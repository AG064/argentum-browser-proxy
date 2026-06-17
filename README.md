# Argentum Browser Proxy

HTTP proxy with browser UI for PS4, with Cloudflare bypass and video transcoding.

## Components

| File | Port | Description |
|------|------|-------------|
| `proxy.py` | 8765 | Main HTTP proxy with Cloudflare bypass |
| `browser_app.py` | 8765 | Full-screen browser UI for PS4 |
| `stream_proxy.py` | 8766 | HLS/m3u8 stream transcoder |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start proxy + browser UI
./scripts/start.sh

# Or start individually
python3 proxy.py        # Proxy on :8765
python3 browser_app.py # Browser UI on :8765 (冲突 if proxy runs)
python3 stream_proxy.py # Stream proxy on :8766
```

## Access

- Browser UI: `http://YOUR_IP:8765/browser`
- Proxy: `http://YOUR_IP:8765/`
- Stream proxy: `http://YOUR_IP:8766/`

Default IP detected from `192.168.0.238` (see `VERSION.json`).

## PS4 Setup

1. Go to PS4 browser, navigate to `http://YOUR_IP:8765/browser`
2. Use the on-screen keyboard to enter URLs
3. Videos are automatically transcoded for PS4 compatibility

## PS4 Package Build

See `static/ps4_pkg_instructions.md` for creating a PS4 pkg file.

## Configuration

Copy `.env.example` to `.env` and adjust if needed.

## Project Structure

```
argentum-browser-proxy/
├── proxy.py              # Main proxy (Cloudflare bypass)
├── browser_app.py        # PS4 browser UI
├── stream_proxy.py       # Video stream transcoder
├── cloudflare.py         # Cloudflare bypass (Python)
├── cloudflare.sh         # Cloudflare bypass (Shell + Node)
├── cloudflare.js         # Cloudflare bypass (Node.js)
├── requirements.txt
├── scripts/
│   └── start.sh          # Start all services
└── static/
    ├── argentum.gp4      # GP4 project for PKG
    ├── ps4_pkg_instructions.md
    └── sce_sys.tar.gz   # PS4 system files
```
