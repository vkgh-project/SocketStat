import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    id: str
    name: str


@dataclass(frozen=True)
class Settings:
    devices: tuple
    endpoint: str
    client_id: str
    client_secret: str
    username: str
    password: str
    db_path: Path
    demo: bool = False

    @classmethod
    def from_env(cls, *, require_dashboard_auth=True):
        demo = os.getenv('DEMO_MODE', 'false').lower() == 'true'
        devices = tuple(Device(
            os.getenv(f'SOCKET_{i}_ID', '') or (f'demo-{i}' if demo else ''),
            os.getenv(f'SOCKET_{i}_NAME', f'Розетка {i}'),
        ) for i in (1, 2))
        client_id = os.getenv('TUYA_CLIENT_ID', '')
        secret = os.getenv('TUYA_CLIENT_SECRET', '')
        username = os.getenv('DASHBOARD_USER', 'admin')
        password = os.getenv('DASHBOARD_PASSWORD', '')
        if require_dashboard_auth and (not username or len(password) < 12):
            raise ValueError('Set DASHBOARD_USER and DASHBOARD_PASSWORD (at least 12 characters)')
        if not demo and (not client_id or not secret):
            raise ValueError('Set TUYA_CLIENT_ID and TUYA_CLIENT_SECRET')
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', d.id) for d in devices):
            raise ValueError('Set valid SOCKET_1_ID and SOCKET_2_ID')
        if devices[0].id == devices[1].id:
            raise ValueError('The two socket IDs must be different')
        endpoint = os.getenv('TUYA_ENDPOINT', 'https://openapi.tuyaeu.com').rstrip('/')
        allowed = {
            'https://openapi.tuyaeu.com', 'https://openapi-weaz.tuyaeu.com',
            'https://openapi.tuyaus.com', 'https://openapi-ueaz.tuyaus.com',
            'https://openapi.tuyacn.com', 'https://openapi.tuyain.com',
            'https://openapi-sg.iotbing.com',
        }
        if endpoint not in allowed:
            raise ValueError('TUYA_ENDPOINT must be an official regional Tuya API endpoint')
        return cls(devices, endpoint, client_id, secret, username, password,
                   Path(os.getenv('DB_PATH', './data/socketstat.db')), demo)
