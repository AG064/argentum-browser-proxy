"""Extract public media in a supervised browser process."""
import json
import sys
from urllib.parse import urlsplit, urljoin
from playwright.sync_api import sync_playwright
from web_security import validate_http_url
import isolation_runtime


def extract_video_url_filmix(page):
    """Extract video URL from Filmix page using Playwright"""
    try:
        # Wait for the video element to have a src
        page.wait_for_selector('video[src]', timeout=10000)
        video = page.query_selector('video')
        if video:
            src = video.get_attribute('src')
            if src and ('.mp4' in src or 'm3u8' in src):
                return src
    except Exception as e:
        print("Filmix extraction failed", file=sys.stderr)
    return None

def extract(url):
    url = validate_http_url(url)
    captured = []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(**isolation_runtime.browser_options())
        try:
            context = browser.new_context()
            page = context.new_page()
            def response_received(response):
                path = urlsplit(response.url).path.lower()
                content_type = response.headers.get('content-type','').split(';')[0]
                if 200 <= response.status < 300 and (path.endswith(('.mp4','.m3u8','.mpd')) or content_type in ('video/mp4','application/vnd.apple.mpegurl','application/x-mpegurl','application/dash+xml')):
                    if len(captured) < 16:
                        captured.append(response.url)
            page.on('response', response_received)
            page.goto(url, timeout=20000, wait_until='domcontentloaded')
            page.wait_for_timeout(3000)
            video_url = None
            if 'filmix' in urlsplit(url).hostname:
                video_url = extract_video_url_filmix(page)
            if not video_url:
                videos = page.query_selector_all('video[src],video source[src]')
                for video in videos[:8]:
                    source = video.get_attribute('src')
                    if source and not source.startswith('blob:'):
                        video_url = urljoin(page.url, source)
                        break
            if not video_url and captured:
                video_url = captured[0]
            if not video_url:
                return None
            video_url = validate_http_url(video_url)
            return dict(video_url=video_url, cookies=context.cookies([video_url]))
        finally:
            browser.close()


if __name__ == '__main__':
    isolation_runtime.require_isolation()
    result = extract(sys.argv[1])
    serialized = json.dumps(result)
    if len(serialized.encode()) > 65536:
        raise ValueError('Media metadata exceeds limit')
    print(serialized)
