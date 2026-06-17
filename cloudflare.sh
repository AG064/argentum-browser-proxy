#!/bin/bash
# Cloudflare bypass helper for Argentum Proxy
# Usage: ./cloudflare.sh <url>
# Returns JSON with cookies and user agent

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_DIR="/tmp/cf_temp"

cd "$NODE_DIR"
node cloudflare.js "$1" 2>/dev/null
