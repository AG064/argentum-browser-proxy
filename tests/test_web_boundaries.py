import ast
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote, urlparse, parse_qs
from bs4 import BeautifulSoup
from web_security import decode_form_target, encode_form_target, resolve_form_destination


def load_app(filename, directory):
    source = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'STREAM_DIR' for item in statement.targets):
            statement.value = ast.Constant(str(Path(directory) / filename.replace('.', '-')))
    module = types.ModuleType('fixture_' + filename.replace('.', '_'))
    module.__file__ = str(source)
    exec(compile(ast.fix_missing_locations(tree), str(source), 'exec'), module.__dict__)
    return module


class WebBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='proxy-web-tests-')
        self.module = load_app('proxy.py', self.directory.name)
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def response(self, body, url='https://site.test/redirected/page'):
        return types.SimpleNamespace(status_code=200, content=body.encode(), headers={'Content-Type': 'text/html; charset=utf-8'}, url=url)

    def test_query_values_stay_data_in_every_home_renderer(self):
        value = 'https://site.test/?x="</script><script>window.injected=1</script>&y=\\quoted'
        for filename, route in [('proxy.py', '/browser'), ('browser_app.py', '/browser')]:
            module = load_app(filename, self.directory.name)
            response = module.app.test_client().get(route, query_string={'home': value})
            self.assertEqual(response.status_code, 200)
            soup = BeautifulSoup(response.data, 'html.parser')
            self.assertEqual(soup.find(id='urlBar')['value'], value)
            self.assertEqual(len(soup.find_all('script')), 1)
            self.assertNotIn('</script><script>window.injected', response.get_data(as_text=True))
            self.assertEqual(module.app.test_client().get(route, query_string={'home': 'javascript:alert(1)'}).status_code, 400)

    def test_media_url_is_not_decoded_twice_and_identifiers_are_validated(self):
        value = 'https://site.test/media%2522.mp4?x=" onerror="window.injected=1'
        response = self.client.get('/video-player', query_string={'url': value})
        soup = BeautifulSoup(response.data, 'html.parser')
        self.assertEqual(soup.source['src'], value)
        self.assertNotIn('onerror', soup.source.attrs)
        self.assertEqual(self.client.get('/video-player', query_string={'stream_id': '"><svg/onload=x()>'}).status_code, 400)
        self.assertEqual(self.client.get('/video-player?stream_id=abc123_8').status_code, 200)
        self.assertEqual(self.client.get('/video-player', query_string={'url': 'data:text/html,payload'}).status_code, 400)

    def test_native_form_actions_use_final_response_and_base_and_submitter_override(self):
        body = '<html><head><base href="/forms/"></head><body><form action="../login?old=1" method="post"><input name="q"><button formaction="?override=1" formmethod="get">Go</button></form><form></form></body></html>'
        with patch.object(self.module, 'make_request', return_value=self.response(body)):
            response = self.client.get('/browse?url=https%3A%2F%2Fsite.test%2Foriginal')
        soup = BeautifulSoup(response.data, 'html.parser')
        target = lambda element, attribute: decode_form_target(element[attribute].split('/submit/')[1])
        self.assertEqual(target(soup.find_all('form')[1], 'action'), 'https://site.test/login?old=1')
        self.assertEqual(target(soup.find_all('form')[2], 'action'), 'https://site.test/redirected/page')
        self.assertEqual(target(soup.find('button', formaction=True), 'formaction'), 'https://site.test/forms/?override=1')
        self.assertNotIn('&post=', response.get_data(as_text=True))
        self.assertNotIn('window.location.href =', ''.join(script.get_text() for script in soup.find_all('script')).split('// Detect and handle video players')[0])

    def test_post_preserves_duplicate_blank_unicode_and_reserved_field_names(self):
        data = 'q=one&q=two&empty=&name=%D0%98%D0%BC%D1%8F&url=field&post=field'.encode()
        target = '/submit/' + encode_form_target('https://site.test/login?intent=signin')
        with patch.object(self.module, 'make_request', return_value=self.response('<html></html>')) as call:
            response = self.client.post(target, data=data, content_type='application/x-www-form-urlencoded', headers={'Authorization': 'synthetic-inbound-only'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_args.args[0], 'https://site.test/login?intent=signin')
        self.assertEqual(call.call_args.kwargs['post_data'], data)
        self.assertEqual(call.call_args.kwargs['headers'], {'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertNotIn('q=one', target)

    def test_empty_post_and_cloudflare_retry_keep_the_post_method(self):
        response = self.response('challenge')
        with patch.object(self.module.requests, 'post', return_value=response) as post, patch.object(self.module.requests, 'get') as get, patch.object(self.module, 'check_cloudflare', return_value=True), patch.object(self.module, 'bypass_cloudflare', return_value=('synthetic-cookie', 'synthetic-agent')):
            self.module.make_request('https://site.test/login', post_data=b'')
        self.assertEqual(post.call_count, 2)
        get.assert_not_called()
        self.assertEqual(post.call_args.kwargs['data'], b'')

    def test_multipart_body_and_content_type_are_preserved(self):
        data = b'--fixture\r\nContent-Disposition: form-data; name="file"; filename="sample.bin"\r\n\r\n\x00\xff\r\n--fixture--\r\n'
        with patch.object(self.module, 'make_request', return_value=self.response('<html></html>')) as call:
            self.client.post('/browse?url=https%3A%2F%2Fsite.test%2Fupload', data=data, content_type='multipart/form-data; boundary=fixture')
        self.assertEqual(call.call_args.kwargs['post_data'], data)
        self.assertEqual(call.call_args.kwargs['headers']['Content-Type'], 'multipart/form-data; boundary=fixture')

    def test_get_native_form_and_legacy_payload_rejection(self):
        response = self.client.get('/submit/' + encode_form_target('https://site.test/search?old=1') + '?q=one&q=two&empty=')
        self.assertEqual(response.status_code, 302)
        result = parse_qs(urlparse(response.location).query)['url'][0]
        self.assertEqual(result, 'https://site.test/search?q=one&q=two&empty=')
        with patch.object(self.module, 'make_request') as call:
            self.assertEqual(self.client.get('/browse?url=https%3A%2F%2Fsite.test&post=secret').status_code, 400)
            self.assertEqual(self.client.post('/submit/invalid').status_code, 400)
        call.assert_not_called()

    def test_head_on_form_target_cannot_turn_into_an_upstream_post(self):
        with patch.object(self.module, 'make_request') as call:
            response = self.client.head('/submit/' + encode_form_target('https://site.test/login'))
        self.assertEqual(response.status_code, 302)
        call.assert_not_called()

    def test_form_reference_parser_and_inherited_targets_match_native_controls(self):
        document = 'https://site.test/redirected/page'
        for base in [None, 'javascript:alert(1)', 'data:text/plain,ignored']:
            self.assertEqual(resolve_form_destination(document, base, 'login   '), 'https://site.test/redirected/login')
            self.assertEqual(resolve_form_destination(document, base, '\\login'), 'https://site.test/login')
            self.assertEqual(resolve_form_destination(document, base, '   '), document)
        self.assertEqual(resolve_form_destination(document, '/forms/', 'login?literal=a\\b'), 'https://site.test/forms/login?literal=a\\b')
        with patch.object(self.module, 'make_request', return_value=self.response('<html><head><base target="_blank"></head><body><form method="post" action="login"><button>Send</button></form><a href="other">Link</a></body></html>')):
            response = self.client.get('/browse?url=https%3A%2F%2Fsite.test')
        soup = BeautifulSoup(response.data, 'html.parser')
        self.assertEqual(soup.find_all('form')[1]['target'], '_blank')
        self.assertEqual(soup.find('a', string='Link')['target'], '_blank')

    def test_header_and_error_messages_escape_markup(self):
        value = 'https://site.test/?x=" onfocus="window.injected=1'
        with patch.object(self.module, 'make_request', return_value=self.response('<html><body></body></html>')):
            response = self.client.get('/browse', query_string={'url': value})
        field = BeautifulSoup(response.data, 'html.parser').find('input', attrs={'name': 'url'})
        self.assertEqual(field['value'], value)
        self.assertNotIn('onfocus', field.attrs)
        payload = '<img src=x onerror=window.injected=1>'
        with patch.object(self.module, 'make_request', side_effect=ValueError(payload)):
            response = self.client.get('/browse?url=https%3A%2F%2Fsite.test')
        self.assertFalse(BeautifulSoup(response.data, 'html.parser').find('img'))
        with patch.object(self.module.requests, 'get', side_effect=ValueError(payload)):
            response = self.client.get('/search?q=fixture')
        self.assertFalse(BeautifulSoup(response.data, 'html.parser').find('img'))


if __name__ == '__main__':
    unittest.main()
