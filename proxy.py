from flask import Flask, request, Response, redirect, render_template_string, send_file
from urllib.parse import quote, parse_qs, urlparse, unquote
import requests
from bs4 import BeautifulSoup
import chardet
import subprocess
import json
import os
import signal
import uuid
import time

app = Flask(__name__)

STREAM_DIR = '/tmp/hls_streams'
os.makedirs(STREAM_DIR, exist_ok=True)
STREAMS = {}

CLOUDFLARE_CACHE = {}

def check_cloudflare(url, resp):
    """Check if response is a Cloudflare challenge"""
    if resp.status_code in [403, 429, 503]:
        content = resp.text[:2000].lower()
        if 'cloudflare' in content or 'checking your browser' in content:
            return True
    return False

def bypass_cloudflare(url):
    """Use Playwright to bypass Cloudflare and get cookies"""
    cache_key = urlparse(url).netloc
    
    # Check in-memory cache (5 min TTL)
    if cache_key in CLOUDFLARE_CACHE:
        cached = CLOUDFLARE_CACHE[cache_key]
        if cached.get('time', 0) > time.time() - 300:
            return cached.get('cookies'), cached.get('user_agent')
    
    try:
        result = subprocess.run(
            ['/home/agx/.proxy/cloudflare.sh', url],
            capture_output=True,
            text=True,
            timeout=60,
            cwd='/home/agx/.proxy'
        )
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if data.get('success'):
                cookies = data.get('cookies', [])
                user_agent = data.get('user_agent', '')
                
                # Build cookie string for requests
                cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
                
                # Cache result
                CLOUDFLARE_CACHE[cache_key] = {
                    'cookies': cookies,
                    'user_agent': user_agent,
                    'cookie_str': cookie_str,
                    'time': time.time()
                }
                
                return cookie_str, user_agent
    except Exception as e:
        print(f"[Cloudflare] Bypass error: {e}")
    
    return None, None

def make_request(url, headers=None, timeout=15, post_data=None):
    """Make HTTP request with Cloudflare bypass support"""
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
    }
    if headers:
        default_headers.update(headers)
    
    # Use POST if post_data is provided
    if post_data:
        resp = requests.post(url, headers=default_headers, data=post_data, timeout=timeout, allow_redirects=True)
    else:
        resp = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
    
    # Check if Cloudflare challenge
    if check_cloudflare(url, resp):
        print(f"[Cloudflare] Detected challenge for {urlparse(url).netloc}, attempting bypass...")
        
        cookie_str, user_agent = bypass_cloudflare(url)
        
        if cookie_str:
            print(f"[Cloudflare] Bypass successful, retrying with cookies...")
            default_headers['Cookie'] = cookie_str
            if user_agent:
                default_headers['User-Agent'] = user_agent
            
            if post_data:
                resp = requests.post(url, headers=default_headers, data=post_data, timeout=timeout, allow_redirects=True)
            else:
                resp = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
    
    return resp

import time

SEARCH_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Argentum Proxy</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0a0a0a; min-height: 100vh; font-family: Arial, sans-serif; color: #e8e8e8; }
        .container { max-width: 900px; margin: 0 auto; padding: 40px 20px; }
        h1 { color: #f0a500; text-align: center; margin-bottom: 30px; font-weight: 300; letter-spacing: 4px; }
        .search-box { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 6px; display: flex; }
        .search-box input { flex: 1; background: #2a2a2a; border: none; padding: 12px 16px; font-size: 16px; color: #fff; outline: none; }
        .search-box button { background: #f0a500; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-weight: 600; color: #000; }
        .bookmarks { margin-top: 30px; display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
        .bookmark { background: #1a1a1a; border: 1px solid #333; padding: 10px 16px; border-radius: 8px; color: #f0a500; text-decoration: none; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ARGENTUM PROXY</h1>
        <form method="get" action="/search">
            <div class="search-box">
                <input type="text" name="q" placeholder="Search..." autofocus>
                <button type="submit">Search</button>
            </div>
        </form>
        <div class="bookmarks">
            <a href="/browse?url=https://kinopoisk.ru" class="bookmark">Кинопоиск</a>
            <a href="/browse?url=https://www.youtube.com" class="bookmark">YouTube</a>
            <a href="/browse?url=http://localhost:8888" class="bookmark">SearXNG</a>
        </div>
    </div>
</body>
</html>'''

RESULTS_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Search Results</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0a0a0a; min-height: 100vh; font-family: Arial, sans-serif; color: #e8e8e8; }
        .container { max-width: 900px; margin: 0 auto; padding: 20px; }
        .header { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 6px; display: flex; margin-bottom: 20px; }
        .header input { flex: 1; background: #2a2a2a; border: none; padding: 12px 16px; font-size: 16px; color: #fff; outline: none; }
        .header button { background: #f0a500; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-weight: 600; color: #000; }
        .result { background: #111; border-radius: 8px; padding: 15px; margin: 15px 0; }
        .result a { color: #f0a500; font-size: 18px; text-decoration: none; display: block; margin-bottom: 5px; }
        .result a:hover { color: #ffc233; }
        .result-url { color: #4caf50; font-size: 12px; margin-bottom: 5px; word-break: break-all; }
        .result-snippet { color: #9aa0a6; font-size: 14px; line-height: 1.5; }
        .engine { color: #666; font-size: 10px; margin-top: 5px; }
        .no-results { text-align: center; color: #666; padding: 40px; }
        .back-link { color: #f0a500; margin-bottom: 20px; display: inline-block; }
        .pagination { display: flex; gap: 10px; justify-content: center; margin-top: 20px; }
        .pagination a { background: #1a1a1a; border: 1px solid #333; padding: 10px 20px; border-radius: 8px; color: #f0a500; text-decoration: none; }
        .pagination a:hover { background: #2a2a2a; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">Home</a>
        <form method="get" action="/search">
            <div class="header">
                <input type="text" name="q" value="{{query}}" autofocus>
                <button type="submit">Search</button>
            </div>
        </form>
        {% if results %}
        {% for r in results %}
        <div class="result">
            <a href="/browse?url={{r.url|encode}}">{{r.title|safe}}</a>
            <div class="result-url">{{r.url|truncate(80)}}</div>
            <div class="result-snippet">{{r.content|safe}}</div>
            <div class="engine">{{r.engine}}</div>
        </div>
        {% endfor %}
        <div class="pagination">
            {% if page > 0 %}
            <a href="/search?q={{query|encode}}&page={{page-1}}">Prev</a>
            {% endif %}
            <a href="/search?q={{query|encode}}&page={{page+1}}">Next</a>
        </div>
        {% else %}
        <div class="no-results">No results found</div>
        {% endif %}
    </div>
</body>
</html>'''

@app.template_filter('encode')
def encode_filter(s):
    return quote(s, safe='')

@app.template_filter('truncate')
def truncate_filter(s, length=80):
    if len(s) > length:
        return s[:length] + '...'
    return s

def decode_content(content, content_type):
    """Try multiple encodings to properly decode content"""
    # Try UTF-8 first
    try:
        return content.decode('utf-8'), 'utf-8'
    except:
        pass
    
    # Try detected encoding
    detected = chardet.detect(content)
    encoding = detected.get('encoding', '')
    if encoding:
        try:
            return content.decode(encoding), encoding
        except:
            pass
    
    # Try common Russian encodings
    for enc in ['windows-1251', 'cp1251', 'koi8-r', 'iso-8859-5']:
        try:
            return content.decode(enc), enc
        except:
            pass
    
    # Fallback to UTF-8 with replacement
    return content.decode('utf-8', errors='replace'), 'utf-8'

@app.route('/')
def index():
    return render_template_string(SEARCH_TEMPLATE)

@app.route('/search')
def search():
    q = request.args.get('q', '')
    if not q:
        return redirect('/')
    
    page = int(request.args.get('page', 0))
    offset = page * 20
    
    try:
        resp = requests.get(f'http://localhost:8888/search?q={quote(q)}&format=json&lang=ru&offset={offset}', timeout=15)
        data = resp.json()
        
        results = []
        for r in data.get('results', [])[:20]:
            results.append({
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'content': r.get('content', '')[:300],
                'engine': r.get('engine', '')
            })
        
        return render_template_string(RESULTS_TEMPLATE, query=q, results=results, page=page)
    except Exception as e:
        return f'<html><body style="background:#0a0a;color:#fff;padding:20px"><h2>Error: {str(e)}</h2><a href="/">Back</a></body></html>'

@app.route('/browse', methods=['GET', 'POST'])
def browse():
    url = request.args.get('url', '')
    
    # Handle POST from our JavaScript interceptor (form submitted via proxy)
    post_raw = request.args.get('post', '')
    if post_raw:
        # Parse the post data from URL parameter
        from urllib.parse import parse_qs
        post_data = {k: v[0] for k, v in parse_qs(post_raw).items()}
    elif request.method == 'POST' and request.form:
        # Direct POST to /browse endpoint
        post_data = dict(request.form)
    else:
        post_data = None
    
    if not url:
        return redirect('/')
    
    try:
        resp = make_request(url, post_data=post_data)
        content_type = resp.headers.get('Content-Type', '')
        content = resp.content
        
        if 'text/html' in content_type:
            text, used_encoding = decode_content(content, content_type)
            soup = BeautifulSoup(text, 'html.parser')
            
            # Set correct charset
            if soup.head:
                meta = soup.find('meta', attrs={'charset': True})
                if meta:
                    meta['charset'] = 'utf-8'
            
            for attr in ['src', 'href', 'action', 'data-src']:
                for tag in soup.find_all(attrs={attr: True}):
                    val = tag[attr]
                    if val.startswith('//'):
                        val = 'https:' + val
                    elif val.startswith('/'):
                        parsed = requests.utils.urlparse(url)
                        val = f"{parsed.scheme}://{parsed.netloc}{val}"
                    elif val and not val.startswith('http'):
                        parsed = requests.utils.urlparse(url)
                        val = f"{parsed.scheme}://{parsed.netloc}/{val}"
                    if val and val.startswith('http'):
                        tag[attr] = f'/browse?url={quote(val)}'
            
            for meta in soup.find_all('meta', attrs={'http-equiv': 'refresh'}):
                content = meta.get('content', '')
                if 'url=' in content.lower():
                    idx = content.lower().index('url=')
                    target_url = content[idx+4:].split(';')[0].strip('"\'')
                    meta['content'] = f'0;url=/browse?url={quote(target_url)}'
            
            style = soup.new_tag('style')
            style.string = '''
                body { background: #0a0a0a !important; color: #e8e8e8 !important; }
                a { color: #f0a500 !important; }
                a:visited { color: #c0c0c0 !important; }
                img { max-width: 100%; height: auto; background: transparent !important; }
                iframe { width: 100%; height: 600px; border: none; }
                video { max-width: 100%; }
                input, textarea { background: #1a1a1a !important; color: #fff !important; border: 1px solid #444 !important; }
                button { background: #333 !important; color: #fff !important; border: 1px solid #555 !important; }
                .header { background: #1a1a1a !important; padding: 10px; margin-bottom: 15px; border-bottom: 1px solid #333; position: sticky; top: 0; z-index: 9999; }
                .header a { color: #c0c0c0 !important; margin-right: 15px; text-decoration: none; }
                .header input { background: #2a2a2a !important; border: 1px solid #444 !important; color: #fff !important; padding: 8px; width: 300px; }
                .header button { background: #333 !important; color: #fff !important; border: 1px solid #555 !important; padding: 8px 16px; cursor: pointer; }
            '''
            if soup.head:
                soup.head.append(style)
            
            # Add JavaScript to intercept form submissions and video players
            script = soup.new_tag('script')
            script.string = '''
                document.addEventListener('DOMContentLoaded', function() {
                    // Intercept form submissions
                    document.addEventListener('submit', function(e) {
                        var form = e.target;
                        if (form.method && form.method.toLowerCase() === 'post') {
                            e.preventDefault();
                            var formData = new FormData(form);
                            var params = new URLSearchParams();
                            for (var pair of formData.entries()) {
                                params.append(pair[0], pair[1]);
                            }
                            var action = form.action || window.location.href;
                            if (!action.startsWith('http')) {
                                action = window.location.origin + action;
                            }
                            window.location.href = '/browse?url=' + encodeURIComponent(action) + '&post=' + encodeURIComponent(params.toString());
                        }
                    });
                    
                    // Intercept search inputs
                    document.addEventListener('keypress', function(e) {
                        if (e.key === 'Enter') {
                            var input = e.target;
                            if (input.tagName === 'INPUT' && (input.type === 'search' || input.name === 'q' || input.name === 'query' || input.name === 'search')) {
                                e.preventDefault();
                                var value = input.value;
                                var form = input.form;
                                if (form && form.action) {
                                    var action = form.action;
                                    if (!action.startsWith('http')) {
                                        action = window.location.origin + action;
                                    }
                                    if (action.includes('?')) {
                                        action += '&' + input.name + '=' + encodeURIComponent(value);
                                    } else {
                                        action += '?' + input.name + '=' + encodeURIComponent(value);
                                    }
                                    window.location.href = '/browse?url=' + encodeURIComponent(action);
                                }
                            }
                        }
                    });
                    
                    // Detect and handle video players
                    var videoButtons = [];
                    
                    // Find iframes (common for embedded players)
                    document.querySelectorAll('iframe').forEach(function(iframe) {
                        var src = iframe.src || '';
                        if (src && !src.includes('youtube') && !src.includes('vk.com')) {
                            videoButtons.push({type: 'iframe', src: src, element: iframe});
                        }
                    });
                    
                    // Find video tags
                    document.querySelectorAll('video').forEach(function(video) {
                        var src = video.src || video.currentSrc || '';
                        if (src) {
                            videoButtons.push({type: 'video', src: src, element: video});
                        }
                        // Also check for source tags
                        video.querySelectorAll('source').forEach(function(source) {
                            if (source.src) {
                                videoButtons.push({type: 'source', src: source.src, element: video});
                            }
                        });
                    });
                    
                    // Find embed tags
                    document.querySelectorAll('embed').forEach(function(embed) {
                        var src = embed.src || embed.getAttribute('flashvars') || '';
                        if (src) videoButtons.push({type: 'embed', src: src, element: embed});
                    });
                    
                    // Add watch button if videos found
                    if (videoButtons.length > 0) {
                        var playerBar = document.createElement('div');
                        playerBar.id = 'proxy-player-bar';
                        playerBar.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#1a1a1a;border-top:2px solid #f0a500;padding:15px;display:flex;align-items:center;justify-content:center;z-index:999999;';
                        
                        var btn = document.createElement('button');
                        btn.textContent = '▶ Watch via Proxy (Transcoded for PS4)';
                        btn.style.cssText = 'background:#f0a500;color:#000;border:none;padding:12px 24px;font-size:16px;font-weight:600;cursor:pointer;border-radius:6px;';
                        btn.onclick = function() {
                            // Try to find the best video URL
                            var videoUrl = '';
                            for (var i = 0; i < videoButtons.length; i++) {
                                var item = videoButtons[i];
                                if (item.src && item.src.startsWith('http') && !item.src.includes('doubleclick')) {
                                    videoUrl = item.src;
                                    break;
                                }
                            }
                            if (!videoUrl && videoButtons.length > 0) {
                                videoUrl = videoButtons[0].src;
                            }
                            if (videoUrl) {
                                window.location.href = '/watch?url=' + encodeURIComponent(videoUrl);
                            } else {
                                alert('Could not find video URL. Try opening the player directly.');
                            }
                        };
                        
                        playerBar.appendChild(btn);
                        document.body.appendChild(playerBar);
                        document.body.style.paddingBottom = '80px';
                    }
                });
            '''
            if soup.head:
                soup.head.append(script)
            
            header = BeautifulSoup(f'''<div class="header"><a href="/">Home</a><a href="/browse?url={quote(url)}">Refresh</a><form method="get" action="/browse" style="display:inline"><input type="text" name="url" value="{url}"><button type="submit">Go</button></form></div>''', 'html.parser')
            if soup.body:
                soup.body.insert(0, header)
            
            return str(soup)
        else:
            return Response(content, status=resp.status_code, headers={'Content-Type': content_type})
            
    except Exception as e:
        return f'<html><body style="background:#0a0a;color:#fff;padding:20px"><h2>Error: {str(e)}</h2><a href="/">Back</a></body></html>'

@app.route('/watch')
def watch():
    """
    Video streaming with real-time transcoding for PS4
    GET /watch?url=<video_url>
    Returns HLS stream URL
    """
    video_url = request.args.get('url', '')
    if not video_url:
        return redirect('/')
    
    video_url = unquote(video_url)
    stream_id = str(uuid.uuid4())[:8]
    segment_dir = f"{STREAM_DIR}/{stream_id}"
    os.makedirs(segment_dir, exist_ok=True)
    playlist_path = f"{segment_dir}/playlist.m3u8"
    
    # FFmpeg command for PS4 compatible HLS
    cmd = [
        'ffmpeg',
        '-re',
        '-i', video_url,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-profile:v', 'main',
        '-level', '3.1',
        '-pix_fmt', 'yuv420p',
        '-b:v', '4000k',
        '-maxrate', '5000k',
        '-bufsize', '10000k',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '48000',
        '-ac', '2',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '6',
        '-hls_flags', 'delete_segments',
        '-hls_segment_filename', f'{segment_dir}/segment_%03d.ts',
        playlist_path
    ]
    
    try:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        
        STREAMS[stream_id] = {
            'process': proc,
            'segment_dir': segment_dir,
            'playlist': playlist_path,
            'started': time.time(),
            'url': video_url
        }
        
        # Give ffmpeg time to start
        time.sleep(2)
        
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            return f'<html><body style="background:#0a0a;color:#fff;padding:20px"><h2>Transcoding failed</h2><pre>{stderr[:1000]}</pre><a href="/">Back</a></body></html>'
        
        # Return HTML5 video player that plays HLS
        hls_url = f'/hls/{stream_id}/playlist.m3u8'
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Video Stream</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ background: #000; display: flex; align-items: center; justify-content: center; height: 100vh; }}
                video {{ width: 100%; height: 100%; }}
            </style>
        </head>
        <body>
            <video id="video" controls autoplay>
                <source src="{hls_url}" type="application/vnd.apple.mpegurl">
            </video>
            <script>
                document.getElementById('video').play();
            </script>
        </body>
        </html>
        '''
        
    except Exception as e:
        return f'<html><body style="background:#0a0a;color:#fff;padding:20px"><h2>Error: {str(e)}</h2><a href="/">Back</a></body></html>'

@app.route('/hls/<stream_id>/<path:filename>')
def hls_files(stream_id, filename):
    """Serve HLS segments"""
    if stream_id not in STREAMS:
        return 'Stream not found', 404
    
    segment_dir = STREAMS[stream_id]['segment_dir']
    file_path = os.path.join(segment_dir, filename)
    
    if not os.path.exists(file_path):
        return 'File not found', 404
    
    if filename.endswith('.m3u8'):
        return Response(
            open(file_path).read(),
            mimetype='application/vnd.apple.mpegurl',
            headers={'Cache-Control': 'no-cache'}
        )
    else:
        return send_file(file_path, mimetype='video/mp2t')

@app.route('/stream/status/<stream_id>')
def stream_status(stream_id):
    """Check stream status"""
    if stream_id not in STREAMS:
        return {'error': 'Stream not found'}, 404
    
    info = STREAMS[stream_id]
    proc = info.get('process')
    
    return {
        'stream_id': stream_id,
        'running': proc is not None and proc.poll() is None,
        'uptime': time.time() - info.get('started', 0)
    }

@app.route('/stream/stop/<stream_id>')
def stream_stop(stream_id):
    """Stop a stream"""
    if stream_id in STREAMS:
        proc = STREAMS[stream_id].get('process')
        if proc:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except:
                pass
        del STREAMS[stream_id]
    return {'status': 'stopped'}

@app.route('/argentum_browser.html')
def argentum_browser_file():
    """Serve the full Argentum Browser UI"""
    browser_file = '/home/agx/.proxy/argentum_browser.html'
    if os.path.exists(browser_file):
        with open(browser_file, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html'}
    return 'Browser file not found', 404

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files for PS4 tools"""
    static_file = f'/home/agx/.proxy/static/{filename}'
    if os.path.exists(static_file):
        return send_file(static_file)
    return 'File not found', 404

@app.route('/download/pkg_tools')
def download_pkg_tools():
    """Download PS4 PKG Tools package"""
    tar_file = '/home/agx/.proxy/static/argentum_ps4_pkg_tools.tar.gz'
    if os.path.exists(tar_file):
        return send_file(tar_file, as_attachment=True, download_name='argentum_ps4_pkg_tools.tar.gz')
    return 'File not found', 404

@app.route('/download/instructions')
def download_instructions():
    """Download PKG build instructions"""
    md_file = '/home/agx/.proxy/static/ps4_pkg_instructions.md'
    if os.path.exists(md_file):
        return send_file(md_file, as_attachment=True, download_name='ps4_pkg_instructions.md')
    return 'File not found', 404

@app.route('/version.json')
def version_info():
    """App version info for auto-update"""
    version_file = '/home/agx/.proxy/VERSION.json'
    if os.path.exists(version_file):
        return send_file(version_file)
    return '{"version": "unknown"}'

@app.route('/browser')
def browser_ui():
    """Full browser interface for PS4 (inline version)"""
    home = request.args.get('home', 'https://www.google.com')
    
    html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Argentum Browser</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; background: #0a0a0a; color: #fff; font-family: Arial, sans-serif; overflow: hidden; }
        
        .header { background: #1a1a1a; padding: 12px; border-bottom: 2px solid #333; display: flex; gap: 8px; align-items: center; }
        .nav-btn { background: #2a2a2a; border: 1px solid #444; color: #fff; width: 44px; height: 44px; font-size: 18px; cursor: pointer; border-radius: 6px; }
        .nav-btn:hover { background: #3a3a3a; }
        .url-bar { flex: 1; background: #2a2a2a; border: 1px solid #444; color: #fff; padding: 12px 16px; font-size: 16px; border-radius: 6px; outline: none; }
        .url-bar:focus { border-color: #f0a500; }
        .go-btn { background: #f0a500; border: none; color: #000; padding: 12px 20px; font-size: 16px; font-weight: 600; cursor: pointer; border-radius: 6px; }
        
        .content { height: calc(100% - 68px); display: flex; flex-direction: column; }
        iframe { flex: 1; border: none; background: #fff; }
        
        .video-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #000; z-index: 9999; display: none; flex-direction: column; }
        .video-overlay.active { display: flex; }
        .video-header { background: #1a1a1a; padding: 12px; display: flex; justify-content: space-between; align-items: center; }
        .video-title { color: #f0a500; font-size: 16px; max-width: 70%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .close-btn { background: #d32f2f; border: none; color: #fff; width: 44px; height: 44px; font-size: 24px; cursor: pointer; border-radius: 6px; }
        .video-container { flex: 1; display: flex; align-items: center; justify-content: center; background: #000; }
        .video-container video { max-width: 100%; max-height: 100%; }
        .video-controls { background: #1a1a1a; padding: 12px; display: flex; gap: 10px; align-items: center; }
        .ctrl-btn { background: #333; border: 1px solid #555; color: #fff; padding: 10px 16px; font-size: 14px; cursor: pointer; border-radius: 6px; }
        .ctrl-btn:hover { background: #444; }
        .ctrl-btn.active { background: #f0a500; color: #000; }
        .progress-bar { flex: 1; height: 8px; background: #333; border-radius: 4px; cursor: pointer; }
        .progress-fill { height: 100%; background: #f0a500; border-radius: 4px; width: 0%; transition: width 0.1s; }
        
        .transcode-status { position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: rgba(26,26,26,0.95); border: 2px solid #f0a500; padding: 20px 40px; border-radius: 12px; text-align: center; z-index: 10000; display: none; }
        .transcode-status.active { display: block; }
        .transcode-status h3 { color: #f0a500; margin-bottom: 10px; }
        .spinner { width: 40px; height: 40px; border: 4px solid #333; border-top-color: #f0a500; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 15px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .loading { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0a0a0a; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 99999; }
        .loading.hidden { display: none; }
        .loading h1 { color: #f0a500; font-size: 32px; margin-bottom: 30px; }
        .loading .spinner { width: 60px; height: 60px; border-width: 6px; }
        
        .controller-hints { position: fixed; bottom: 10px; left: 10px; background: rgba(0,0,0,0.8); padding: 10px 15px; border-radius: 8px; font-size: 12px; color: #888; z-index: 100; }
        .controller-hints span { color: #f0a500; }
    </style>
</head>
<body>
    <div class="loading" id="loading">
        <h1>Argentum Browser</h1>
        <div class="spinner"></div>
        <p>Loading...</p>
    </div>

    <div class="header">
        <button class="nav-btn" onclick="goBack()" title="Back">&#8592;</button>
        <button class="nav-btn" onclick="goForward()" title="Forward">&#8594;</button>
        <button class="nav-btn" onclick="goHome()" title="Home">&#8962;</button>
        <input type="text" class="url-bar" id="urlBar" placeholder="Enter URL or search..." value="''' + home + '''">
        <button class="go-btn" onclick="navigate()">Go</button>
    </div>
    
    <div class="content">
        <iframe id="browserFrame" src="/browse?url=''' + quote(home) + '''"></iframe>
    </div>
    
    <div class="video-overlay" id="videoOverlay">
        <div class="video-header">
            <span class="video-title" id="videoTitle">Video</span>
            <button class="close-btn" onclick="closeVideo()">&#215;</button>
        </div>
        <div class="video-container">
            <video id="videoPlayer" controls autoplay>
                <source id="videoSource" type="application/vnd.apple.mpegurl">
            </video>
        </div>
        <div class="video-controls">
            <button class="ctrl-btn" onclick="togglePlay()">&#9654;</button>
            <div class="progress-bar" id="progressBar">
                <div class="progress-fill" id="progressFill"></div>
            </div>
            <button class="ctrl-btn" onclick="toggleFullscreen()">&#9974;</button>
        </div>
    </div>
    
    <div class="transcode-status" id="transcodeStatus">
        <div class="spinner"></div>
        <h3>Transcoding for PS4...</h3>
        <p id="transcodeInfo">Preparing video</p>
    </div>
    
    <div class="controller-hints">
        <span>PS Button</span> Menu | <span>L1/R1</span> Back/Forward | <span>Share</span> Reload
    </div>

    <script>
        var currentUrl = "";
        var history = [];
        var historyIndex = -1;
        var currentStreamId = null;
        
        window.onload = function() {
            currentUrl = "''' + home + '''";
            document.getElementById("urlBar").value = currentUrl;
            addToHistory(currentUrl);
            setTimeout(() => { document.getElementById("loading").classList.add("hidden"); }, 1500);
            setInterval(detectVideos, 5000);
        };
        
        function navigate() {
            var url = document.getElementById("urlBar").value.trim();
            if (!url) return;
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                if (url.includes(".") && !url.includes(" ")) { url = "https://" + url; }
                else { url = "https://www.google.com/search?q=" + encodeURIComponent(url); }
            }
            loadURL(url);
        }
        
        function loadURL(url) {
            document.getElementById("loading").style.display = "flex";
            document.getElementById("loading").classList.remove("hidden");
            document.getElementById("browserFrame").src = "/browse?url=" + encodeURIComponent(url);
            currentUrl = url;
            document.getElementById("urlBar").value = url;
            addToHistory(url);
            setTimeout(() => { document.getElementById("loading").classList.add("hidden"); }, 2000);
        }
        
        function addToHistory(url) {
            if (historyIndex < history.length - 1) { history = history.slice(0, historyIndex + 1); }
            history.push(url);
            historyIndex = history.length - 1;
        }
        
        function goBack() { if (historyIndex > 0) { historyIndex--; loadURL(history[historyIndex]); } }
        function goForward() { if (historyIndex < history.length - 1) { historyIndex++; loadURL(history[historyIndex]); } }
        function goHome() { loadURL("''' + home + '''"); }
        
        function detectVideos() {
            try {
                var frame = document.getElementById("browserFrame");
                var frameDoc = frame.contentDocument || frame.contentWindow.document;
                var videos = frameDoc.querySelectorAll("video");
                videos.forEach(function(video) {
                    video.style.cursor = "pointer";
                    video.onclick = function() { playVideo(this.src || this.currentSrc); };
                });
            } catch(e) {}
        }
        
        function playVideo(videoUrl) {
            if (!videoUrl) return;
            showTranscodeStatus("Starting transcoding...");
            fetch("/watch?url=" + encodeURIComponent(videoUrl))
                .then(r => r.text())
                .then(html => {
                    document.getElementById("videoTitle").textContent = videoUrl.split("/").pop();
                    var parser = new DOMParser();
                    var doc = parser.parseFromString(html, "text/html");
                    var source = doc.querySelector("source");
                    if (source) {
                        document.getElementById("videoSource").src = source.src;
                        document.getElementById("videoPlayer").load();
                        document.getElementById("videoOverlay").classList.add("active");
                    }
                    hideTranscodeStatus();
                })
                .catch(err => { hideTranscodeStatus(); alert("Error: " + err); });
        }
        
        function closeVideo() {
            var player = document.getElementById("videoPlayer");
            player.pause();
            document.getElementById("videoOverlay").classList.remove("active");
        }
        
        function togglePlay() {
            var player = document.getElementById("videoPlayer");
            if (player.paused) { player.play(); } else { player.pause(); }
        }
        
        function toggleFullscreen() {
            var player = document.getElementById("videoPlayer");
            if (player.requestFullscreen) { player.requestFullscreen(); }
        }
        
        function showTranscodeStatus(info) {
            document.getElementById("transcodeInfo").textContent = info;
            document.getElementById("transcodeStatus").classList.add("active");
        }
        
        function hideTranscodeStatus() {
            document.getElementById("transcodeStatus").classList.remove("active");
        }
        
        document.getElementById("urlBar").addEventListener("keypress", function(e) { if (e.key === "Enter") navigate(); });
        document.addEventListener("keydown", function(e) { if (e.key === "Share") location.reload(); });
    </script>
</body>
</html>'''
    return html

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8765, debug=False)
