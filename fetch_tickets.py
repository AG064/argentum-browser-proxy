"""Short-lived fetch capabilities for sandboxed upstream documents."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import quote
from flask import g
import deployment_access
from web_security import validate_http_url, encode_form_target


def sign(payload):
    return hmac.new(deployment_access.key(), b'public-fetch\0'+payload, hashlib.sha256).hexdigest()


def mint(url):
    validate_http_url(url)
    expiry = min(int(time.time())+300, getattr(g, 'fetch_expiry', int(time.time())+300))
    data = json.dumps([expiry,url], ensure_ascii=False, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip('=')+'.'+sign(data)


def validate(token, url):
    try:
        if not token or len(token) > 16384:
            return None
        encoded, supplied = token.split('.')
        if not re.fullmatch('[A-Za-z0-9_-]+', encoded):
            return None
        data = base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        expiry, target = json.loads(data)
        if type(expiry) is not int or not 0 < expiry-time.time() <= 300 or target != url or not hmac.compare_digest(sign(data), supplied):
            return None
        validate_http_url(target)
        return expiry
    except (ValueError, UnicodeError, OSError, TypeError):
        return None


def browse_url(url):
    return '/browse?url='+quote(url, safe='')+'&cap='+mint(url)


def form_url(url):
    return '/submit/'+encode_form_target(url)+'/'+mint(url)


VIDEO_BRIDGE = '''
(() => {
  function report() {
    const urls = [...document.querySelectorAll('video,video source')]
      .map(node => node.getAttribute('data-argentum-source')).filter(Boolean).slice(0,8);
    window.parent.postMessage({argentumVideos: urls}, '*');
  }
  window.addEventListener('message', event => {
    if (event.source === window.parent && event.data === 'argentum-detect-video') report();
  });
  document.addEventListener('DOMContentLoaded', report);
})();
'''
