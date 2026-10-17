import asyncio
import hashlib
import hmac
import time

import httpx


class TuyaError(Exception):
    def __init__(self, code):
        self.code = str(code)[:80]
        super().__init__(self.code)


class TuyaClient:
    def __init__(self, settings, client):
        self.settings = settings
        self.client = client
        self.token = ''
        self.expires_at = 0
        self.lock = asyncio.Lock()

    def headers(self, path, token='', timestamp=None):
        timestamp = timestamp or str(int(time.time() * 1000))
        content_hash = hashlib.sha256(b'').hexdigest()
        to_sign = f'GET\n{content_hash}\n\n{path}'
        message = self.settings.client_id + token + timestamp + to_sign
        signature = hmac.new(self.settings.client_secret.encode(), message.encode(),
                             hashlib.sha256).hexdigest().upper()
        headers = {'client_id': self.settings.client_id, 't': timestamp,
                   'sign_method': 'HMAC-SHA256', 'sign': signature}
        if token:
            headers['access_token'] = token
        return headers

    async def request(self, path, token=''):
        # One retry for transient errors only. Never log credentials or response bodies.
        for attempt in range(2):
            try:
                response = await self.client.get(
                    self.settings.endpoint + path, headers=self.headers(path, token))
                if response.status_code >= 500 or response.status_code == 429:
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise TuyaError('invalid_response')
                if data.get('success') is not True:
                    raise TuyaError(data.get('code', 'api_error'))
                result = data.get('result')
                if not isinstance(result, dict):
                    raise TuyaError('invalid_result')
                return result
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                raise TuyaError('network_error') from None
            except httpx.HTTPStatusError as exc:
                raise TuyaError(f'http_{exc.response.status_code}') from None
            except ValueError:
                raise TuyaError('invalid_json') from None
        raise TuyaError('request_failed')

    async def get_token(self):
        async with self.lock:
            if time.monotonic() >= self.expires_at:
                result = await self.request('/v1.0/token?grant_type=1')
                token = result.get('access_token')
                ttl = result.get('expire_time')
                if not isinstance(token, str) or not token or type(ttl) not in (int, float) or ttl <= 0:
                    raise TuyaError('invalid_token_response')
                self.token = token
                self.expires_at = time.monotonic() + max(0, ttl - 60)
            return self.token

    async def online(self, device_id):
        path = f'/v1.0/iot-03/devices/{device_id}'
        for attempt in range(2):
            token = await self.get_token()
            try:
                result = await self.request(path, token)
                if type(result.get('online')) is not bool:
                    raise TuyaError('missing_online_field')
                return 'online' if result['online'] else 'offline'
            except TuyaError as exc:
                if exc.code in ('1010', '1011') and attempt == 0:
                    async with self.lock:
                        if self.token == token:
                            self.expires_at = 0
                    continue
                raise
        raise TuyaError('token_refresh_failed')
