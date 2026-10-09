import os
from pathlib import Path
import sys
root = Path('/run/argentum')
root.mkdir(mode=0o755, exist_ok=True)
with open('/secrets/access-code', 'rb') as stream:
    key = stream.read(129).strip()
if not 32 <= len(key) <= 128:
    raise RuntimeError('Invalid access code')
path = root/'access-key'
path.write_bytes(key)
os.chown(path, 0, 10002)
os.chmod(path, 0o440)
os.environ['ARGENTUM_ACCESS_KEY_FILE'] = str(path)
# The pinned broker image uses files/DNS resolution without mDNS NSS plugins.
configuration = Path('/etc/nsswitch.conf').read_text()
hosts = next(line.split(':',1)[1].split() for line in configuration.splitlines() if line.startswith('hosts:'))
if hosts != ['files','dns']:
    raise RuntimeError('Unexpected host resolver configuration')
os.execvp('setpriv', ['setpriv', '--reuid=10002', '--regid=10002', '--clear-groups', '--bounding-set=-all',
    '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs', sys.executable, '/app/egress_broker.py'])
