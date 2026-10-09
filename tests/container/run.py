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
  ready=subprocess.run(['docker','exec',worker,'setpriv','--reuid=10001','--regid=10001','--clear-groups','--bounding-set=-all','--no-new-privs','python','-c','import isolation_runtime;isolation_runtime.require_isolation()'],cwd=root,capture_output=True)
  if ready.returncode==0:break
  time.sleep(1)
 else:raise RuntimeError('Worker boundary did not become ready')
 for mode in ['network','browser','descendants','quotas','cookie_media']:
  print(run(['docker','exec',worker,'setpriv','--reuid=10001','--regid=10001','--clear-groups','--bounding-set=-all','--no-new-privs','python','/app/tests/container/probe.py',mode],timeout=150))
 from api import validate_video_routes
 validate_video_routes(root)
 fixture=run([*base,'ps','-q','fixtures'])
 metrics=json.loads(run(['docker','exec',fixture,'python','-c',
    "import urllib.request;print(urllib.request.urlopen('http://10.77.0.5/_metrics').read().decode())"]))
 assert metrics['private_hits']==0,metrics
 assert metrics['dns_worker_hits']==0,metrics
 assert metrics['cookie_leaks']==0,metrics
 assert not any(host.startswith(('evilpublic.fixture.test','child.public.fixture.test')) for host in metrics['cookie_hosts']),metrics
 print(json.dumps({'forbidden_fixture_hits':0,'direct_dns_hits':0,'global_fixture_requests':metrics['public_hits']}))
 # A killed service must cause the supervisor/PID namespace to exit.
 result=run(['docker','exec',worker,'setpriv','--reuid=10001','--regid=10001','--clear-groups','--bounding-set=-all','--no-new-privs','python','-c',
   "import os,signal;from process_guard import children;import isolation_runtime;root=isolation_runtime.require_isolation()['supervisor_pid'];from pathlib import Path;pid=next(int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit() and b'/app/deploy/serve.py' in (p/'cmdline').read_bytes());os.kill(pid,signal.SIGKILL)"])
 for attempt in range(30):
  state=run(['docker','inspect','--format','{{.State.Running}}',worker])
  if state=='false':break
  time.sleep(.2)
 else:raise AssertionError('Worker namespace survived service failure')
 print(json.dumps({'service_failure_closes_namespace':True}))
except Exception:
 print(run([*base,'logs','--tail','60']))
 broker=run([*base,'ps','-q','broker'])
 diagnostic=subprocess.run(['docker','exec','-i',broker,'python','-'],cwd=root,
     input=(root/'tests/container/debug_broker.py').read_text(),capture_output=True,text=True)
 print(diagnostic.stdout[-4000:]+diagnostic.stderr[-1000:])
 raise
finally:
 subprocess.run([*base,'down'],cwd=root,check=False)
