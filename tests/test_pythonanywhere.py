import importlib.util
from pathlib import Path

import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[1] / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_startup_anchors_config_and_database_to_project(tmp_path, monkeypatch):
    module = load_script('pythonanywhere_start')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setenv('DOMAIN_SOCKET', '/host/app.sock')
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'test-password-long')
    monkeypatch.setenv('DASHBOARD_USER', 'admin')
    monkeypatch.setenv('SOCKET_1_ID', 'demo-1')
    monkeypatch.setenv('SOCKET_2_ID', 'demo-2')
    monkeypatch.setenv('TUYA_ENDPOINT', 'https://openapi.tuyaeu.com')
    monkeypatch.setenv('DB_PATH', './data/socketstat.db')
    monkeypatch.chdir(tmp_path.parent)
    calls = []
    monkeypatch.setattr(module.uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    loaded = []
    monkeypatch.setattr(module, 'load_dotenv', lambda path: loaded.append(path))
    module.main(['--check'])
    assert not calls
    assert loaded == [tmp_path / '.env']
    assert module.Settings.from_env().db_path.resolve() == tmp_path / 'data' / 'socketstat.db'
    module.main([])
    assert calls == [(('socketstat.app:app',), {
        'uds': '/host/app.sock', 'workers': 1, 'lifespan': 'on',
    })]


def test_startup_requires_host_socket(monkeypatch):
    module = load_script('pythonanywhere_start')
    monkeypatch.delenv('DOMAIN_SOCKET', raising=False)
    with pytest.raises(SystemExit) as error:
        module.main([])
    assert error.value.code == 2
