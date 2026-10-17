#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f config.env ]]; then
  cp .env.example config.env
  echo "Fill in config.env with your Tuya credentials and dashboard password, then run again."
  exit 1
fi

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pythonanywhere

# Validate configuration before creating the hosted website.
.venv/bin/python - <<'PY'
from dotenv import load_dotenv
from socketstat.config import Settings
load_dotenv('config.env')
Settings.from_env()
PY

domain="${1:-$(id -un).eu.pythonanywhere.com}"
printf -v command '/bin/bash "%s"' "$PWD/start.sh"
.venv/bin/pa website create --domain "$domain" --command "$command"
echo "Open https://$domain"
echo "For future code/config changes: $PWD/.venv/bin/pa website reload --domain $domain"
