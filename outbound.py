"""Application HTTP transport through the verified egress broker."""
import hashlib
import hmac
import os
from pathlib import Path
from urllib.parse import urlencode
import requests
import http.cookiejar
import isolation_runtime as runtime
from web_security import validate_http_url
from cookie_security import requests_cookie_jar


class ScopedSession(requests.Session):
    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        prepared._cookies.set_policy(http.cookiejar.DefaultCookiePolicy(
            strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
        prepared.headers.pop('Cookie', None)
        prepared.prepare_cookies(prepared._cookies)
        return prepared


class HTTPTransport:
    def request(self, method, url, **kwargs):
        validate_http_url(url)
        with ScopedSession() as session:
            session.trust_env = False
            session.max_redirects = 8
            cookies = kwargs.pop('cookies', None)
            if cookies:
                session.cookies = requests_cookie_jar(cookies)
            response = session.request(method, url, proxies=runtime.proxies(), stream=True,
                                       verify='/etc/ssl/certs/ca-certificates.crt', **kwargs)
            content = bytearray()
            try:
                for chunk in response.iter_content(65536):
                    if len(content)+len(chunk) > 64*1024*1024:
                        raise ValueError('Response exceeds the64 MiB limit')
                    content.extend(chunk)
                response._content = bytes(content)
                response._content_consumed = True
                return response
            finally:
                response.close()

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


def search(query, offset):
    marker = runtime.require_isolation()
    key = Path('/run/argentum/access-key').read_bytes().strip()
    token = hmac.new(key, b'fixed-search-gateway', hashlib.sha256).hexdigest()
    url = marker['proxy']+'/_argentum/search?'+urlencode(dict(q=query, offset=offset))
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, headers={'Authorization': 'Bearer '+token}, timeout=8, stream=True) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(65536):
                if len(data)+len(chunk) > 2*1024*1024:
                    raise ValueError('Search response exceeds limit')
                data.extend(chunk)
            return requests.models.complexjson.loads(bytes(data))


client = HTTPTransport()
