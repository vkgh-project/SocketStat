"""Read-only Tuya connectivity check; never prints credentials or tokens."""
import asyncio
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

from socketstat.config import Settings
from socketstat.tuya import TuyaClient, TuyaError


async def check_website(settings, url):
    print('\nWebsite collector check:')
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            health = await http.get(url + '/healthz')
            print(f'Collector health: HTTP {health.status_code}')
            response = await http.get(
                url + '/api/dashboard?hours=1',
                auth=(settings.username, settings.password))
            print(f'Dashboard API: HTTP {response.status_code}')
            if response.status_code == 401:
                print('Website credentials differ from this .env, or the website has not reloaded it.')
                return
            if response.status_code != 200:
                return
            data = response.json()
            print(f'Website demo mode: {data.get("demo")}')
            for number, device in enumerate(data['devices'], 1):
                checked = device.get('last_checked_at')
                when = datetime.fromtimestamp(checked, timezone.utc).isoformat() if checked else 'never'
                age = f'{time.time() - checked:.0f} seconds ago' if checked else 'no observations'
                print(f'Socket {number}: status={device.get("state")}, last check={when} ({age}), '
                      f'error_code={device.get("error_code")}')
                if checked and time.time() - checked > 120:
                    print('  STALE: the collector has not saved a recent observation.')
            print('Fresh checks with online status mean polling is working; status stays online until Tuya changes it.')
    except Exception as exc:
        print(f'Website check failed ({type(exc).__name__}).')


async def main(website=None, env_file=None):
    load_dotenv(env_file or Path(__file__).resolve().parents[1] / '.env')
    try:
        settings = Settings.from_env(require_dashboard_auth=bool(website))
    except ValueError as exc:
        print(f'Configuration error: {exc}')
        return 1
    print(f'Tuya endpoint: {settings.endpoint}')
    if website:
        await check_website(settings, website)
    if settings.demo:
        print('DEMO_MODE=true: the website uses simulated data, not Tuya.')
        print('Set DEMO_MODE=false in .env and reload the website.')
        return 1

    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as http:
        client = TuyaClient(settings, http)

        async def check(label, operation):
            try:
                result = await asyncio.wait_for(operation(), timeout=40)
                print(f'{label}: OK' + (f' ({result})' if label != 'Authentication' else ''))
                return True
            except TuyaError as exc:
                print(f'{label}: FAILED, error_code={exc.code}')
            except httpx.ProxyError:
                print(f'{label}: FAILED, proxy connection blocked or unavailable.')
                print('On a free PythonAnywhere account, check the Tuya endpoint allowlist.')
            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                print(f'{label}: FAILED, network error ({type(exc).__name__}).')
            except Exception as exc:
                print(f'{label}: FAILED ({type(exc).__name__}).')
            return False

        if not await check('Authentication', client.get_token):
            return 1
        results = []
        for number, device in enumerate(settings.devices, 1):
            results.append(await check(f'Socket {number}', lambda: client.online(device.id)))
        if all(results):
            print('Tuya access works from this console. If the dashboard is stale,')
            print('reload the website and check its server log and .env path.')
        return 0 if all(results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).resolve().parents[1] / '.env',
                        help='Configuration file; defaults to the project .env')
    parser.add_argument('--website', help='Your HTTPS PythonAnywhere website URL')
    args = parser.parse_args()
    if args.website:
        parts = urlsplit(args.website)
        if (parts.scheme != 'https' or not parts.hostname or
                not parts.hostname.endswith('.eu.pythonanywhere.com') or
                parts.username or parts.password or parts.port or
                parts.path not in ('', '/') or parts.query or parts.fragment):
            parser.error('Use an HTTPS URL like https://YOURUSERNAME.eu.pythonanywhere.com')
    sys.exit(asyncio.run(main(args.website.rstrip('/') if args.website else None, args.env_file)))
