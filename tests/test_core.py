import asyncio
import hashlib
import hmac
import importlib
from datetime import datetime
from types import SimpleNamespace

import pytest
import time

import httpx
from fastapi.testclient import TestClient

from socketstat.app import create_app
from socketstat.collector import poll_device
from socketstat.config import Device, Settings
from socketstat.store import RETENTION, Store
from socketstat.timeline import summarize
from socketstat.tuya import TuyaClient


def settings(tmp_path):
    return Settings((Device('one', 'Перша'), Device('two', 'Друга')),
                    'https://openapi.tuyaeu.com', 'client', 'secret',
                    'admin', 'long-test-password', tmp_path / 'db.sqlite', True)


def test_gap_never_becomes_an_outage():
    rows = [{'scheduled_at': 60, 'state': 'offline'},
            {'scheduled_at': 180, 'state': 'offline'}]
    result = summarize(rows, 60, 240)
    assert [i['state'] for i in result['intervals']] == ['offline', 'unknown', 'offline']
    assert result['stats']['seconds'] == {'online': 0, 'offline': 120, 'unknown': 60}
    assert result['stats']['longest_offline_seconds'] == 60
    assert result['stats']['coverage_percent'] == 66.67


def test_clip_and_merge():
    result = summarize([{'scheduled_at': 60, 'state': 'offline'},
                        {'scheduled_at': 120, 'state': 'offline'},
                        {'scheduled_at': 180, 'state': 'online'}], 90, 210)
    assert result['intervals'] == [
        {'start': 90, 'end': 180, 'state': 'offline'},
        {'start': 180, 'end': 210, 'state': 'online'},
    ]
    assert result['stats']['availability_percent'] == 25


def test_empty_history_is_unknown():
    result = summarize([], 0, 600)
    assert result['stats']['availability_percent'] is None
    assert result['stats']['coverage_percent'] == 0
    assert result['stats']['seconds']['unknown'] == 600


def test_retention_and_idempotence(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    now = RETENTION + 600
    store.save('one', 0, 1, 'offline')
    store.save('one', 600, 601, 'online')
    store.save('one', 600, 602, 'offline')
    store.save('two', 600, 603, 'offline')
    store.cleanup(now)
    rows = store.read('one', 0, now)
    assert len(rows) == 1
    assert rows[0]['state'] == 'online'
    assert store.latest('two')['state'] == 'offline'


def test_signed_get_and_token_refresh(tmp_path):
    async def scenario():
        token_calls = 0
        device_calls = 0

        def handler(request):
            nonlocal token_calls, device_calls
            path = request.url.raw_path.decode()
            token = request.headers.get('access_token', '')
            message = ('client' + token + request.headers['t'] + 'GET\n' +
                       hashlib.sha256(b'').hexdigest() + '\n\n' + path)
            expected = hmac.new(b'secret', message.encode(), hashlib.sha256).hexdigest().upper()
            assert request.headers['sign'] == expected
            if path.startswith('/v1.0/token'):
                token_calls += 1
                return httpx.Response(200, json={'success': True, 'result': {
                    'access_token': f'token-{token_calls}', 'expire_time': 7200}})
            device_calls += 1
            if device_calls == 1:
                return httpx.Response(200, json={'success': False, 'code': 1010})
            return httpx.Response(200, json={'success': True, 'result': {'online': False}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tuya = TuyaClient(settings(tmp_path), client)
            assert await tuya.online('one') == 'offline'
            assert await tuya.online('two') == 'offline'
        assert token_calls == 2
    asyncio.run(scenario())


def test_missing_online_is_unknown_and_other_socket_still_works(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'db.sqlite')
        def handler(request):
            if request.url.path == '/v1.0/token':
                result = {'access_token': 'token', 'expire_time': 7200}
            elif request.url.path.endswith('/one'):
                result = {'status': [{'code': 'switch_1', 'value': False}]}
            else:
                result = {'online': True}
            return httpx.Response(200, json={'success': True, 'result': result})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            config = settings(tmp_path)
            tuya = TuyaClient(config, client)
            await asyncio.gather(*(poll_device(store, tuya, d, 120) for d in config.devices))
        assert store.latest('one')['state'] == 'unknown'
        assert store.latest('one')['error_code'] == 'missing_online_field'
        assert store.latest('two')['state'] == 'online'
    asyncio.run(scenario())


def test_http_errors_are_unknown(tmp_path):
    async def scenario():
        config = settings(tmp_path)
        store = Store(config.db_path)
        def handler(request):
            return httpx.Response(403, json={'secret': 'never expose response body'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await poll_device(store, TuyaClient(config, client), config.devices[0], 120)
        assert store.latest('one')['error_code'] == 'http_403'
        assert store.latest('one')['state'] == 'unknown'
    asyncio.run(scenario())


def test_app_auth_and_dashboard(tmp_path):
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        assert client.get('/').status_code == 401
        assert client.get('/api/dashboard').status_code == 401
        assert client.get('/healthz').status_code == 200
        auth = ('admin', 'long-test-password')
        assert client.get('/', auth=auth).status_code == 200
        assert client.get('/assets/app.js', auth=auth).status_code == 200
        assert client.get('/api/dashboard?hours=337', auth=auth).status_code == 422
        assert client.get('/api/dashboard?hours=0', auth=auth).status_code == 422
        assert client.get('/api/dashboard?hours=0.000001', auth=auth).status_code == 422
        response = client.get('/api/dashboard?hours=336', auth=auth)
        assert response.status_code == 200
        data = response.json()
        assert len(data['devices']) == 2
        assert data['demo'] is True
        assert data['end'] - data['start'] <= RETENTION
        assert response.headers['cache-control'] == 'no-store'


def test_local_dashboard_requires_no_credentials(tmp_path):
    with TestClient(create_app(settings(tmp_path), local=True),
                    base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000)) as client:
        for path in ('/', '/assets/app.js', '/assets/style.css', '/api/dashboard'):
            assert client.get(path).status_code == 200


@pytest.mark.parametrize(('host', 'peer'), [
    ('127.0.0.1', '192.168.1.10'),
    ('192.168.1.10', '127.0.0.1'),
])
def test_local_dashboard_rejects_non_loopback_connections(tmp_path, host, peer):
    with TestClient(create_app(settings(tmp_path), local=True),
                    base_url=f'http://{host}:8000', client=(peer, 50000)) as client:
        assert client.get('/api/dashboard').status_code == 403


def test_local_settings_allow_no_dashboard_password(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('SOCKET_1_ID', '')
    monkeypatch.setenv('SOCKET_2_ID', '')
    monkeypatch.setenv('TUYA_ENDPOINT', 'https://openapi.tuyaeu.com')
    monkeypatch.setenv('DASHBOARD_PASSWORD', '')
    assert Settings.from_env(require_dashboard_auth=False).password == ''
    with pytest.raises(ValueError, match='DASHBOARD_PASSWORD'):
        Settings.from_env()


def test_stale_observation_is_not_current_offline(tmp_path):
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        old = int(time.time() // 60) * 60 - 300
        client.app.state.store.save('one', old, old + 1, 'offline')
        # Use a separate stale ID so the running demo collector cannot replace it.
        client.app.state.settings = Settings((Device('stale', 'Old'), Device('two', 'New')),
            config.endpoint, config.client_id, config.client_secret, config.username,
            config.password, config.db_path, True)
        client.app.state.store.save('stale', old, old + 1, 'offline')
        data = client.get('/api/dashboard', auth=('admin', 'long-test-password')).json()
        assert data['devices'][0]['state'] == 'unknown'


def test_demo_accepts_blank_device_ids(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'long-test-password')
    monkeypatch.setenv('SOCKET_1_ID', '')
    monkeypatch.setenv('SOCKET_2_ID', '')
    monkeypatch.setenv('TUYA_ENDPOINT', 'https://openapi.tuyaeu.com')
    config = Settings.from_env()
    assert [device.id for device in config.devices] == ['demo-1', 'demo-2']


def test_network_timeout_is_unknown(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'db.sqlite')
        calls = 0
        def handler(request):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout('timeout', request=request)
        config = settings(tmp_path)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await poll_device(store, TuyaClient(config, client), config.devices[0], 120)
        assert calls == 2
        assert store.latest('one')['state'] == 'unknown'
        assert store.latest('one')['error_code'] == 'network_error'
    asyncio.run(scenario())


@pytest.mark.parametrize(('start_iso', 'now_iso', 'end_iso', 'hours'), [
    ('2026-10-17T21:00:00+00:00', '2026-10-18T09:00:00+00:00', '2026-10-18T21:00:00+00:00', 24),
    ('2026-03-28T22:00:00+00:00', '2026-03-29T20:30:00+00:00', '2026-03-29T21:00:00+00:00', 23),
    ('2026-10-24T21:00:00+00:00', '2026-10-25T21:30:00+00:00', '2026-10-25T22:00:00+00:00', 25),
    ('2026-10-17T21:00:00+00:00', '2026-10-17T21:00:00+00:00', '2026-10-18T21:00:00+00:00', 24),
])
def test_current_kyiv_day_includes_midnight_even_on_dst_days(tmp_path, monkeypatch, start_iso, now_iso, end_iso, hours):
    module = importlib.import_module('socketstat.app')
    start, now, end = [datetime.fromisoformat(value).timestamp() for value in (start_iso, now_iso, end_iso)]

    async def idle_collector(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(module, 'collect', idle_collector)
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=lambda: now))
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        client.app.state.store.save('one', int(start), start + 1, 'offline')
        data = client.get('/api/dashboard?hours=1', auth=('admin', 'long-test-password')).json()
    assert data['today'] == {'start': start, 'end': end}
    assert end - start == hours * 3600
    intervals = data['devices'][0]['today_intervals']
    if now == start:
        assert intervals == []
    else:
        assert intervals[0] == {'start': start, 'end': start + 60, 'state': 'offline'}
        assert intervals[-1]['end'] == now
        assert data['devices'][1]['today_intervals'] == [{'start': start, 'end': now, 'state': 'unknown'}]
