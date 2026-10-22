import json
import os
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import deploy_pythonanywhere as deploy
from socketstat.app import create_app
from socketstat.config import Device, Settings
from socketstat.updates import Updates


def layout(tmp_path):
    home = tmp_path / 'Vacula'
    home.mkdir()
    root = home / '.socketstat'
    root.mkdir()
    env = home / '.env'
    env.write_text('existing-secret-config\n')
    (home / 'start.sh').write_text('# old launcher\n')
    db = home / 'data/history.sqlite'
    db.parent.mkdir()
    connection = sqlite3.connect(db)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE history (state TEXT)')
    connection.execute("INSERT INTO history VALUES ('preserved')")
    connection.commit()
    config = {'home': str(home), 'env_file': str(env), 'username': 'Vacula',
              'domain': 'vacula.eu.pythonanywhere.com'}
    deploy.atomic_json(root / 'deployment.json', config)
    return home, root, db, connection


def fake_runtime(monkeypatch, db):
    monkeypatch.setattr(deploy, 'runtime', lambda *args: {'db': str(db), 'token': 'test-api-token'})


def test_install_prepares_before_switching_and_preserves_live_wal(tmp_path, monkeypatch):
    home, root, db, connection = layout(tmp_path)
    fake_runtime(monkeypatch, db)
    worker = deploy.Deployer(root)
    calls = []
    def api(config, token, reload=False):
        calls.append(reload)
        return {'webapp': {'command': '/bin/bash ' + str(home / 'start.sh')}}
    monkeypatch.setattr(deploy, 'website_api', api)
    def prepare():
        assert (home / 'start.sh').read_text() == '# old launcher\n'
        assert not (root / 'current').exists()
        # Simulate another observation arriving while dependencies install.
        connection.execute("INSERT INTO history VALUES ('during-build')")
        connection.commit()
        release = root / 'releases/new'
        release.mkdir(parents=True)
        worker.state['target'] = 'a' * 40
        deploy.atomic_json(release / 'release.json', {'revision': 'a' * 40})
        return release
    monkeypatch.setattr(worker, 'prepare', prepare)
    monkeypatch.setattr(worker, 'wait_for_health', lambda revision: None)
    worker.deploy(install=True)
    assert calls == [False, True]
    assert (home / '.env').read_text() == 'existing-secret-config\n'
    assert connection.execute('SELECT state FROM history').fetchall() == [('preserved',), ('during-build',)]
    backup = next((root / 'backups').iterdir())
    with sqlite3.connect(backup / 'socketstat.db') as copied:
        assert copied.execute('SELECT state FROM history').fetchall() == [('preserved',), ('during-build',)]
    assert str(home) in (home / 'start.sh').read_text()
    assert (backup / 'start.sh').read_text() == '# old launcher\n'
    assert deploy.read_json(root / 'state.json')['phase'] == 'success'
    connection.close()


def test_failed_build_never_switches_or_reloads(tmp_path, monkeypatch):
    home, root, db, connection = layout(tmp_path)
    fake_runtime(monkeypatch, db)
    calls = []
    def api(config, token, reload=False):
        calls.append(reload)
        return {'webapp': {'command': '/bin/bash ' + str(home / 'start.sh')}}
    monkeypatch.setattr(deploy, 'website_api', api)
    worker = deploy.Deployer(root)
    def fail():
        raise deploy.DeploymentError('pip failed')
    monkeypatch.setattr(worker, 'prepare', fail)
    with pytest.raises(deploy.DeploymentError):
        worker.deploy()
    assert calls == [False]
    assert (home / 'start.sh').read_text() == '# old launcher\n'
    assert not (root / 'current').exists()
    assert connection.execute('SELECT state FROM history').fetchall() == [('preserved',)]
    connection.close()


def test_failed_first_start_restores_legacy_launcher_and_does_not_clean(tmp_path, monkeypatch):
    home, root, db, connection = layout(tmp_path)
    fake_runtime(monkeypatch, db)
    monkeypatch.setattr(deploy, 'website_api', lambda *args, **kwargs:
                        {'webapp': {'command': '/bin/bash ' + str(home / 'start.sh')}})
    worker = deploy.Deployer(root)
    release = root / 'releases/new'
    release.mkdir(parents=True)
    monkeypatch.setattr(worker, 'prepare', lambda: release)
    worker.state['target'] = 'a' * 40
    def bad_health(*args):
        raise deploy.DeploymentError('health failed')
    monkeypatch.setattr(worker, 'wait_for_health', bad_health)
    called = []
    monkeypatch.setattr(deploy, 'cleanup', lambda *args, **kwargs: called.append(True))
    with pytest.raises(deploy.DeploymentError):
        worker.deploy(install=True, clean=True)
    assert (home / 'start.sh').read_text() == '# old launcher\n'
    assert not (root / 'current').exists()
    assert not called
    connection.close()


def test_cleanup_archives_junk_and_preserves_database_account_and_launcher(tmp_path):
    home, root, db, connection = layout(tmp_path)
    for name in ('.ssh', '.local', '.venv', 'old-build'):
        (home / name).mkdir()
        (home / name / 'file').write_text('fixture')
    (home / 'old.zip').write_text('old archive')
    (home / '.bashrc').write_text('account settings')
    (root / 'backups').mkdir()
    before = {str(path): path.read_bytes() for path in (home / '.env', home / 'start.sh', home / '.bashrc')}
    deploy.cleanup(home, root, str(db), home / '.env', apply=True)
    assert not (home / '.venv').exists()
    assert not (home / 'old-build').exists()
    assert not (home / 'old.zip').exists()
    assert (home / '.ssh/file').is_file() and (home / '.local/file').is_file()
    for name, data in before.items():
        assert Path(name).read_bytes() == data
    assert connection.execute('SELECT * FROM history').fetchall() == [('preserved',)]
    with tarfile.open(next((root / 'backups').glob('legacy-*.tar.gz'))) as archive:
        assert '.venv/file' in archive.getnames()
        assert 'old.zip' in archive.getnames()
        assert not any(name.startswith('data') for name in archive.getnames())
    connection.close()


def test_runtime_imports_new_release_and_resolves_db_from_home(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'socketstat').mkdir()
    (home / 'socketstat/__init__.py').write_text('raise RuntimeError("obsolete home package imported")')
    env = home / '.env'
    env.write_text('DB_PATH=./data/live.sqlite\n')
    release = tmp_path / 'release'
    (release / '.venv/bin').mkdir(parents=True)
    python = release / '.venv/bin/python'
    actual_python = Path('.venv/bin/python').absolute()
    python.write_text('#!/bin/bash\nexec "' + str(actual_python) + '" "$@"\n')
    python.chmod(0o700)
    (release / 'socketstat').mkdir()
    (release / 'socketstat/__init__.py').write_text('')
    (release / 'socketstat/config.py').write_text('''from pathlib import Path
from types import SimpleNamespace
import os
class Settings:
    @classmethod
    def from_env(cls):
        return SimpleNamespace(db_path=Path(os.environ['DB_PATH']))
''')
    result = deploy.runtime(python, home, env)
    assert result['db'] == str(home / 'data/live.sqlite')


def app_settings(tmp_path):
    return Settings((Device('one', 'One'), Device('two', 'Two')),
                    'https://openapi.tuyaeu.com', 'client', 'secret',
                    'admin', 'long-test-password', tmp_path / 'db.sqlite', True)


def test_update_routes_require_auth_and_csrf_and_same_origin(tmp_path, monkeypatch):
    monkeypatch.delenv('SOCKETSTAT_DEPLOY_ROOT', raising=False)
    started = []
    monkeypatch.setattr(Updates, 'start', lambda self: started.append(True) or {'accepted': True})
    with TestClient(create_app(app_settings(tmp_path))) as client:
        auth = ('admin', 'long-test-password')
        assert client.get('/updates').status_code == 401
        assert client.get('/api/updates').status_code == 401
        assert client.post('/api/updates').status_code == 401
        assert client.get('/updates', auth=auth).status_code == 200
        assert client.get('/assets/updates.js', auth=auth).status_code == 200
        csrf = client.get('/api/updates', auth=auth).json()['csrf']
        assert client.post('/api/updates', auth=auth).status_code == 403
        headers = {'X-SocketStat-Token': csrf, 'Origin': 'https://other.example'}
        assert client.post('/api/updates', auth=auth, headers=headers).status_code == 403
        headers['Origin'] = 'http://testserver'
        assert client.post('/api/updates', auth=auth, headers=headers).status_code == 202
        assert started == [True]


def test_update_lock_rejects_second_request(tmp_path):
    import fcntl
    from fastapi import HTTPException
    deploy.atomic_json(tmp_path / 'deployment.json', {'home': str(tmp_path)})
    manager = Updates(tmp_path)
    with (tmp_path / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(HTTPException) as error:
            manager.start()
        assert error.value.status_code == 409


def test_restart_only_marks_success_for_running_target(tmp_path):
    deploy.atomic_json(tmp_path / 'deployment.json', {'home': str(tmp_path)})
    deploy.atomic_json(tmp_path / 'state.json', {'phase': 'restarting', 'target': 'a' * 40})
    manager = Updates(tmp_path)
    manager.revision = 'b' * 40
    manager.started()
    assert deploy.read_json(tmp_path / 'state.json')['phase'] == 'restarting'
    manager.revision = 'a' * 40
    manager.started()
    assert deploy.read_json(tmp_path / 'state.json')['phase'] == 'success'


def test_snapshots_are_bounded_and_do_not_delete_legacy_archive(tmp_path):
    home, root, db, connection = layout(tmp_path)
    (root / 'backups').mkdir()
    archive = root / 'backups/legacy-keep.tar.gz'
    archive.write_bytes(b'fixture-archive')
    for _ in range(7):
        deploy.snapshot(root, home / '.env', str(db), home)
    assert len([path for path in (root / 'backups').iterdir() if path.is_dir()]) == 5
    assert archive.read_bytes() == b'fixture-archive'
    connection.close()
