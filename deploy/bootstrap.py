"""Generate private deployment credentials and a local TLS certificate."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('private'))
    args = parser.parse_args()
    try:
        subject = 'IP:'+str(ipaddress.ip_address(args.host))
    except ValueError:
        host = args.host.encode('idna').decode('ascii')
        if len(host) > 253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', part) for part in host.split('.')):
            parser.error('A host name or IP address is required')
        subject = 'DNS:'+host
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output directory must be empty; existing credentials are preserved')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = args.output/'access-code'
    descriptor = os.open(key, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(secrets.token_urlsafe(32)+'\n')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-sha256', '-nodes', '-days', '365',
        '-subj', '/CN=Argentum Proxy', '-addext', 'subjectAltName='+subject,
        '-keyout', str(args.output/'tls.key'), '-out', str(args.output/'tls.crt')],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    os.chmod(args.output/'tls.key', 0o600)
    print('Private credentials and TLS certificate created in '+str(args.output.resolve()))


if __name__ == '__main__':
    main()
