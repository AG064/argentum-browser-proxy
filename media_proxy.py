"""Per-job media HTTP transport with browser-compatible cookie scope."""
import base64
import hashlib
import http.server
import json
from pathlib import Path
import secrets
import socket
import socketserver
import threading
import time
from urllib.parse import urlsplit,urljoin
from outbound import ScopedSession, limit_response
from cookie_security import requests_cookie_jar
from web_security import validate_http_url
import isolation_runtime as runtime
import re

entries={}
lock=threading.Lock()


def encode(url):return base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')
def media_url(cap,url):return 'http://127.0.0.1:18890/'+cap+'/'+encode(validate_http_url(url))


class Registry(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            user=__import__('struct').unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if user !=10001:return
            raw=self.rfile.readline(65537)
            if len(raw)>65536:return
            data=json.loads(raw)
            with lock:
                for cap in list(entries):
                    if entries[cap]['expires'] <=time.monotonic():entries.pop(cap)
                if data.get('action')=='delete':
                    entries.pop(data['cap'],None);reply={'removed':True}
                else:
                    if len(entries)>=6:raise ValueError('Media capacity reached')
                    url=validate_http_url(data['url']);jar=requests_cookie_jar(data['cookies'])
                    cap=secrets.token_urlsafe(32)
                    entries[cap]={'cookies':data['cookies'],'expires':time.monotonic()+14400}
                    reply={'url':media_url(cap,url),'cap':cap}
            self.wfile.write(json.dumps(reply).encode()+b'\n')
        except (ValueError,KeyError,OSError):self.wfile.write(b'{"error":"Media registration failed"}\n')


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_HEAD(self):return self.transfer(head=True)
    def do_GET(self):return self.transfer()
    def transfer(self,head=False):
        self.close_connection=True
        try:
            cap,encoded=self.path.lstrip('/').split('/',1)
            with lock:
                entry=entries.get(cap)
                if not entry or entry['expires']<=time.monotonic():raise ValueError('Unknown media job')
                cookies=list(entry['cookies'])
            if len(encoded)>16384:raise ValueError('Invalid target')
            url=validate_http_url(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)).decode())
            with ScopedSession() as session:
                session.trust_env=False;session.max_redirects=8
                session.cookies=requests_cookie_jar(cookies)
                def bound_redirect(response,*args,**kwargs):
                    return limit_response(response) if response.is_redirect else response
                session.hooks['response'].append(bound_redirect)
                headers={name:self.headers[name] for name in ('Range','If-None-Match','If-Modified-Since') if name in self.headers}
                headers['Accept-Encoding']='identity'
                with session.request('HEAD' if head else 'GET',url,headers=headers,proxies=runtime.proxies(),
                        verify='/etc/ssl/certs/ca-certificates.crt',timeout=15,stream=True) as response:
                    kind=response.headers.get('Content-Type','').split(';')[0]
                    hls=kind in ('application/vnd.apple.mpegurl','application/x-mpegurl') or urlsplit(response.url).path.endswith('.m3u8')
                    if hls and not head and response.status_code==200:
                        data=bytearray()
                        for chunk in response.iter_content(65536):
                            if len(data)+len(chunk)>1024*1024:raise ValueError('Playlist exceeds limit')
                            data.extend(chunk)
                        lines=[]
                        def rewrite(target):return media_url(cap,urljoin(response.url,target))
                        for line in data.decode('utf-8').splitlines():
                            if line and not line.startswith('#'):line=rewrite(line)
                            elif line.startswith('#'):line=re.sub(r'URI="([^"]*)"',lambda match:'URI="'+rewrite(match.group(1))+'"',line)
                            lines.append(line)
                        output=('\n'.join(lines)+'\n').encode()
                        self.send_response(200);self.send_header('Content-Type','application/vnd.apple.mpegurl')
                        self.send_header('Content-Length',str(len(output)));self.send_header('Connection','close');self.end_headers();self.wfile.write(output)
                    else:
                        self.send_response(response.status_code)
                        for name in ('Content-Type','Content-Length','Content-Range','Accept-Ranges','Content-Encoding'):
                            if name in response.headers:self.send_header(name,response.headers[name])
                        self.send_header('Connection','close');self.end_headers()
                        if not head:
                            for chunk in response.raw.stream(65536,decode_content=False):self.wfile.write(chunk)
        except Exception:
            self.send_error(502,'Media transport failed')


class Server(http.server.ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,*args):
        self.capacity=threading.BoundedSemaphore(16)
        super().__init__(*args)
    def process_request(self,request,address):
        if not self.capacity.acquire(False):request.close();return
        try:super().process_request(request,address)
        except Exception:self.capacity.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.capacity.release()


if __name__=='__main__':
    runtime.require_isolation()
    path=Path('/runtime/media.sock')
    registry=socketserver.UnixStreamServer(str(path),Registry)
    __import__('os').chmod(path,0o600)
    threading.Thread(target=registry.serve_forever,daemon=True).start()
    Server(('127.0.0.1',18890),Handler).serve_forever()
