import concurrent.futures
import hashlib
import http.server
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from flask import Flask, g
import requests
import egress_broker as broker
import deployment_access as access
import fetch_tickets as tickets
import isolation_runtime as runtime
from cookie_security import cookie_header, requests_cookie_jar
from outbound import ScopedSession


class PolicyTests(unittest.TestCase):
    def test_address_classes_and_authority_encodings(self):
        for value in ['127.0.0.1','10.1.2.3','172.16.0.1','192.168.1.1','169.254.169.254','100.64.0.1','0.0.0.0','224.1.1.1','192.0.2.1','::1','::','fc00::1','fe80::1','ff02::1','::ffff:8.8.8.8','64:ff9b::a00:1','2002:0808:0808::1']:
            self.assertFalse(broker.public_address(value), value)
        self.assertTrue(broker.public_address('51.77.0.4'))
        self.assertTrue(broker.public_address('2606:4700:4700::1111'))
        for value in ['user@public.test:443', 'public.test:22','public.test:443/path','[fe80::1%eth0]:443','public.test\\x:443']:
            with self.assertRaises(broker.DestinationDenied):
                broker.authority(value)

    def test_mixed_answers_and_rebinding_are_denied(self):
        records = lambda address: (socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))
        resolver = unittest.mock.Mock(side_effect=[[records('51.77.0.4')],[records('127.0.0.1')]])
        policy = broker.DestinationPolicy(resolver=resolver)
        self.assertEqual(policy.addresses('public.test',443), [(socket.AF_INET,'51.77.0.4')])
        with self.assertRaises(broker.DestinationDenied):
            policy.addresses('public.test',443)
        mixed = broker.DestinationPolicy(resolver=lambda *a,**k:[records('51.77.0.4'),records('10.0.0.1')])
        with self.assertRaises(broker.DestinationDenied):
            mixed.addresses('public.test',443)

    def test_connection_uses_one_numeric_peer(self):
        resolver = unittest.mock.Mock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('51.77.0.4',80))])
        connection = unittest.mock.Mock()
        policy = broker.DestinationPolicy(resolver=resolver,source_for=lambda address:'51.77.0.2')
        with patch.object(broker.socket,'socket',return_value=connection):
            self.assertIs(policy.connect('public.test',80),connection)
        resolver.assert_called_once()
        connection.connect.assert_called_once_with(('51.77.0.4',80))
        connection.bind.assert_called_once_with(('51.77.0.2',0))

    def test_local_route_and_host_addresses_are_denied(self):
        cases = [[{'dev':'eth0'}],[],[{'dev':'lo','type':'local','prefsrc':'51.77.0.2'}]]
        with patch.object(broker,'ip_command',side_effect=cases):
            with self.assertRaises(broker.DestinationDenied):
                broker.route_source(__import__('ipaddress').ip_address('51.77.0.2'))

    def test_broker_preserves_post_bytes_range_and_redirects(self):
        seen = []
        class Origin(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_POST(self):
                data = self.rfile.read(int(self.headers['Content-Length']))
                seen.append((self.path,self.headers.get('Host'),data))
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302);self.send_header('Location','http://public.test/final');self.send_header('Content-Length','0');self.end_headers();return
                data = b'0123456789'
                if self.headers.get('Range') == 'bytes=2-4':
                    data = data[2:5];self.send_response(206);self.send_header('Content-Range','bytes 2-4/10')
                else:self.send_response(200)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        origin = http.server.ThreadingHTTPServer(('127.0.0.1',0),Origin)
        threading.Thread(target=origin.serve_forever,daemon=True).start()
        class FixturePolicy:
            def connect(self,host,port):
                if host != 'public.test':raise broker.DestinationDenied('Rejected')
                return socket.create_connection(origin.server_address,timeout=2)
        proxy = broker.BrokerServer(('127.0.0.1',0),allowed_clients=['127.0.0.1'],policy=FixturePolicy())
        threading.Thread(target=proxy.serve_forever,daemon=True).start()
        try:
            session = requests.Session();session.trust_env=False
            proxies={'http':'http://127.0.0.1:'+str(proxy.server_port)}
            data=b'field=one&field=two&empty=&signed=%252F'+bytes(range(128))
            result=session.post('http://public.test/path?token=%252F',data=data,proxies=proxies,timeout=3)
            self.assertEqual(result.content,data)
            self.assertEqual(seen,[('/path?token=%252F','public.test',data)])
            partial=session.get('http://public.test/range',headers={'Range':'bytes=2-4'},proxies=proxies,timeout=3)
            self.assertEqual(partial.status_code,206);self.assertEqual(partial.content,b'234')
            redirected=session.get('http://public.test/redirect',proxies=proxies,timeout=3)
            self.assertEqual(redirected.url,'http://public.test/final')
            denied=session.get('http://private.test/',proxies=proxies,timeout=3)
            self.assertEqual(denied.status_code,403)
            session.close()
        finally:
            proxy.shutdown();proxy.server_close();origin.shutdown();origin.server_close()


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.key=self.enterContext(patch.object(access,'key',return_value=b'K'*43))
        self.enterContext(patch.object(runtime,'require_isolation',return_value={}))
        self.app=Flask('access-tests');access.install(self.app)
        @self.app.route('/watch')
        def watch():return 'work'
        @self.app.route('/browse')
        def browse():return 'public document'
        @self.app.route('/submit/<target>/<ticket>',methods=['GET','POST'])
        def submit_form(target,ticket):return request_body()
        def request_body():
            from flask import request
            return request.get_data()
        self.client=self.app.test_client()

    def login(self):
        return self.client.post('/login',base_url='https://localhost',data={'code':'K'*43},headers={'Origin':'https://localhost'})

    def test_authentication_and_secure_cookie_are_required(self):
        self.assertEqual(self.client.get('/watch',base_url='https://localhost').status_code,303)
        response=self.login();self.assertEqual(response.status_code,303)
        cookie=response.headers['Set-Cookie']
        for property in ['Secure','HttpOnly','SameSite=Strict']:self.assertIn(property,cookie)
        self.assertEqual(self.client.get('/watch',base_url='https://localhost',headers={'Origin':'https://localhost'}).data,b'work')
        self.assertEqual(self.client.get('/watch',base_url='https://localhost',headers={'Origin':'null'}).status_code,403)
        self.assertEqual(self.client.get('/watch',base_url='https://localhost',headers={'Referer':'https://localhost/browse?url=public'}).status_code,403)

    def test_cookie_expiry_and_forgery(self):
        payload=str(int(time.time())-access.LIFETIME-1)+'.'+'a'*32
        self.assertFalse(access.valid_cookie(payload+'.'+access.signature(payload)))
        self.assertFalse(access.valid_cookie(str(int(time.time()))+'.'+'a'*32+'.'+'f'*64))

    def test_fetch_capabilities_cannot_renew_or_access_controls(self):
        url='https://public.test/path?token=%252F'
        with self.app.test_request_context():
            g.fetch_expiry=int(time.time())+100
            token=tickets.mint(url)
            expiry=tickets.validate(token,url)
            self.assertLessEqual(expiry,int(time.time())+100)
            self.assertIsNone(tickets.validate(token,url+'x'))
            self.assertIsNone(tickets.validate(token[:-1]+('0' if token[-1] != '0' else '1'),url))
        response=self.client.get('/browse',query_string={'url':url,'cap':token},base_url='https://localhost')
        self.assertEqual(response.status_code,200)
        self.assertIn('sandbox allow-scripts allow-forms',response.headers['Content-Security-Policy'])
        self.assertNotIn('allow-same-origin',response.headers['Content-Security-Policy'])
        self.assertEqual(self.client.get('/watch',query_string={'url':url,'cap':token},base_url='https://localhost').status_code,303)
        from web_security import encode_form_target
        body=b'field=one&field=two&empty='
        result=self.client.post('/submit/'+encode_form_target(url)+'/'+token,base_url='https://localhost',data=body,headers={'Origin':'null'})
        self.assertEqual(result.data,body)

    def test_unisolated_execution_fails_closed(self):
        with patch.object(runtime,'require_isolation',side_effect=runtime.IsolationUnavailable('missing')):
            self.assertEqual(self.client.get('/watch').status_code,503)


class CookieTests(unittest.TestCase):
    def test_domain_path_secure_and_redirect_cookie_scope(self):
        cookies=[dict(name='session',value='fixture',domain='public.test',path='/video',secure=True,expires=-1)]
        self.assertEqual(cookie_header(cookies,'https://public.test/video/movie'),'session=fixture')
        for url in ['https://other.test/video','https://public.test/videox','http://public.test/video']:
            self.assertEqual(cookie_header(cookies,url),'')
        session=ScopedSession();session.cookies=requests_cookie_jar(cookies)
        own=session.prepare_request(requests.Request('GET','https://public.test/video'))
        child=session.prepare_request(requests.Request('GET','https://child.public.test/video'))
        self.assertEqual(own.headers.get('Cookie'),'session=fixture')
        self.assertNotIn('Cookie',child.headers)
        wrong_path=session.prepare_request(requests.Request('GET','https://public.test/videox'))
        downgrade=session.prepare_request(requests.Request('GET','http://public.test/video'))
        suffix=session.prepare_request(requests.Request('GET','https://evilpublic.test/video'))
        for prepared in (wrong_path,downgrade,suffix):self.assertNotIn('Cookie',prepared.headers)
        session.close()

    def test_malformed_cookie_state_is_rejected(self):
        with self.assertRaises(ValueError):
            cookie_header([dict(name='session',value='x\r\nHeader: injected',domain='public.test')],'https://public.test/')

    def test_cookie_media_uses_the_scoped_fetch_service(self):
        command=['ffmpeg','-i','https://public.test/video','output.m3u8']
        cookies=[dict(name='session',value='fixture',domain='public.test',path='/video',secure=True,expires=-1)]
        with patch.object(runtime,'require_isolation',return_value={'proxy':'http://broker:3128'}):
            with patch('media_client.register',return_value={'url':'http://127.0.0.1:18890/cap/media','cap':'cap'}) as registered:
                prepared=runtime.ffmpeg_options(command,cookies)
        registered.assert_called_once_with(command[2],cookies)
        self.assertEqual(prepared.media_cap,'cap')
        self.assertEqual(prepared[prepared.index('-i')+1],'http://127.0.0.1:18890/cap/media')
        self.assertNotIn('-cookies',prepared)

    def test_every_redirect_body_is_limited_before_following(self):
        from outbound import limit_response
        response=unittest.mock.Mock()
        response.iter_content.return_value=iter([b'x'*(64*1024*1024),b'x'])
        with self.assertRaises(ValueError):limit_response(response)
        response.close.assert_called_once()


class RouteTests(unittest.TestCase):
    def test_connected_and_specific_routes_on_default_interface_are_denied(self):
        import ipaddress
        for prefix in ['51.77.0.0/24','51.77.0.4/32']:
            replies=[[{'dev':'eth0','gateway':'51.77.0.1'}],[{'dst':prefix,'dev':'eth0'}]]
            with patch.object(broker,'ip_command',side_effect=replies):
                with self.assertRaises(broker.DestinationDenied):broker.route_source(ipaddress.ip_address('51.77.0.4'))
