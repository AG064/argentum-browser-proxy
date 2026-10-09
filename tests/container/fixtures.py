"""Offline DNS, HTTP, TLS and media fixtures for the container gate."""
import gzip
import http.server
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import threading
import time
from urllib.parse import urlsplit

public='51.78.0.4';private='10.77.0.5'
state={'private_hits':0,'dns_worker_hits':0,'public_hits':0,'cookie_hosts':[],'cookie_leaks':0,'paths':[]}
lock=threading.Lock();rebinding=0
root=Path('/fixture');root.mkdir(exist_ok=True)
# All media and credentials in this topology are synthetic.
subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=128x128:rate=10',
    '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-t','6','-c:v','libx264','-threads','2','-filter_threads','1',
    '-pix_fmt','yuv420p','-c:a','aac','-y',str(root/'movie.mp4')],check=True)
key=root/'key.bin';key.write_bytes(bytes(range(16)))
(root/'key-info').write_text('key.bin\n'+str(key)+'\n')
subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(root/'movie.mp4'),
    '-c','copy','-hls_time','2','-hls_list_size','0','-hls_key_info_file',str(root/'key-info'),
    '-hls_segment_filename',str(root/'good%d.ts'),str(root/'good.m3u8')],check=True)


def dns_answer(data, source):
    global rebinding
    index=12;labels=[]
    while data[index]:
        length=data[index];index+=1;labels.append(data[index:index+length].decode());index+=length
    end=index+5;name='.'.join(labels);kind=struct.unpack('!H',data[index+1:index+3])[0]
    if source[0]== '10.77.0.3':
        with lock:state['dns_worker_hits']+=1
    addresses=[]
    if name=='console.fixture.test':addresses=[private.replace('.5','.4')]
    elif name=='private.fixture.test':addresses=[private]
    elif name=='mixed.fixture.test':addresses=[public,private]
    elif name=='connected.fixture.test':addresses=['51.77.0.4']
    elif name=='rebind.fixture.test':
        if kind==1:rebinding+=1
        addresses=[public if rebinding==1 else private]
    elif name=='local.fixture.test':addresses=['51.77.0.2']
    elif name=='loopback.fixture.test':addresses=['127.0.0.1']
    elif name.endswith('.fixture.test'):addresses=[public]
    answers=b''
    if kind==1:
        for address in addresses:
            answers+=b'\xc0\x0c'+struct.pack('!HHIH',1,1,0,4)+socket.inet_aton(address)
    count=len(addresses) if kind==1 else 0
    return data[:2]+struct.pack('!HHHHH',0x8180,1,count,0,0)+data[12:end]+answers


def dns_server(address):
    server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);server.bind((address,53))
    while True:
        data,source=server.recvfrom(4096)
        try:server.sendto(dns_answer(data,source),source)
        except (ValueError,IndexError,UnicodeError):pass


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def reply(self,data,content='text/plain',status=200,headers=()):
        self.send_response(status);self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close')
        for key,value in headers:self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/_metrics':return self.reply(json.dumps(state).encode(),'application/json')
        with lock:
            if self.server.server_address[0]in (private,'51.77.0.4'):state['private_hits']+=1
            else:
                state['public_hits']+=1
                state['paths'].append(self.path)
                if len(state['paths'])>100:state['paths'].pop(0)
                if self.headers.get('Cookie'):state['cookie_hosts'].append(self.headers.get('Host'))
                if 'private_session=' in self.headers.get('Cookie',''):
                    if self.headers.get('Host')!='public.fixture.test' or not (path=='/video' or path.startswith('/video/')) or not isinstance(self.connection,ssl.SSLSocket):
                        state['cookie_leaks']+=1
        if path=='/redirect-private':return self.reply(b'',status=302,headers=[('Location','http://private.fixture.test/private')])
        if path=='/redirect-public':return self.reply(b'',status=302,headers=[('Location','http://public.fixture.test/bytes')])
        if path in ('/video/redirect-other','/video/redirect-path','/video/redirect-child') and 'private_session=synthetic' not in self.headers.get('Cookie',''):
            return self.reply(b'Fixture cookie required',status=401)
        if path=='/video/redirect-other':return self.reply(b'',status=302,headers=[('Location','http://evilpublic.fixture.test/videox/movie.mp4')])
        if path=='/video/redirect-path':return self.reply(b'',status=302,headers=[('Location','https://public.fixture.test/videox/movie.mp4')])
        if path=='/video/redirect-child':return self.reply(b'',status=302,headers=[('Location','https://child.public.fixture.test/video/movie.mp4')])
        if path=='/bytes':return self.reply(bytes(range(256))*4,'application/octet-stream')
        if path=='/gzip':return self.reply(gzip.compress(b'compressed fixture'),'text/plain',headers=[('Content-Encoding','gzip')])
        if path=='/redirect-bomb':return self.reply(gzip.compress(b'x'*(65*1024*1024)),'text/plain',status=302,headers=[('Content-Encoding','gzip'),('Location','http://public.fixture.test/bytes')])
        if path=='/range':
            data=b'0123456789'
            if self.headers.get('Range')=='bytes=2-4':return self.reply(data[2:5],status=206,headers=[('Content-Range','bytes 2-4/10')])
            return self.reply(data)
        if path=='/provider':
            page=b'<html><body><video src="/movie.mp4?token=%252F"></video><script>fetch("http://private.fixture.test/private").catch(()=>{});new WebSocket("ws://private.fixture.test/socket");</script></body></html>'
            return self.reply(page,'text/html',headers=[('Set-Cookie','session=fixture; Path=/; HttpOnly')])
        if path=='/bad.m3u8':return self.reply(b'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nhttp://private.fixture.test/private.ts\n#EXT-X-ENDLIST\n','application/vnd.apple.mpegurl')
        if path=='/good.m3u8':return self.reply((root/'good.m3u8').read_bytes(),'application/vnd.apple.mpegurl')
        if path=='/key.bin' or (path.startswith('/good') and path.endswith('.ts') and path[5:-3].isdigit()):
            return self.reply((root/path.lstrip('/')).read_bytes(),'application/octet-stream')
        if path in ('/movie.mp4','/video/movie.mp4','/videox/movie.mp4'):return self.reply((root/'movie.mp4').read_bytes(),'video/mp4')
        if path=='/cookie':return self.reply(self.headers.get('Cookie','').encode())
        return self.reply(b'PRIVATE_FIXTURE' if self.server.server_address[0]==private else b'PUBLIC_FIXTURE')
    def do_POST(self):
        data=self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.reply(data,'application/octet-stream')
    def log_message(self,*args):pass


for address in (public,private):
    threading.Thread(target=dns_server,args=(address,),daemon=True).start()
servers=[]
for address in (public,private,'51.77.0.4'):
    server=http.server.ThreadingHTTPServer((address,80),Handler)
    servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
server=http.server.ThreadingHTTPServer((public,443),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain('/secrets/provider.crt','/secrets/provider.key')
server.socket=context.wrap_socket(server.socket,server_side=True)
threading.Thread(target=server.serve_forever,daemon=True).start()
while True:time.sleep(60)
