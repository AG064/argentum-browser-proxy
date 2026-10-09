from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent/'private'
root.mkdir(mode=0o700,exist_ok=True)
def run(args):subprocess.run(['openssl',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
run(['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Fixture CA','-keyout',str(root/'ca.key'),'-out',str(root/'ca.crt')])
run(['req','-newkey','rsa:2048','-nodes','-subj','/CN=public.fixture.test','-keyout',str(root/'provider.key'),'-out',str(root/'provider.csr')])
(root/'provider.ext').write_text('subjectAltName=DNS:public.fixture.test,DNS:rebind.fixture.test,DNS:child.public.fixture.test,DNS:evilpublic.fixture.test\n')
run(['x509','-req','-in',str(root/'provider.csr'),'-CA',str(root/'ca.crt'),'-CAkey',str(root/'ca.key'),'-CAcreateserial','-days','1','-extfile',str(root/'provider.ext'),'-out',str(root/'provider.crt')])
print('Created synthetic fixture certificates')
