"""Install the worker network boundary before dropping root privileges."""
import json
import ipaddress
import os
from pathlib import Path
import resource
import subprocess


def command(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def firewall(table, broker, gateway):
    command(table, '-P', 'OUTPUT', 'DROP')
    command(table, '-P', 'INPUT', 'DROP')
    command(table, '-P', 'FORWARD', 'DROP')
    command(table, '-F')
    command(table, '-A', 'OUTPUT', '-m', 'conntrack', '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT')
    command(table, '-A', 'INPUT', '-m', 'conntrack', '--ctstate', 'ESTABLISHED', '-j', 'ACCEPT')
    if table == 'iptables':
        command(table, '-A', 'OUTPUT', '-p', 'tcp', '-d', broker, '--dport', '3128', '-m', 'conntrack', '--ctstate', 'NEW', '-j', 'ACCEPT')
        command(table, '-A', 'INPUT', '-p', 'tcp', '-s', gateway, '-m', 'multiport', '--dports', '8765,8767,8788', '-m', 'conntrack', '--ctstate', 'NEW', '-j', 'ACCEPT')
    saved = subprocess.check_output([table+'-save']).decode()
    if ':OUTPUT DROP' not in saved or ':INPUT DROP' not in saved:
        raise RuntimeError('Firewall verification failed')


def main():
    if os.getuid() != 0:
        raise RuntimeError('Worker bootstrap requires root')
    broker = str(ipaddress.IPv4Address(os.environ.get('ARGENTUM_BROKER_IP', '10.77.0.1')))
    gateway = str(ipaddress.IPv4Address(os.environ.get('ARGENTUM_GATEWAY_IP', '10.77.0.4')))
    firewall('iptables', broker, gateway)
    firewall('ip6tables', broker, gateway)
    root = Path('/run/argentum')
    root.mkdir(mode=0o755, exist_ok=True)
    with open('/secrets/access-code', 'rb') as stream:
        key = stream.read(129).strip()
    if not 32 <= len(key) <= 128:
        raise RuntimeError('Invalid access code')
    secret = root/'access-key'
    secret.write_bytes(key)
    os.chown(secret, 0, 10001)
    os.chmod(secret, 0o440)
    os.chown('/runtime', 10001, 10001)
    for name in ('jobs', 'home', 'cache', 'config'):
        path = Path('/runtime')/name
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, 10001, 10001)
    certificates = Path('/usr/local/share/ca-certificates')
    if list(certificates.glob('*.crt')):
        store = Path('/runtime/home/.pki/nssdb')
        store.mkdir(parents=True, mode=0o700, exist_ok=True)
        command('certutil', '-d', 'sql:'+str(store), '-N', '--empty-password')
        for certificate in certificates.glob('*.crt'):
            command('certutil', '-d', 'sql:'+str(store), '-A', '-n', certificate.name, '-t', 'C,,', '-i', str(certificate))
        for path in [store.parent, store, *store.iterdir()]:
            os.chown(path, 10001, 10001)
    marker = root/'isolation.json'
    marker.write_text(json.dumps(dict(version=1, broker_ip=broker, proxy='http://'+broker+':3128',
        net_namespace=os.readlink('/proc/self/ns/net'), supervisor_pid=os.getpid())))
    os.chmod(marker, 0o444)
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for variable in ('HOME','http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy','NO_PROXY','no_proxy'):
        os.environ.pop(variable, None)
    os.execvp('setpriv', ['setpriv', '--reuid=10001', '--regid=10001', '--clear-groups', '--bounding-set=-all',
        '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs', '/usr/local/bin/python', '/app/deploy/supervisor.py'])


if __name__ == '__main__':
    main()
