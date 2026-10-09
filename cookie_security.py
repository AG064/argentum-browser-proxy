"""Domain/path/secure scoping for browser cookies sent by server transports."""
import re
import time
import math
from urllib.parse import urlsplit


def matching_cookies(cookies, url):
    parsed = urlsplit(url)
    host, path = (parsed.hostname or '').lower(), parsed.path or '/'
    if not isinstance(cookies, list) or len(cookies) > 128:
        raise ValueError('Invalid cookie set')
    output = []
    for cookie in cookies:
        name, value = cookie.get('name', ''), cookie.get('value', '')
        domain, scope = cookie.get('domain', '').lower(), cookie.get('path', '/')
        if (not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", name)
                or not isinstance(value, str) or len(value) > 4096
                or any(ord(c) < 32 or ord(c) > 126 or c in ';,\\' for c in value)
                or not domain or any(c in domain for c in '/\\; \r\n')
                or not scope.startswith('/') or any(c in scope for c in ';\r\n')):
            raise ValueError('Invalid cookie')
        suffix = domain.lstrip('.')
        if host != suffix and not (domain.startswith('.') and host.endswith('.'+suffix)):
            continue
        if path != scope and not (path.startswith(scope) and (scope.endswith('/') or path[len(scope):].startswith('/'))):
            continue
        if cookie.get('secure') and parsed.scheme != 'https':
            continue
        expires = cookie.get('expires', -1)
        if not isinstance(expires, (int, float)) or not math.isfinite(expires) or (expires != -1 and expires <= time.time()):
            continue
        output.append(cookie)
    return output


def cookie_header(cookies, url):
    return '; '.join(c['name']+'='+c['value'] for c in matching_cookies(cookies, url))


def ffmpeg_cookies(cookies, url):
    return '\n'.join(c['name']+'='+c['value']+'; path='+c.get('path', '/')+'; domain='+c['domain']+';'
                     for c in matching_cookies(cookies, url))


def requests_cookie_jar(cookies):
    import http.cookiejar
    import requests
    jar = requests.cookies.RequestsCookieJar()
    jar.set_policy(http.cookiejar.DefaultCookiePolicy(strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
    for cookie in cookies:
        domain = cookie.get('domain', '')
        host = domain.lstrip('.')
        # Reuse validation without altering the original domain/path scope.
        scheme = 'https' if cookie.get('secure') else 'http'
        if not matching_cookies([cookie], scheme+'://'+host+cookie.get('path','/')):
            continue
        item = requests.cookies.create_cookie(cookie['name'], cookie['value'], domain=domain,
                    path=cookie.get('path','/'), secure=bool(cookie.get('secure')))
        item.domain_specified = domain.startswith('.')
        item.domain_initial_dot = domain.startswith('.')
        expires = cookie.get('expires', -1)
        item.expires = None if expires == -1 else int(expires)
        jar.set_cookie(item)
    return jar
