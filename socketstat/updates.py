"""Authenticated web interface to the isolated release worker."""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse


BUSY = {'preparing', 'dependencies', 'validating', 'backup', 'restarting'}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}


class Updates:
    def __init__(self, root=None):
        value = root or os.getenv('SOCKETSTAT_DEPLOY_ROOT')
        self.root = Path(value).resolve() if value else None
        self.csrf = secrets.token_urlsafe(32)
        self.revision = read_json(Path(__file__).resolve().parent.parent / 'release.json').get('revision', '')

    @property
    def enabled(self):
        return bool(self.root and (self.root / 'deployment.json').is_file())

    def started(self):
        if not self.enabled:
            return
        state = read_json(self.root / 'state.json')
        if (state.get('phase') == 'restarting' and self.revision and
                state.get('target') == self.revision):
            # Confirm only when this release actually passed the app lifespan.
            state.update(phase='success', message='Оновлення завершено', updated_at=time.time())
            temporary = self.root / 'startup-state.tmp'
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            temporary.chmod(0o600)
            os.replace(temporary, self.root / 'state.json')

    def status(self):
        state = read_json(self.root / 'state.json') if self.enabled else {}
        phase = state.get('phase', 'idle')
        # Interrupted pre-reload jobs release their OS lock. Never block updates
        # forever because a worker disappeared while downloading/installing.
        if (self.enabled and phase in BUSY and
                (phase != 'restarting' or time.time() - state.get('updated_at', 0) > 150)):
            import fcntl
            with (self.root / 'update.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    phase = 'error'
                    state['message'] = 'Попереднє оновлення перервалося. Можна повторити спробу.'
        return {'enabled': self.enabled, 'phase': phase,
                'message': state.get('message', 'Оновлень ще не запускали'),
                'revision': self.revision[:12], 'target': state.get('target', '')[:12],
                'backup': state.get('backup', ''), 'csrf': self.csrf}

    def start(self):
        if not self.enabled:
            raise HTTPException(503, 'Спочатку налаштуйте оновлення в консолі PythonAnywhere.')
        import fcntl
        lock = (self.root / 'update.lock').open('a')
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HTTPException(409, 'Оновлення вже виконується.')
            # Write a status while holding the lock; the child inherits the same
            # open-file lock, so two simultaneous POSTs cannot launch two jobs.
            path = self.root / 'state.json'
            temporary = self.root / 'request-state.tmp'
            temporary.write_text(json.dumps({'phase': 'preparing', 'message': 'Запускаємо оновлення',
                                             'updated_at': time.time()}, ensure_ascii=False), encoding='utf-8')
            temporary.chmod(0o600)
            os.replace(temporary, path)
            with (self.root / 'update.log').open('a') as log:
                (self.root / 'update.log').chmod(0o600)
                subprocess.Popen([
                    sys.executable, str(Path(__file__).resolve().parent.parent / 'deploy_pythonanywhere.py'),
                    'update', '--home', read_json(self.root / 'deployment.json')['home'],
                    '--root', str(self.root), '--lock-fd', str(lock.fileno()),
                ], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, pass_fds=(lock.fileno(),))
        finally:
            lock.close()
        return {'accepted': True}


def mount_updates(app, authenticate, *, local=False):
    updates = Updates()
    app.state.updates = updates

    @app.get('/updates', dependencies=[Depends(authenticate)])
    def page():
        return FileResponse(Path(__file__).parent / 'static' / 'updates.html')

    @app.get('/api/updates', dependencies=[Depends(authenticate)])
    def status():
        return updates.status()

    @app.post('/api/updates', status_code=202, dependencies=[Depends(authenticate)])
    def start(request: Request):
        if local:
            raise HTTPException(403, 'Оновлення доступне лише в захищеному серверному режимі.')
        if not secrets.compare_digest(request.headers.get('x-socketstat-token', ''), updates.csrf):
            raise HTTPException(403, 'Оновіть сторінку перед запуском оновлення.')
        origin = request.headers.get('origin')
        if origin and (urlsplit(origin).netloc != request.headers.get('host') or
                       urlsplit(origin).scheme != request.url.scheme):
            raise HTTPException(403, 'Запит має походити зі сторінки цього сайту.')
        return updates.start()

    return updates
