#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
cd -- "$PROJECT_DIR"
test -f deploy/private/access-code || { echo 'Run deploy/bootstrap.py before starting.' >&2; exit 1; }
exec docker compose up -d --build
