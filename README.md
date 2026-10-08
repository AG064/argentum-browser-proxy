# Argentum Browser Proxy

HTTP proxy with browser UI for PS4, with Cloudflare bypass, video extraction, and transcoding.

## Current security boundaries

Proxy-owned pages encode supplied values for their HTML or JavaScript context. Rewritten forms use native GET or POST submission; POST fields and uploaded bytes remain in the body. Legacy GET requests containing a post payload are rejected. Local static/HLS file retrieval is constrained to its configured directory.

Outbound destinations are still unrestricted, and transcoding services still accept unauthenticated requests without global job limits. These are unresolved security findings. Restrict access to trusted operators while deciding whether to retain the service with isolated network/process workers or disable its unsafe features. URL syntax checks do not provide network isolation.

## Dependencies

Use Python 3.10 or newer; checks use Python 3.12. The requirements file declares the tested minimum Flask, Requests, Beautiful Soup and chardet releases with major-version bounds. It is not a complete transitive lockfile. FFmpeg, Playwright and Chromium are optional external dependencies for extraction/transcoding, and the Cloudflare helper is resolved from the configured host installation. Their installed versions and host permissions have not been verified by the focused HTTP/UI checks.

## Quick Start

```bash
cd /home/agx/AGX/argentum-browser-proxy
pip install -r requirements.txt
python3 proxy.py
```

Access: `http://YOUR_IP:8765/`

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Search interface |
| `GET /browser` | PS4 browser UI |
| `GET /browse?url=` | Proxy a URL through the proxy |
| `GET /extract?url=` | Extract video URL from page using Playwright |
| `GET /transcode?url=` | Transcode direct video URL to HLS |
| `GET /transcode?page_url=` | Extract + transcode in one step (Playwright) |
| `GET /hls/<id>/playlist.m3u8` | Serve HLS playlist |
| `GET /hls/stop/<id>` | Stop transcode |
| `GET /video-player?stream_id=` | Standalone video player page |

## PS4 Browser Setup

1. Go to PS4 browser, navigate to: `http://192.168.0.238:8765/browser`
2. Navigate to any supported site
3. Use `/transcode?page_url=` for automatic video extraction

## Supported Sites

| Site | Video Extraction | Transcode | Notes |
|------|-----------------|-----------|-------|
| filmix.my | ✅ Playwright | ✅ HLS/AAC | Best quality, auto-extract |
| atomics.ws | ✅ Direct | ✅ HLS | Works well, some audio codec issues |
| gidonline | ⚠️ YouTube embeds | ❌ | YouTube blocks PS4 |
| hdrezka | ❌ AJAX | ❌ | Dynamic JS loading |
| VK | ❌ Blocked | ❌ | Requires login |

## Transcoding

The transcode endpoint converts video to HLS with AAC audio for PS4 compatibility:

```
GET /transcode?page_url=https://filmix.my/play/9348
```

Returns:
```json
{
  "stream_id": "b5064ec5",
  "hls_url": "/hls/b5064ec5/playlist.m3u8",
  "status": "started"
}
```

Watch at: `http://YOUR_IP:8765/hls/b5064ec5/playlist.m3u8`

Or use the player: `http://YOUR_IP:8765/video-player?stream_id=b5064ec5`

Stop: `GET /hls/stop/b5064ec5`

## Configuration

Default IP: `192.168.0.238` (hardcoded in VERSION.json)

## Project Structure

```
argentum-browser-proxy/
├── proxy.py              # Main Flask app with all routes
├── browser_app.py        # Standalone browser UI
├── stream_proxy.py       # Stream proxy
├── cloudflare.py/js/sh  # Cloudflare bypass
├── requirements.txt
├── README.md
├── LICENSE (MIT)
├── VERSION.json
├── scripts/start.sh
└── static/              # PS4 pkg build files
```
