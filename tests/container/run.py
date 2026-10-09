from pathlib import Path
import json
import os
import subprocess
import time
import requests
root=Path(__file__).resolve().parents[2]
base=['docker','compose','-f','compose.yaml','-f','tests/container/compose.test.yaml']
def run(args,**kwargs):
 result=subprocess.run(args,cwd=root,capture_output=True,text=True,**kwargs)
 if result.returncode:raise RuntimeError(result.stdout[-1500:]+result.stderr[-1500:])
 return result.stdout.strip()
run([*base,'up','-d'])
try:
 worker=run([*base,'ps','-q','worker'])
 for attempt in range(90):
  ready=subprocess.run(['docker','exec','--user','10001',worker,'python','-c','import isolation_runtime;isolation_runtime.require_isolation()'],cwd=root,capture_output=True)
  if ready.returncode==0:break
  time.sleep(1)
 else:raise RuntimeError('Worker boundary did not become ready')
 for mode in ['network','browser','descendants']:
  print(run(['docker','exec','--user','10001',worker,'python','/app/tests/container/probe.py',mode],timeout=150))
 fixture=run([*base,'ps','-q','fixtures'])
 metrics=json.loads(run(['docker','exec',fixture,'python','-c',
    "import urllib.request;print(urllib.request.urlopen('http://10.77.0.5/_metrics').read().decode())"]))
 assert metrics['private_hits']==0,metrics
 assert metrics['dns_worker_hits']==0,metrics
 print(json.dumps({'forbidden_fixture_hits':0,'direct_dns_hits':0,'global_fixture_requests':metrics['public_hits']}))
except Exception:
 print(run([*base,'logs','--tail','60']))
 raise
finally:
 subprocess.run([*base,'down'],cwd=root,check=False)
