#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export DB_PATH="$PWD/data/socketstat.db"
exec .venv/bin/python -m uvicorn socketstat.app:app \
  --env-file "$PWD/config.env" \
  --uds "${DOMAIN_SOCKET:?Run this through PythonAnywhere ASGI hosting}" \
  --workers 1
