#!/bin/bash
# Start Argentum Browser Proxy services

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/tmp/argentum-proxy-logs"

mkdir -p "$LOG_DIR"

echo "Starting Argentum Browser Proxy..."
echo "  Proxy:  http://localhost:8765/"
echo "  Browser UI: http://localhost:8765/browser"
echo "  Stream proxy: http://localhost:8766/"
echo ""

# Start proxy (if not already running)
if ! lsof -i :8765 &>/dev/null; then
    cd "$PROJECT_DIR"
    nohup python3 proxy.py > "$LOG_DIR/proxy.log" 2>&1 &
    echo "proxy.py started (PID: $!)"
else
    echo "proxy.py already running on :8765"
fi

# Start stream proxy (if not already running)
if ! lsof -i :8766 &>/dev/null; then
    cd "$PROJECT_DIR"
    nohup python3 stream_proxy.py > "$LOG_DIR/stream.log" 2>&1 &
    echo "stream_proxy.py started (PID: $!)"
else
    echo "stream_proxy.py already running on :8766"
fi

echo ""
echo "Logs: $LOG_DIR/"
echo "  tail -f $LOG_DIR/proxy.log"
echo "  tail -f $LOG_DIR/stream.log"
