#!/usr/bin/env bash
# One-time setup, then use /updates. Existing setup also supports console updates.
set -Eeuo pipefail
umask 077
APP="${SOCKETSTAT_APP_DIR:-/home/Vacula}"
ROOT="$APP/.socketstat"
PYTHON="$APP/.venv/bin/python"
trap 'printf "Помилка встановлення, рядок %s. Перевірте повідомлення вище та .socketstat/update.log.\n" "$LINENO" >&2' ERR
if [[ -f "$ROOT/current/deploy_pythonanywhere.py" ]]; then
    exec "$ROOT/current/.venv/bin/python" "$ROOT/current/deploy_pythonanywhere.py" update --home "$APP" --root "$ROOT"
fi
[[ -x "$PYTHON" ]] || { printf 'Не знайдено Python: %s\n' "$PYTHON" >&2; exit 1; }
TEMP=$(mktemp -d)
trap 'rm -rf "$TEMP"' EXIT
curl -fL https://raw.githubusercontent.com/vkgh-project/SocketStat/main/deploy_pythonanywhere.py -o "$TEMP/deploy_pythonanywhere.py"
"$PYTHON" "$TEMP/deploy_pythonanywhere.py" install --home "$APP" --root "$ROOT" "$@"
