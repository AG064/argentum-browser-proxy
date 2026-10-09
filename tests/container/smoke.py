from pathlib import Path
import json
import subprocess
import time
import requests

root=Path(__file__).resolve().parents[2]
code=(root/'deploy/private/access-code').read_text().strip()
certificate=str(root/'deploy/private/tls.crt')
session=requests.Session();session.trust_env=False
base='https://127.0.0.1:8765'
container=subprocess.check_output(['docker','compose','ps','-q','worker'],cwd=root,text=True).strip()
for attempt in range(30):
    probe=subprocess.run(['docker','exec','--user','10001',container,'python','-c',
        'import isolation_runtime;print(isolation_runtime.require_isolation()["version"])'],capture_output=True,text=True)
    if probe.returncode==0:break
    time.sleep(1)
else:raise RuntimeError('Worker check failed: '+probe.stderr)
last='no connection'
for attempt in range(90):
    try:
        result=session.get(base+'/login',verify=certificate,timeout=2)
        last=str(result.status_code)+' '+result.text[:120]
        if result.status_code==200:break
    except requests.RequestException as error:last=type(error).__name__+': '+str(error)[:250]
    time.sleep(1)
else:raise RuntimeError('Isolated service did not become ready: '+last)
unauthorized=session.get(base+'/version',verify=certificate,allow_redirects=False,timeout=5)
assert unauthorized.status_code in (303,404)
response=session.post(base+'/login',data={'code':code},headers={'Origin':base},verify=certificate,allow_redirects=False,timeout=5)
assert response.status_code==303,response.status_code
cookie=response.headers['Set-Cookie']
assert all(item in cookie for item in ('Secure','HttpOnly','SameSite=Strict'))
assert session.get(base+'/browser',verify=certificate,timeout=5).status_code==200
container=subprocess.check_output(['docker','compose','ps','-q','worker'],cwd=root,text=True).strip()
probe=subprocess.run(['docker','exec','--user','10001',container,'python','-c',
    'import isolation_runtime;print(isolation_runtime.require_isolation()["version"])'],capture_output=True,text=True)
assert probe.returncode==0,probe.stderr
assert probe.stdout.strip()=='1'
print(json.dumps({'tls_login':True,'owner_browser':True,'runtime_caps_verified':True}))
