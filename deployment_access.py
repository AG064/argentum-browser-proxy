"""Owner access through HTTPS cookies; all code holders share one deployment."""
import hashlib
import hmac
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit
from flask import request, redirect, Response, g
import isolation_runtime as runtime

COOKIE = 'argentum_access'
LIFETIME = 8*3600
LOGIN = '<!doctype html><meta charset="utf-8"><title>Argentum access</title><h1>Argentum access</h1><form method="post"><label>Access code <input name="code" type="password" maxlength="128" autocomplete="current-password" required></label><button>Sign in</button></form>'


def key():
    value = Path('/run/argentum/access-key').read_bytes().strip()
    if not 32 <= len(value) <= 128:
        raise ValueError('Invalid access key')
    return value


def signature(payload):
    return hmac.new(key(), payload.encode('ascii'), hashlib.sha256).hexdigest()


def valid_cookie(value):
    if not value or len(value) > 256:
        return False
    try:
        issued, nonce, supplied = value.split('.')
        timestamp = int(issued)
        return 0 <= time.time()-timestamp <= LIFETIME and len(nonce) == 32 and secrets.compare_digest(signature(issued+'.'+nonce), supplied)
    except (ValueError, OSError):
        return False


def enforce_request():
    try:
        runtime.require_isolation()
    except runtime.IsolationUnavailable:
        return 'Start the isolated deployment to use this service.', 503
    if request.path == '/login':
        return None
    if request.endpoint in ('browse', 'submit_form'):
        from fetch_tickets import validate
        from web_security import decode_form_target
        try:
            target = request.args.get('url', '') if request.endpoint == 'browse' else decode_form_target(request.view_args['target'])
            token = request.args.get('cap') if request.endpoint == 'browse' else request.view_args.get('ticket')
            expiry = validate(token, target)
            if expiry:
                g.fetch_expiry = expiry
                return None
        except ValueError:
            return 'Invalid target', 400
    if not valid_cookie(request.cookies.get(COOKIE)):
        if request.method == 'GET':
            return redirect('/login', code=303)
        return 'Sign in required', 401
    origin = request.headers.get('Origin')
    if origin is not None and origin != 'https://'+request.host:
        return 'Invalid request origin', 403
    controls = {'watch', 'transcode_video', 'extract_video', 'stream_start', 'stream', 'proxy', 'stream_stop', 'stop_hls', 'stop'}
    if request.method not in ('GET', 'HEAD', 'OPTIONS') or (request.endpoint in controls and request.method == 'GET'):
        reference = request.headers.get('Referer')
        if origin != 'https://'+request.host:
            parsed = urlsplit(reference or '')
            if origin is not None or parsed.scheme != 'https' or parsed.netloc != request.host or parsed.path not in ('/', '/browser', '/video-player', '/argentum_browser.html', '/search'):
                return 'Invalid request origin', 403
    return None


def install(app):
    app.config['MAX_CONTENT_LENGTH'] = 32*1024*1024
    app.before_request(enforce_request)

    @app.after_request
    def isolate_upstream(response):
        if request.endpoint in ('browse', 'submit_form'):
            origin = 'https://'+request.host
            response.headers['Content-Security-Policy'] = (
                "sandbox allow-scripts allow-forms; default-src 'none'; "
                "script-src 'unsafe-inline' "+origin+"; style-src 'unsafe-inline' "+origin+
                '; img-src '+origin+' data: blob:; media-src '+origin+' blob:; connect-src '+origin+
                '; frame-src '+origin+'; form-action '+origin+"; base-uri 'none'")
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def owner_login():
        if request.method == 'GET':
            response = Response(LOGIN, mimetype='text/html')
        else:
            if request.headers.get('Origin') != 'https://'+request.host:
                return 'Invalid request origin', 403
            code = request.form.get('code', '')
            if len(code) > 128 or not secrets.compare_digest(code.encode('utf-8'), key()):
                return 'Invalid access code', 403
            payload = str(int(time.time()))+'.'+secrets.token_hex(16)
            response = redirect('/', code=303)
            response.set_cookie(COOKIE, payload+'.'+signature(payload), secure=True, httponly=True, samesite='Strict', max_age=LIFETIME)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response
