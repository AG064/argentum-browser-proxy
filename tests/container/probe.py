"""Run real transports inside the production worker namespace."""
import hashlib
import json
import socket
import sys
sys.path.insert(0,'/app')
from pathlib import Path
import subprocess
import os
os.environ.pop('HOME',None)
import isolation_runtime as runtime
from outbound import client
from job_tools import run_guarded


def blocked_connection(host,port,family=socket.AF_INET):
    connection=socket.socket(family,socket.SOCK_STREAM);connection.settimeout(1)
    try:
        connection.connect((host,port))
        return False
    except OSError:return True
    finally:connection.close()


def network():
    runtime.require_isolation()
    assert blocked_connection('10.77.0.5',80)
    assert blocked_connection('127.0.0.1',8765)
    assert blocked_connection('10.77.0.1',8888)
    assert blocked_connection('51.78.0.4',80)
    assert blocked_connection('::1',8765,socket.AF_INET6)
    udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.settimeout(1)
    packet=b'\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06public\x07fixture\x04test\x00\x00\x01\x00\x01'
    udp.sendto(packet,('10.77.0.5',53))
    try:udp.recvfrom(4096);raise AssertionError('Direct UDP succeeded')
    except socket.timeout:pass
    finally:udp.close()
    for scheme in ['http','https']:
        response=client.get(scheme+'://public.fixture.test/bytes',timeout=5,allow_redirects=True)
        assert response.status_code==200
        assert response.content==bytes(range(256))*4
    response=client.post('http://public.fixture.test/echo?token=%252F',data=b'a=one&a=two&empty=',timeout=5,allow_redirects=True)
    assert response.content==b'a=one&a=two&empty='
    partial=client.get('http://public.fixture.test/range',headers={'Range':'bytes=2-4'},timeout=5,allow_redirects=True)
    assert partial.status_code==206 and partial.content==b'234'
    for host in ['private.fixture.test','loopback.fixture.test','mixed.fixture.test','local.fixture.test','connected.fixture.test','127.1','2130706433','169.254.169.254']:
        response=client.get('http://'+host+'/private',timeout=5,allow_redirects=True)
        assert response.status_code==403,(host,response.status_code)
    response=client.get('http://public.fixture.test/redirect-private',timeout=5,allow_redirects=True)
    assert response.status_code==403
    try:
        client.get('http://public.fixture.test/redirect-bomb',timeout=5,allow_redirects=True)
        raise AssertionError('Oversized redirect body bypassed the limit')
    except ValueError:pass
    good=client.get('http://rebind.fixture.test/bytes',timeout=5,allow_redirects=True)
    bad=client.get('http://rebind.fixture.test/private',timeout=5,allow_redirects=True)
    assert good.status_code==200 and bad.status_code==403
    try:
        client.get('https://wrong.fixture.test/bytes',timeout=5,allow_redirects=True)
        raise AssertionError('Invalid TLS host succeeded')
    except __import__('requests').exceptions.SSLError:pass
    print(json.dumps({'direct_egress_blocked':True,'real_http_https':True,'private_redirects_and_rebinding_blocked':True}))


def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as engine:
        browser=engine.chromium.launch(**runtime.browser_options())
        try:
            page=browser.new_page()
            page.goto('https://public.fixture.test/provider',wait_until='domcontentloaded',timeout=15000)
            page.wait_for_timeout(1000)
            assert page.locator('video').count()==1
            assert page.evaluate("fetch('http://private.fixture.test/private').then(r=>r.ok).catch(()=>false)") is False
        finally:browser.close()
    for command in [['node','/app/cloudflare.js','https://public.fixture.test/provider'],
                    [sys.executable,'/app/cloudflare.py','https://public.fixture.test/provider']]:
        result=run_guarded(command,seconds=60)
        assert result.returncode==0,result.stderr
        data=json.loads(result.stdout)
        assert data and data.get('cookies')
    print(json.dumps({'python_browser_sandbox':True,'node_helper':True,'python_helper':True}))


def descendants():
    script="import os,time;pid=os.fork();\nif pid==0:\n os.setsid();open('/runtime/detached.pid','w').write(str(os.getpid()));time.sleep(60)\nelse:\n while not os.path.exists('/runtime/detached.pid'):time.sleep(.01)"
    result=run_guarded([sys.executable,'-c',script],seconds=2)
    assert result.returncode==0
    pid=int(Path('/runtime/detached.pid').read_text())
    assert not Path('/proc/'+str(pid)).exists()
    print(json.dumps({'detached_descendants_reaped':True}))




def quotas():
    runtime.require_isolation()
    path=Path('/runtime/quota-probe.bin')
    created=False
    try:
        with path.open('xb') as stream:
            created=True
            written=0
            while True:
                try:stream.write(b'x'*(4*1024*1024));stream.flush();written+=4*1024*1024
                except OSError:break
                assert written <=256*1024*1024
        assert written <256*1024*1024
    finally:
        if created:path.unlink()
    print(json.dumps({'hard_runtime_quota':True}))


def cookie_media():
    import media_client
    import requests
    cookies=[dict(name='private_session',value='synthetic',domain='public.fixture.test',path='/video',secure=True,expires=-1)]
    for path in ('redirect-other','redirect-path','redirect-child'):
        registered=media_client.register('https://public.fixture.test/video/'+path,cookies)
        try:
            session=requests.Session();session.trust_env=False
            response=session.get(registered['url'],timeout=15)
            assert response.status_code==200 and response.content
            session.close()
        finally:media_client.unregister(registered['cap'])
    print(json.dumps({'cookie_downgrade_suffix_subdomain_and_path_scoped':True}))

if __name__=='__main__':
    {'network':network,'browser':browser,'descendants':descendants,'quotas':quotas,'cookie_media':cookie_media}[sys.argv[1]]()
