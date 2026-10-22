# SocketStat на PythonAnywhere

Застосунок використовує FastAPI та фонове опитування Tuya раз на хвилину.
Потрібен **ASGI website**: стандартний WSGI-файл на вкладці Web для цього запуску не підходить.
Підтримка ASGI на PythonAnywhere наразі має статус beta; доступність функції й тарифні умови перевірте у своєму акаунті.
Для реального моніторингу використовуйте тариф із необмеженим вихідним доступом до Tuya.
На безкоштовному тарифі зовнішні адреси мають бути в allowlist; саме налаштування проксі не знімає цього обмеження.

## 1. Завантаження

У Files завантажте `socketstat-pythonanywhere.zip` у домашню папку.
У Bash console виконайте:

```bash
cd ~
unzip socketstat-pythonanywhere.zip
cd ~/SocketStat
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [ ! -e .env ]; then cp .env.example .env; fi
chmod 600 .env
```

Потрібен Python 3.10 або новіший. Якщо `python3.12` відсутній, оберіть доступну версію в налаштуваннях system image або використайте інший сумісний інтерпретатор.
Windows/macOS-середовища `.venv` переносити не потрібно.

## 2. Налаштування

Відредагуйте `/home/YOURUSERNAME/SocketStat/.env` через Files:

- `TUYA_CLIENT_ID`, `TUYA_CLIENT_SECRET` — ключі свого Tuya-проєкту.
- `TUYA_ENDPOINT` — датацентр проєкту (типово `https://openapi.tuyaeu.com`).
- `SOCKET_1_ID`, `SOCKET_2_ID` — різні Device ID розеток; за потреби змініть назви.
- `DASHBOARD_USER` і `DASHBOARD_PASSWORD` — вхід до панелі; пароль від 12 символів.
- `DB_PATH=./data/socketstat.db` — історія в папці проєкту. Файл створиться автоматично.
- `DEMO_MODE=false` — реальні спостереження. Для перевірки без Tuya можна тимчасово задати `true`; використайте окремий `DB_PATH=./data/demo.db`.

Не публікуйте `.env`. Значення з локального комп’ютера не переносяться автоматично.
Файл запуску завжди використовує папку проєкту як робочу, тому `.env` і відносний `DB_PATH` не залежать від робочої папки сервера.
Уже задані змінні середовища мають пріоритет над `.env`.

Перевірте конфігурацію без запитів до Tuya:

```bash
cd ~/SocketStat
.venv/bin/python pythonanywhere_start.py --check
```

## 3. Створення ASGI website

На сторінці Account → API token створіть API token. У новій Bash console встановіть офіційний CLI:

```bash
pip install --upgrade pythonanywhere
```

Створіть сайт, замінивши **обидва** `YOURUSERNAME` своїм логіном:

```bash
pa website create --domain YOURUSERNAME.pythonanywhere.com --command '/home/YOURUSERNAME/SocketStat/.venv/bin/python /home/YOURUSERNAME/SocketStat/pythonanywhere_start.py'
```

Для акаунта на EU-системі домен має вигляд `YOURUSERNAME.eu.pythonanywhere.com`.
PythonAnywhere передає `DOMAIN_SOCKET` процесу; файл запуску підключає до нього Uvicorn.
Якщо домен уже зайнятий іншим сайтом, спочатку перегляньте його налаштування; не видаляйте чинний сайт без резервної копії й плану перенесення.
ASGI-сайт може не відображатися у звичайному розділі Web. Перевірка:

```bash
pa website get --domain YOURUSERNAME.pythonanywhere.com
```

Відкрийте `https://YOURUSERNAME.pythonanywhere.com` і введіть логін та пароль із `.env`.
`https://YOURUSERNAME.pythonanywhere.com/healthz` має повертати `{"status":"ok"}`.
Це перевіряє БД та роботу циклу збору, але не доступ до Tuya: після хвилини перевірте час останнього опитування та стан обох розеток у панелі.
Якщо стан лишається невідомим, перевірте ключі, права API Tuya, датацентр та мережевий доступ тарифу.

## 4. Безперервний збір і оновлення

Запускайте **один** ASGI-процес. Збирач працює всередині нього; окрему Tasks/Always-on task для цього варіанта не створюйте.
Не додавайте `--reload` або додаткові workers. Під час зупинки чи перезапуску сервера опитування немає; пропуски залишаються «немає даних».
Збір залежить від доступності вебпроцесу на обраному тарифі. Після розгортання перевірте накопичення історії також без відкритої панелі.

### Оновлення з GitHub (якщо папка містить `.git`)

У Bash console виконайте, замінивши домен своїм:

```bash
cd ~/SocketStat &&
git pull --ff-only origin main &&
.venv/bin/python -m pip install -r requirements.txt &&
.venv/bin/python pythonanywhere_start.py --check &&
pa website reload --domain YOURUSERNAME.pythonanywhere.com
```

`git pull --ff-only` оновлює код без примусового скидання локальних змін. У цьому репозиторії `.env` та `data/` виключені через `.gitignore` і не відстежуються Git, тому наведені команди їх не перезаписують. `.env.example` — лише шаблон, застосунок не копіює його поверх `.env`. Налаштування домену та команди ASGI-сайту також не змінюються: виконується лише reload. Не запускайте `cp .env.example .env`, `git reset --hard` або `git clean` для звичайного оновлення.

### Оновлення після встановлення з ZIP (без `.git`)

Завантажте оновлений `output/socketstat-pythonanywhere.zip` із GitHub. Цей пакет містить лише код, документацію та `.env.example`: `.env`, `data/` і `.venv/` у нього не входять. Розпакування оновить код у `~/SocketStat`, зберігши ці локальні файли:

```bash
cd ~ &&
curl -fL https://raw.githubusercontent.com/vkgh-project/SocketStat/main/output/socketstat-pythonanywhere.zip -o socketstat-pythonanywhere.zip &&
unzip -o socketstat-pythonanywhere.zip &&
cd ~/SocketStat &&
.venv/bin/python -m pip install -r requirements.txt &&
.venv/bin/python pythonanywhere_start.py --check &&
pa website reload --domain YOURUSERNAME.pythonanywhere.com
```

Якщо тариф блокує завантаження з GitHub, завантажте цей ZIP на комп’ютер і передайте в домашню папку PythonAnywhere через Files, потім виконайте команди вище без рядка `curl`.

Для EU-акаунта використовуйте домен `YOURUSERNAME.eu.pythonanywhere.com`. Ланцюжок `&&` зупинить виконання при помилці: reload відбудеться лише після успішного оновлення та перевірки конфігурації. Перевірка `--check` не запускає збирач і не очищає базу.

Після зміни `.env` теж потрібен reload. Перезавантажте панель через Ctrl+F5.
Оновлення тем і кольорів розеток не потребує нових змінних `.env`, міграції БД чи зміни команди запуску. Після reload перевірте перемикач «Тема» у верхній частині сторінки: світла, темна та класична. Вибір зберігається в браузері, а не в серверній конфігурації. Кольори розеток мають бути узгоджені на вкладках «Розетки», «Тижневий розклад» та «Звіт недоступності».
Шляхи до error/server/access logs показує `pa website get --domain ...`.
Історія зберігається 14 діб. Для перенесення чинної історії зробіть узгоджену резервну копію через SQLite backup API; не копіюйте лише основний файл активної WAL-бази.

## Джерела та повторне пакування

- [Офіційне розгортання ASGI](https://help.pythonanywhere.com/pages/ASGICommandLine)
- [Мережеві обмеження](https://help.pythonanywhere.com/pages/403ForbiddenError)

Для створення нового архіву на своєму комп’ютері: `python build_pythonanywhere.py`.
Пакувальник бере лише явно дозволені файли; `.env`, база, логи та віртуальні середовища не включаються.
