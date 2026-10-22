import asyncio
import secrets
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .collector import collect
from .config import Settings
from .store import RETENTION, Store
from .timeline import summarize
from .tuya import TuyaClient

STATIC = Path(__file__).parent / 'static'
security = HTTPBasic(auto_error=False)


def create_app(settings=None, *, local=False):
    @asynccontextmanager
    async def lifespan(app):
        nonlocal settings
        if settings is None:
            load_dotenv()
            settings = Settings.from_env(require_dashboard_auth=not local)
        app.state.settings = settings
        app.state.store = Store(settings.db_path)
        app.state.store.cleanup(time.time())
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            task = asyncio.create_task(collect(app.state.store, TuyaClient(settings, client), settings))
            app.state.collector = task
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title='SocketStat', lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)

    def authenticate(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
        if local:
            loopback = {'127.0.0.1', '::1'}
            server = request.scope.get('server')
            if (server and server[0] in loopback and request.client
                    and request.client.host in loopback):
                return
            raise HTTPException(403, 'Local dashboard requires a loopback connection')
        if credentials is None:
            raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Basic'})
        config = app.state.settings
        user_ok = secrets.compare_digest(credentials.username.encode(), config.username.encode())
        pass_ok = secrets.compare_digest(credentials.password.encode(), config.password.encode())
        if not (user_ok and pass_ok):
            raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Basic'})

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get('/healthz')
    def health():
        # Liveness, not Tuya reachability: a provider outage must not restart the app.
        if app.state.collector.done():
            raise HTTPException(503, 'Collector stopped')
        with app.state.store.connect() as db:
            db.execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/', dependencies=[Depends(authenticate)])
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/assets/{name}', dependencies=[Depends(authenticate)])
    def asset(name: str):
        if name not in ('app.js', 'style.css'):
            raise HTTPException(404)
        return FileResponse(STATIC / name)

    @app.get('/api/dashboard', dependencies=[Depends(authenticate)])
    def dashboard(hours: float = Query(24, ge=1, le=336)):
        now = time.time()
        start = now - hours * 3600
        weekly_start = now - RETENTION
        weekly_devices = []
        local_now = datetime.fromtimestamp(now, ZoneInfo('Europe/Kyiv'))
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = midnight.timestamp()
        day_end = (midnight + timedelta(days=1)).timestamp()
        devices = []
        for device in app.state.settings.devices:
            weekly_devices.append({
                'name': device.name,
                'intervals': summarize(app.state.store.read(device.id, weekly_start, now),
                                       weekly_start, now)['intervals'],
            })
            latest = app.state.store.latest(device.id)
            current = (latest['state'] if latest and now - latest['scheduled_at'] < 120
                       else 'unknown')
            item = summarize(app.state.store.read(device.id, start, now), start, now)
            today_intervals = (summarize(app.state.store.read(device.id, day_start, now),
                                         day_start, now)['intervals']
                               if now > day_start else [])
            item.update({'name': device.name, 'state': current,
                         'today_intervals': today_intervals,
                         'last_checked_at': latest['checked_at'] if latest else None,
                         'error_code': latest['error_code'] if latest else None})
            devices.append(item)
        return {'start': start, 'end': now, 'timezone': 'Europe/Kyiv',
                'demo': app.state.settings.demo, 'devices': devices,
                'weekly': {'start': weekly_start, 'end': now, 'devices': weekly_devices},
                'today': {'start': day_start, 'end': day_end}}

    return app


def create_local_app():
    """Password-free entry point; serve on 127.0.0.1 with --factory."""
    return create_app(local=True)


app = create_app()
