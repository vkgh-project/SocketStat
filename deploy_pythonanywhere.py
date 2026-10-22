"""Prepare isolated releases and switch the existing PythonAnywhere start.sh.

Only the CLI install/cleanup commands can remove legacy home-directory files.
The website can request an update of the fixed GitHub main branch only.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPOSITORY = 'https://github.com/vkgh-project/SocketStat.git'
STEPS = {
    'preparing': 'Завантажуємо нову версію',
    'dependencies': 'Готуємо середовище нової версії',
    'validating': 'Перевіряємо нову версію',
    'backup': 'Створюємо резервну копію',
    'restarting': 'Перезапускаємо сайт',
}


class DeploymentError(RuntimeError):
    pass


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.chmod(0o600)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {} if default is None else default


def switch_link(root, name, target):
    link = root / (name + '.next')
    link.unlink(missing_ok=True)
    link.symlink_to(target, target_is_directory=True)
    os.replace(link, root / name)


def run(command, *, cwd=None, env=None, log=None, timeout=900, failure_message=None):
    result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=timeout)
    if log:
        with log.open('a', encoding='utf-8') as out:
            out.write(result.stdout)
    if result.returncode:
        raise DeploymentError(failure_message or 'Команда завершилася помилкою. Подробиці — у приватному update.log.')
    return result.stdout.strip()


def runtime(python, home, env_file):
    # Validate using the selected release, without starting collectors or a DB.
    probe = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
os.chdir(sys.argv[2])
from pathlib import Path
from dotenv import load_dotenv
from socketstat.config import Settings
load_dotenv(os.environ['SOCKETSTAT_ENV_FILE'])
s = Settings.from_env()
print(json.dumps({'db': str(s.db_path.absolute()),
                  'token': os.getenv('PYTHONANYWHERE_API_TOKEN') or os.getenv('API_TOKEN', '')}))
'''
    env = dict(os.environ, SOCKETSTAT_ENV_FILE=str(env_file))
    # stdin/-c would otherwise import the obsolete package in the home directory.
    source = Path(python).parent.parent.parent
    result = run([python, '-c', probe, source, home], cwd=source, env=env,
                 failure_message=('Не вдалося перевірити ' + str(env_file) +
                                  '. Перевірте DASHBOARD_USER, DASHBOARD_PASSWORD (від 12 символів), '
                                  'ключі Tuya, ID розеток та доступність Python.'))
    return json.loads(result)


def website_api(config, token, *, reload=False):
    if not token:
        raise DeploymentError('Немає API token PythonAnywhere. Створіть його в Account → API token.')
    endpoint = ('https://eu.pythonanywhere.com/api/v1/user/' +
                config['username'] + '/websites/' + config['domain'] + '/')
    if reload:
        endpoint += 'reload/'
    request = urllib.request.Request(endpoint, data=b'' if reload else None,
                                     headers={'Authorization': 'Token ' + token})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        raise DeploymentError('PythonAnywhere API недоступний або відхилив запит.') from error
    return {} if reload else json.loads(body)


def snapshot(root, env_file, db_path, home):
    backup = root / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex())
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(env_file, backup / '.env')
    (backup / '.env').chmod(0o600)
    db = Path(db_path).resolve()
    if not db.is_file():
        raise DeploymentError('Чинну базу DB_PATH не знайдено. Порожню БД не створено.')
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(backup / 'socketstat.db') as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise DeploymentError('Резервна копія БД не пройшла перевірку.')
    (backup / 'db-path.txt').write_text(str(db) + '\n', encoding='utf-8')
    if (home / 'start.sh').is_file():
        shutil.copy2(home / 'start.sh', backup / 'start.sh')
    # Bound routine data copies; retain the one-time legacy archive separately.
    snapshots = sorted(path for path in (root / 'backups').iterdir()
                       if path.is_dir() and re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', path.name))
    for expired in snapshots[:-5]:
        shutil.rmtree(expired)
    return backup


def startup_script(root, home, env_file):
    return '\n'.join([
        '#!/bin/bash', 'set -e',
        'export SOCKETSTAT_DEPLOY_ROOT=' + shlex.quote(str(root)),
        'export SOCKETSTAT_WORK_DIR=' + shlex.quote(str(home)),
        'export SOCKETSTAT_ENV_FILE=' + shlex.quote(str(env_file)),
        'RELEASE=$(cd ' + shlex.quote(str(root / 'current')) + ' && pwd -P)',
        'exec "$RELEASE/.venv/bin/python" "$RELEASE/pythonanywhere_start.py"', '',
    ])


def clean_plan(home, root, db_path, env_file):
    # Retain account dotfiles (.ssh/.local/.cache/etc), the launcher, managed
    # deployment, and both logical and real paths of the configuration/database.
    protected = {'start.sh'}
    for path in (root, env_file, env_file.resolve(), Path(db_path), Path(db_path).resolve()):
        try:
            relative = path.absolute().relative_to(home)
        except ValueError:
            continue
        if relative.parts:
            protected.add(relative.parts[0])
    protected.update({Path(db_path).name + suffix for suffix in ('-wal', '-shm')})
    return sorted((path for path in home.iterdir()
                   if path.name not in protected and
                   (not path.name.startswith('.') or path.name in {'.venv', '.git', '.pytest_cache'})),
                  key=lambda path: path.name)


def cleanup(home, root, db_path, env_file, *, apply=False):
    paths = clean_plan(home, root, db_path, env_file)
    print('Старі файли: ' + ', '.join(path.name for path in paths), flush=True)
    if not apply or not paths:
        return
    # Archive first; only remove the reviewed, snapshotted top-level entries.
    archive_path = root / 'backups' / ('legacy-' + time.strftime('%Y%m%d-%H%M%S') + '.tar.gz')
    with tarfile.open(archive_path, 'x:gz') as archive:
        for path in paths:
            archive.add(path, arcname=path.name, recursive=True)
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                while stream.read(1024 * 1024):
                    pass
    for path in paths:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    print('Старі файли прибрано. Архів: ' + str(archive_path), flush=True)


class Deployer:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = read_json(self.root / 'deployment.json')
        self.state = {}

    def record(self, phase, **values):
        self.state.update(phase=phase, message=STEPS.get(phase, ''), updated_at=time.time())
        self.state.update(values)
        atomic_json(self.root / 'state.json', self.state)
        print(self.state.get('message') or phase, flush=True)

    def prepare(self):
        self.record('preparing')
        root = self.root
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=root) as temp:
            checkout = Path(temp) / 'repo'
            run(['git', 'clone', '--depth', '1', '--branch', 'main', REPOSITORY, checkout], log=root / 'update.log')
            revision = run(['git', '-C', checkout, 'rev-parse', 'HEAD'])
            if not re.fullmatch('[a-f0-9]{40}', revision):
                raise DeploymentError('Некоректна версія GitHub.')
            self.state['target'] = revision
            current = read_json(root / 'current' / 'release.json').get('revision')
            if current == revision:
                self.record('success', message='Встановлена остання версія GitHub')
                return None
            release = root / 'releases' / (time.strftime('%Y%m%d-%H%M%S') + '-' + revision[:12] + '-' + os.urandom(3).hex())
            release.mkdir(parents=True)
            for name in ('requirements.txt', 'pythonanywhere_start.py', 'deploy_pythonanywhere.py'):
                shutil.copy2(checkout / name, release / name)
            shutil.copytree(checkout / 'socketstat', release / 'socketstat',
                            ignore=shutil.ignore_patterns('.env*', '*.db*', '__pycache__', '*.pyc'))
            atomic_json(release / 'release.json', {'revision': revision})
        self.record('dependencies')
        run([sys.executable, '-m', 'venv', release / '.venv'], log=root / 'update.log')
        python = release / '.venv/bin/python'
        run([python, '-m', 'pip', 'install', '-r', release / 'requirements.txt'], log=root / 'update.log')
        self.record('validating')
        run([python, '-m', 'compileall', '-q', release / 'socketstat'], log=root / 'update.log')
        return release

    def deploy(self, *, install=False, clean=False):
        root, config = self.root, self.config
        home, env_file = Path(config['home']), Path(config['env_file'])
        previous = (root / 'current').resolve() if (root / 'current').exists() else None
        switched = False
        try:
            # Fail BEFORE changing files if the existing configuration is invalid.
            self.record('validating')
            old_python = (previous / '.venv/bin/python') if previous else home / '.venv/bin/python'
            old = runtime(old_python, home, env_file)
            info = website_api(config, old['token'])
            expected_command = '/bin/bash ' + str(home / 'start.sh')
            if info.get('webapp', {}).get('command') != expected_command:
                raise DeploymentError('Команда сайту відрізняється від очікуваного /bin/bash start.sh.')
            env_hash = hashlib.sha256(env_file.read_bytes()).digest()
            release = self.prepare()
            if release is None:
                return
            new = runtime(release / '.venv/bin/python', home, env_file)
            if Path(new['db']).resolve() != Path(old['db']).resolve():
                raise DeploymentError('Нова версія змінила DB_PATH. Оновлення скасовано.')
            self.record('backup')
            backup = snapshot(root, env_file, old['db'], home)
            self.state['backup'] = backup.name
            if hashlib.sha256(env_file.read_bytes()).digest() != env_hash:
                raise DeploymentError('.env змінився під час підготовки. Повторіть оновлення.')
            if previous:
                switch_link(root, 'previous', previous)
            # The API always executes the existing /home/Vacula/start.sh path.
            # Replace only this launcher and the pointer to a prepared release.
            launcher = home / 'start.sh.new'
            launcher.write_text(startup_script(root, home, env_file), encoding='utf-8')
            launcher.chmod(0o700)
            switch_link(root, 'current', release)
            os.replace(launcher, home / 'start.sh')
            switched = True
            self.record('restarting')
            website_api(config, old['token'], reload=True)
            # A web-triggered worker may be terminated by the host on reload.
            # The new app marks success only after its lifespan has started.
            self.wait_for_health(self.state['target'])
            self.record('success', message='Оновлення завершено')
            switched = False  # Cleanup errors must never roll back a healthy release.
            if install and clean:
                cleanup(home, root, old['db'], env_file, apply=True)
        except Exception as error:
            if switched:
                if previous:
                    switch_link(root, 'current', previous)
                elif 'backup' in locals() and (backup / 'start.sh').exists():
                    shutil.copy2(backup / 'start.sh', home / 'start.sh')
                    (root / 'current').unlink(missing_ok=True)
                try:
                    website_api(config, old['token'], reload=True)
                except Exception:
                    pass
            self.record('error', message='Оновлення не завершено: ' + str(error))
            raise

    def wait_for_health(self, revision):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request('https://' + self.config['domain'] + '/healthz',
                                                 headers={'Cache-Control': 'no-cache'})
                with urllib.request.urlopen(request, timeout=10) as response:
                    if (response.headers.get('X-SocketStat-Revision') == revision and
                            json.loads(response.read()).get('status') == 'ok'):
                        return
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
            time.sleep(2)
        raise DeploymentError('Нова версія не підтвердила працездатність. Потрібна перевірка журналу сайту.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'update', 'rollback', 'cleanup'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--root', type=Path)
    parser.add_argument('--domain', default='vacula.eu.pythonanywhere.com')
    parser.add_argument('--clean', action='store_true', help='Archive and remove old home files after a healthy install')
    parser.add_argument('--apply', action='store_true', help='Apply the printed cleanup plan')
    parser.add_argument('--lock-fd', type=int)
    args = parser.parse_args(argv)
    os.umask(0o077)
    home = args.home.resolve()
    root = (args.root or home / '.socketstat').resolve()
    if root == home or home not in root.parents:
        parser.error('Deployment root must be a separate directory inside the home directory')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.fdopen(args.lock_fd, 'w') if args.lock_fd is not None else (root / 'update.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Оновлення вже виконується.')
    with lock:
        if args.action == 'install':
            if (root / 'current').exists():
                raise SystemExit('Встановлення вже налаштовано. Використовуйте update.')
            if not (home / '.env').is_file():
                raise SystemExit('Не знайдено ' + str(home / '.env'))
            atomic_json(root / 'deployment.json', {'home': str(home), 'env_file': str(home / '.env'),
                        'username': home.name, 'domain': args.domain})
        deployer = Deployer(root)
        if not deployer.config:
            raise SystemExit('Спочатку виконайте install.')
        try:
            if args.action in ('install', 'update'):
                deployer.deploy(install=args.action == 'install', clean=args.clean)
            elif args.action == 'cleanup':
                config = deployer.config
                home = Path(config['home'])
                current = (root / 'current').resolve()
                active = runtime(current / '.venv/bin/python', home, Path(config['env_file']))
                deployer.wait_for_health(read_json(current / 'release.json')['revision'])
                cleanup(home, root, active['db'], Path(config['env_file']), apply=args.apply)
            elif args.action == 'rollback':
                previous = (root / 'previous').resolve()
                if not (previous / 'release.json').is_file():
                    raise DeploymentError('Попередньої версії немає.')
                config = deployer.config
                active = runtime(previous / '.venv/bin/python', Path(config['home']), Path(config['env_file']))
                snapshot(root, Path(config['env_file']), active['db'], Path(config['home']))
                current = (root / 'current').resolve()
                switch_link(root, 'current', previous)
                switch_link(root, 'previous', current)
                deployer.state['target'] = read_json(previous / 'release.json')['revision']
                deployer.record('restarting')
                website_api(config, active['token'], reload=True)
                deployer.wait_for_health(deployer.state['target'])
                deployer.record('success', message='Відновлено попередню версію коду')
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1
        finally:
            # Keep current + previous only; no uncontrolled accumulation of venvs.
            protected = {(root / name).resolve() for name in ('current', 'previous') if (root / name).exists()}
            for release in (root / 'releases').glob('*'):
                if release.resolve() not in protected:
                    shutil.rmtree(release)
    return 0


if __name__ == '__main__':
    sys.exit(main())
