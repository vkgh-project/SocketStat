#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# start.sh changes to /home/Vacula before starting .venv/bin/python.
APP="${SOCKETSTAT_APP_DIR:-/home/Vacula}"
SOURCE="${SOCKETSTAT_SOURCE_DIR:-$HOME/SocketStat-source}"
BACKUP_ROOT="${SOCKETSTAT_BACKUP_DIR:-$HOME/socketstat-backups}"
DOMAIN=vacula.eu.pythonanywhere.com
BACKUP='ще не створено'
STEP='перевірка шляхів та команд'
trap 'status=$?; printf "\nПОМИЛКА: етап «%s», рядок %s, код %s.\nРезервна копія: %s\n" "$STEP" "$LINENO" "$status" "$BACKUP" >&2; exit "$status"' ERR
fail() { printf 'ПОМИЛКА: %s\n' "$*" >&2; exit 1; }

[[ -d "$APP" ]] || fail "Не знайдено робочу папку: $APP"
cd "$APP"
APP=$(pwd -P)
[[ -f .env ]] || fail "Не знайдено $APP/.env"
[[ -x .venv/bin/python ]] || fail "Не знайдено $APP/.venv/bin/python"
for tool in git rsync pa sha256sum tar mktemp; do
    command -v "$tool" >/dev/null || fail "Не знайдено команду: $tool"
done
printf 'Робоча папка: %s\nGitHub-копія: %s\n' "$APP" "$SOURCE"
STEP='резервне копіювання'

# Резервні копії лежать в окремій папці, яку rsync не змінює.
mkdir -p "$BACKUP_ROOT"
BACKUP=$(mktemp -d "$BACKUP_ROOT/update-$(date +%Y%m%d-%H%M%S)-XXXXXX")
printf 'Резервна копія: %s\n' "$BACKUP"
cp -p .env "$BACKUP/.env"
sha256sum .env > "$BACKUP/env.sha256"
pa website get --domain "$DOMAIN" > "$BACKUP/website.txt"

# Узгоджена копія активної SQLite-бази, включно з даними з WAL.
# Конфігурація читається поточним кодом, до його оновлення.
.venv/bin/python - "$BACKUP" <<'PY'
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv
from socketstat.config import Settings

root = Path.cwd().resolve()
load_dotenv(root / '.env')
db = Settings.from_env().db_path.resolve()
backup = Path(sys.argv[1])
code = (root / 'socketstat').resolve()
targets = [(root / name).resolve() for name in
           ('requirements.txt', 'pythonanywhere_start.py')]
if db == code or code in db.parents or db in targets:
    raise SystemExit('STOP: DB_PATH перетинається з файлами коду. Оновлення скасовано.')
if not db.is_file():
    raise SystemExit(f'STOP: чинну базу не знайдено: {db}')
with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(backup / 'socketstat.db') as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise SystemExit('STOP: резервна копія БД не пройшла перевірку.')
(backup / 'db-path.txt').write_text(str(db) + '\n')
print(f'База: {db}\nРезервна копія: {backup}')
PY

# Оновлюємо тільки окрему GitHub-копію; локальні зміни не скидаємо.
STEP='отримання коду з GitHub'
if [[ ! -e "$SOURCE" ]]; then
    git clone --branch main --single-branch \
      https://github.com/vkgh-project/SocketStat.git "$SOURCE"
fi
[[ "$(cd "$SOURCE" && pwd -P)" != "$APP" ]] || fail 'GitHub-копія має бути окремою від робочої папки.'
test "$(git -C "$SOURCE" remote get-url origin)" = \
  'https://github.com/vkgh-project/SocketStat.git'
test "$(git -C "$SOURCE" branch --show-current)" = main
test -z "$(git -C "$SOURCE" status --porcelain)"
git -C "$SOURCE" rev-parse HEAD > "$BACKUP/source-before.txt"
git -C "$SOURCE" pull --ff-only origin main
git -C "$SOURCE" rev-parse HEAD > "$BACKUP/source-after.txt"
for file in requirements.txt pythonanywhere_start.py socketstat/config.py; do
    [[ -f "$SOURCE/$file" ]] || fail "У GitHub-копії немає $file"
done
STEP='збереження попереднього коду'

# Зберігаємо попередній код для можливого відновлення.
# Старе розгортання через start.sh може не мати нового launcher-файлу.
CODE_FILES=(socketstat)
for file in requirements.txt pythonanywhere_start.py start.sh; do
    if [[ -f "$file" ]]; then CODE_FILES+=("$file"); fi
done
tar -czf "$BACKUP/code.tar.gz" "${CODE_FILES[@]}"
.venv/bin/python -m pip freeze > "$BACKUP/requirements-before.txt"

STEP='перенесення коду'
# Переносимо лише код. --delete не використовуємо.
rsync -a --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='.env' --exclude='.env.*' --exclude='config.env' \
  --exclude='data/' --exclude='*.db' --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  "$SOURCE/socketstat/" "$APP/socketstat/"
rsync -a "$SOURCE/requirements.txt" "$SOURCE/pythonanywhere_start.py" "$APP/"

STEP='встановлення залежностей'
.venv/bin/python -m pip install -r requirements.txt
STEP='перевірка конфігурації'
.venv/bin/python pythonanywhere_start.py --check
sha256sum --check "$BACKUP/env.sha256"
STEP='перезапуск сайту'
pa website reload --domain "$DOMAIN"
printf 'Оновлення завершено. Резервна копія: %s\n' "$BACKUP"
