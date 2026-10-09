"""HTTP egress broker. Connections use validated numeric peers exactly once."""
import hmac
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit, urlencode
import urllib.request


class DestinationDenied(ValueError):
    pass


TRANSITION_NETWORKS = tuple(ipaddress.ip_network(value) for value in
    ('64:ff9b::/96', '64:ff9b:1::/48', '2001::/32', '2002::/16'))


def public_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved or address.is_unspecified:
        return False
    if address.version == 6:
        if address.ipv4_mapped or address.is_site_local or any(address in network for network in TRANSITION_NETWORKS):
            return False
    return True


def authority(value, default_port=None):
    if not value or len(value) > 512 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or any(c in value for c in '/\\%?#@'):
        raise DestinationDenied('Invalid destination authority')
    try:
        parsed = urlsplit('//'+value)
        host = parsed.hostname
        port = parsed.port or default_port
        if not host or port not in (80, 443):
            raise ValueError()
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            host = host.rstrip('.').encode('idna').decode('ascii').lower()
            if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError()
        return host, port
    except (ValueError, UnicodeError):
        raise DestinationDenied('Invalid destination authority') from None


def ip_command(*arguments):
    result = subprocess.run(['ip', '-j', *arguments], capture_output=True, timeout=2, check=True)
    if len(result.stdout) > 65536:
        raise DestinationDenied('Network topology is too large')
    return json.loads(result.stdout)


def route_source(address):
    family = '-6' if address.version == 6 else '-4'
    defaults = ip_command(family, 'route', 'show', 'default')
    interfaces = {row['dev'] for row in defaults if row.get('dev') and row.get('type', 'unicast') == 'unicast'}
    route = ip_command(family, 'route', 'get', str(address))
    if len(route) != 1 or route[0].get('type', 'unicast') != 'unicast' or route[0].get('dev') not in interfaces:
        raise DestinationDenied('Destination does not use the external route')
    source = route[0].get('prefsrc') or route[0].get('src')
    if not source:
        raise DestinationDenied('External source address is unavailable')
    for interface in ip_command('address'):
        for row in interface.get('addr_info', []):
            if ipaddress.ip_address(row['local']) == address:
                raise DestinationDenied('Host addresses are not allowed')
    return source


class DestinationPolicy:
    def __init__(self, resolver=socket.getaddrinfo, source_for=route_source, deny_networks=()):
        self.resolver, self.source_for = resolver, source_for
        self.denied = tuple(ipaddress.ip_network(value) for value in deny_networks)

    def addresses(self, host, port):
        records = self.resolver(host, port, type=socket.SOCK_STREAM)
        if not records or len(records) > 32:
            raise DestinationDenied('Destination resolution failed')
        output = []
        for family, kind, protocol, name, sockaddr in records:
            if family not in (socket.AF_INET, socket.AF_INET6) or (family == socket.AF_INET6 and sockaddr[3]):
                raise DestinationDenied('Scoped addresses are not allowed')
            address = ipaddress.ip_address(sockaddr[0])
            if not public_address(str(address)) or any(address in network for network in self.denied):
                raise DestinationDenied('Destination is not public')
            pair = (family, str(address))
            if pair not in output:
                output.append(pair)
        return output

    def connect(self, host, port):
        addresses = self.addresses(host, port)
        for family, value in addresses:
            connection = socket.socket(family, socket.SOCK_STREAM)
            connection.settimeout(15)
            try:
                source = self.source_for(ipaddress.ip_address(value))
                if source:
                    connection.bind((source, 0))
                target = (value, port) if family == socket.AF_INET else (value, port, 0, 0)
                connection.connect(target)
                return connection
            except (OSError, subprocess.SubprocessError, DestinationDenied):
                connection.close()
        raise DestinationDenied('No permitted destination is reachable')


def relay(client, upstream, *, max_seconds=14400, max_client_bytes=32*1024*1024, http_response=False):
    deadline = time.monotonic() + max_seconds
    client_bytes = 0
    client_open = True
    response_header = bytearray()
    while time.monotonic() < deadline:
        ready, _, _ = select.select(([client] if client_open else [])+[upstream], [], [], max(0, min(15, deadline-time.monotonic())))
        if not ready:
            break
        for source in ready:
            chunk = source.recv(65536)
            if not chunk:
                if source is upstream:
                    return
                client_open = False
                upstream.shutdown(socket.SHUT_WR)
                continue
            if source is client:
                client_bytes += len(chunk)
                if client_bytes > max_client_bytes:
                    return
            elif http_response:
                response_header.extend(chunk)
                boundary = response_header.find(b'\r\n\r\n')
                if boundary < 0:
                    if len(response_header) > 65536:
                        return
                    continue
                lines = bytes(response_header[:boundary]).split(b'\r\n')
                status = int(lines[0].split()[1])
                if status < 200 and status != 101:
                    client.sendall(bytes(response_header[:boundary+4]))
                    response_header = bytearray(response_header[boundary+4:])
                    # Interim headers normally arrive separately; process an already
                    # buffered final response without waiting for another packet.
                    if not response_header:
                        continue
                    boundary = response_header.find(b'\r\n\r\n')
                    if boundary < 0:
                        continue
                    lines = bytes(response_header[:boundary]).split(b'\r\n')
                    status = int(lines[0].split()[1])
                if status != 101:
                    lines = [line for line in lines if not line.lower().startswith((b'connection:', b'proxy-connection:'))]
                    lines.append(b'Connection: close')
                chunk = b'\r\n'.join(lines)+b'\r\n\r\n'+bytes(response_header[boundary+4:])
                http_response = False
            (upstream if source is client else client).sendall(chunk)


class BrokerHandler(http.server.BaseHTTPRequestHandler):
    rbufsize = 0
    protocol_version = 'HTTP/1.1'

    def log_message(self, *arguments):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _allowed_client(self):
        return ipaddress.ip_address(self.client_address[0]) in self.server.allowed_clients

    def _headers_valid(self):
        if sum(len(k)+len(v) for k,v in self.headers.items()) > 65536:
            return False
        lengths = self.headers.get_all('Content-Length', [])
        encodings = self.headers.get_all('Transfer-Encoding', [])
        if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
            return False
        if lengths and (not re.fullmatch(r'[0-9]{1,10}', lengths[0]) or int(lengths[0]) > 32*1024*1024):
            return False
        if encodings and encodings[0].lower() != 'chunked':
            return False
        return True

    def _reject(self, status, message):
        self.close_connection = True
        self.send_error(status, message)

    def do_CONNECT(self):
        if not self._allowed_client() or not self._headers_valid():
            return self._reject(403, 'Access denied')
        established = False
        try:
            host, port = authority(self.path)
            if port != 443:
                raise DestinationDenied('CONNECT requires HTTPS')
            with self.server.policy.connect(host, port) as upstream:
                self.send_response(200, 'Connection established')
                self.end_headers()
                self.wfile.flush()
                established = True
                relay(self.connection, upstream)
        except (DestinationDenied, OSError, ValueError, subprocess.SubprocessError):
            if established:
                self.close_connection = True
            else:
                self._reject(403, 'Destination denied')
        finally:
            self.close_connection = True

    def _forward(self):
        if not self._allowed_client() or not self._headers_valid():
            return self._reject(403, 'Access denied')
        if self.path.startswith('/_argentum/search?'):
            return self._search()
        try:
            if len(self.path) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in self.path):
                raise DestinationDenied('Invalid target')
            parsed = urlsplit(self.path)
            if parsed.scheme != 'http' or parsed.fragment:
                raise DestinationDenied('Absolute HTTP target required')
            host, port = authority(parsed.netloc, 80)
            if port != 80:
                raise DestinationDenied('HTTP requires port80')
            target = (parsed.path or '/') + ('?'+parsed.query if parsed.query else '')
            host_header = parsed.netloc
            upgrade = self.headers.get('Upgrade', '').lower() == 'websocket'
            hop = {'host', 'proxy-authorization', 'proxy-connection', 'connection'}
            hop.update(x.strip().lower() for x in self.headers.get('Connection', '').split(',') if x.strip())
            if upgrade:
                hop.discard('upgrade')
            headers = [(k,v) for k,v in self.headers.items() if k.lower() not in hop]
            first = self.command+' '+target+' HTTP/1.1\r\nHost: '+host_header+'\r\n'
            first += 'Connection: '+('Upgrade' if upgrade else 'close')+'\r\n'
            first += ''.join(k+': '+v+'\r\n' for k,v in headers)+'\r\n'
            with self.server.policy.connect(host, port) as upstream:
                upstream.sendall(first.encode('latin1'))
                relay(self.connection, upstream, http_response=True)
        except (DestinationDenied, OSError, ValueError, UnicodeError, subprocess.SubprocessError):
            self._reject(403, 'Destination denied')
        finally:
            self.close_connection = True

    def _search(self):
        expected = self.server.search_token
        if self.command != 'GET' or not expected or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+expected):
            return self._reject(403, 'Access denied')
        from urllib.parse import parse_qs
        parameters = parse_qs(urlsplit(self.path).query)
        query = parameters.get('q', [''])[0]
        offset = parameters.get('offset', ['0'])[0]
        if len(query) > 500 or not offset.isdigit() or not 0 <= int(offset) <= 10000:
            return self._reject(400, 'Invalid search')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            endpoint = self.server.search_endpoint+'?'+urlencode(dict(q=query, offset=int(offset), format='json', lang='ru'))
            with opener.open(endpoint, timeout=5) as response:
                data = response.read(2*1024*1024+1)
            if len(data) > 2*1024*1024:
                raise ValueError()
            json.loads(data)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self._reject(502, 'Search unavailable')
        self.close_connection = True

    do_GET = _forward
    do_HEAD = _forward
    do_POST = _forward
    do_PUT = _forward
    do_DELETE = _forward
    do_OPTIONS = _forward
    do_PATCH = _forward


class BrokerServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address, *, allowed_clients, policy=None, search_token='', search_endpoint='http://127.0.0.1:8888/search'):
        self.capacity = threading.BoundedSemaphore(32)
        self.allowed_clients = {ipaddress.ip_address(value) for value in allowed_clients}
        self.policy = policy or DestinationPolicy(deny_networks=filter(None, os.environ.get('ARGENTUM_EGRESS_DENY_CIDRS','').split(',')))
        self.search_token, self.search_endpoint = search_token, search_endpoint
        super().__init__(address, BrokerHandler)

    def process_request(self, request, address):
        if not self.capacity.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.capacity.release()


if __name__ == '__main__':
    import hashlib
    key = Path(os.environ['ARGENTUM_ACCESS_KEY_FILE']).read_bytes().strip()
    search_token = hmac.new(key, b'fixed-search-gateway', hashlib.sha256).hexdigest()
    BrokerServer((os.environ.get('ARGENTUM_BROKER_BIND', '10.77.0.1'), 3128),
        allowed_clients=[os.environ.get('ARGENTUM_WORKER_IP', '10.77.0.3')], search_token=search_token,
        search_endpoint=os.environ.get('ARGENTUM_SEARCH_ENDPOINT', 'http://127.0.0.1:8888/search')).serve_forever()
