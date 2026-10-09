import ipaddress
import os
from pathlib import Path
import shutil
import subprocess

worker = str(ipaddress.IPv4Address(os.environ.get('ARGENTUM_WORKER_IP','10.77.0.3')))
for table in ('iptables','ip6tables'):
    def rule(*args):
        subprocess.run([table,*args],check=True)
    rule('-P','OUTPUT','DROP');rule('-P','INPUT','DROP');rule('-P','FORWARD','DROP');rule('-F')
    rule('-A','OUTPUT','-m','conntrack','--ctstate','ESTABLISHED','-j','ACCEPT')
    rule('-A','INPUT','-m','conntrack','--ctstate','ESTABLISHED','-j','ACCEPT')
    if table == 'iptables':
        rule('-A','OUTPUT','-p','tcp','-d',worker,'-m','multiport','--dports','8765,8767,8788','-m','conntrack','--ctstate','NEW','-j','ACCEPT')
        rule('-A','INPUT','-p','tcp','-m','multiport','--dports','8765,8767,8788','-m','conntrack','--ctstate','NEW','-j','ACCEPT')
private=Path('/run/argentum');private.mkdir(mode=0o700,exist_ok=True)
for name in ('client-body','proxy','fastcgi','uwsgi','scgi'):
    directory=Path('/tmp')/name
    directory.mkdir(mode=0o700,exist_ok=True)
    os.chown(directory,101,101)
for name in ('tls.crt','tls.key'):
    shutil.copyfile('/secrets/'+name,private/name)
    os.chmod(private/name,0o600)
os.execvp('setpriv',['setpriv','--bounding-set=-all,+setuid,+setgid','--inh-caps=-all','--ambient-caps=-all','--no-new-privs','nginx','-g','daemon off;'])
