#!/bin/bash
# Cloudflare bypass helper for Argentum Proxy
# Usage: ./cloudflare.sh <url>
# Returns JSON with cookies and user agent

set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
    printf '%s\n' 'Usage: cloudflare.sh <url>' >&2
    exit 64
fi

SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"
[[ -f "$SCRIPT_DIR/cloudflare.js" && -r "$SCRIPT_DIR/cloudflare.js" ]]
cd -- "$SCRIPT_DIR"
exec node "$SCRIPT_DIR/cloudflare.js" "$1"
