"""Exercise every public video route through the production TLS gateway."""
import json
from pathlib import Path
import time
import requests
from bs4 import BeautifulSoup


def validate_video_routes(root):
    code=(root/'deploy/private/access-code').read_text().strip()
    certificate=str(root/'deploy/private/tls.crt')
    source='http://public.fixture.test/movie.mp4?token=%252F'
    cases=[(8765,'/watch','/stream/stop/'),(8765,'/transcode','/hls/stop/'),
           (8767,'/browser/stream/start','/browser/stream/stop/'),(8788,'/stream','/stop/'),(8788,'/proxy','/stop/')]
    sessions={}
    for port,route,stop in cases:
        base='https://127.0.0.1:'+str(port)
        if port not in sessions:
            session=requests.Session();session.trust_env=False
            signed=session.post(base+'/login',data={'code':code},headers={'Origin':base},verify=certificate,allow_redirects=False,timeout=5)
            assert signed.status_code==303,signed.status_code
            sessions[port]=session
        session=sessions[port]
        result=session.get(base+route,params={'url':source},headers={'Origin':base},verify=certificate,allow_redirects=False,timeout=15)
        assert result.status_code in (200,302),(route,result.status_code,result.text[:200])
        if route=='/watch':
            path=BeautifulSoup(result.text,'html.parser').find('source')['src']
            key=path.split('/')[2]
        elif route=='/proxy':path=result.headers['Location'];key='direct'
        else:
            data=result.json();key=data['stream_id'];assert data['status']=='started'
            path=data.get('hls_url') or data.get('playlist_url') or '/browser/hls/'+key+'/playlist.m3u8'
        # Start replies precede the first completed HLS segment.
        deadline=time.monotonic()+15
        while True:
            playlist=session.get(base+path,verify=certificate,timeout=5)
            if playlist.status_code==200 or time.monotonic()>=deadline:break
            assert playlist.status_code==404,(route,playlist.status_code,playlist.text[:200])
            time.sleep(.2)
        assert playlist.status_code==200 and '#EXTM3U' in playlist.text,(route,playlist.status_code,playlist.text[:200])
        assert playlist.headers['Cache-Control']=='no-cache'
        segment=next(line for line in playlist.text.splitlines() if line and not line.startswith('#'))
        partial=session.get(base+path.rsplit('/',1)[0]+'/'+segment,headers={'Range':'bytes=0-3'},verify=certificate,timeout=5)
        assert partial.status_code==206 and len(partial.content)==4
        stopped=session.get(base+stop+key,headers={'Origin':base},verify=certificate,timeout=10)
        assert stopped.status_code==200
        assert session.get(base+path,verify=certificate,timeout=5).status_code==404
    session=sessions[8765];base='https://127.0.0.1:8765'
    for scheme in ('http','https'):
        good=session.get(base+'/transcode',params={'url':scheme+'://public.fixture.test/good.m3u8'},headers={'Origin':base},verify=certificate,timeout=15)
        assert good.status_code==200,(scheme,good.status_code,good.text[:200])
        data=good.json();assert data['status']=='started'
        assert session.get(base+'/hls/stop/'+data['stream_id'],headers={'Origin':base},verify=certificate,timeout=10).status_code==200
    failed=session.get(base+'/transcode',params={'url':'http://public.fixture.test/bad.m3u8'},headers={'Origin':base},verify=certificate,timeout=15)
    assert failed.status_code==500,failed.status_code
    for session in sessions.values():session.close()
    print(json.dumps({'all_five_video_routes':True,'hls_ranges_and_stop':True,'encrypted_http_https_hls_inputs':True,'private_hls_fetch_blocked':True}))
