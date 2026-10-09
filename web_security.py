"""Encoding and navigation boundaries for proxy-owned pages and forms."""
import base64
import binascii
import re
from urllib.parse import urlsplit, urljoin


def validate_http_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid URL')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('HTTP or HTTPS URL required')
        if parsed.username is not None or parsed.password is not None or '\\' in parsed.netloc or '%' in parsed.netloc:
            raise ValueError('Invalid authority')
        parsed.port
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid HTTP or HTTPS URL') from error
    return value


def encode_form_target(value):
    validate_http_url(value)
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode('ascii').rstrip('=')


def resolve_form_destination(document_url, base_href, action):
    """Match HTTP form-reference rules while keeping proxy routing separate."""
    def reference(value):
        value = value.strip(''.join(chr(code) for code in range(33)))
        value = value.replace('\t', '').replace('\r', '').replace('\n', '')
        split = re.split(r'(?=[?#])', value, maxsplit=1)
        return split[0].replace('\\', '/') + (split[1] if len(split) > 1 else '')

    base_url = document_url
    if base_href is not None:
        candidate = urljoin(document_url, reference(base_href))
        try:
            base_url = validate_http_url(candidate)
        except ValueError:
            pass
    action = reference(action)
    return validate_http_url(urljoin(base_url, action) if action else document_url)


def decode_form_target(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid form target')
    try:
        result = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True).decode('utf-8')
        return validate_http_url(result)
    except (binascii.Error, ValueError, UnicodeError) as error:
        raise ValueError('Invalid form target') from error
