import asyncio
import logging
import time

from .tuya import TuyaError

logger = logging.getLogger(__name__)


async def poll_device(store, tuya, device, slot, demo=False):
    try:
        if demo:
            phase = (slot // 60 + (13 if device.id.endswith('2') else 0)) % 90
            state = 'offline' if 30 <= phase < 45 else 'online'
        else:
            # Hard overall deadline includes retries and token acquisition.
            state = await asyncio.wait_for(tuya.online(device.id), timeout=40)
        error = None
    except asyncio.TimeoutError:
        state, error = 'unknown', 'poll_timeout'
    except TuyaError as exc:
        state, error = 'unknown', exc.code
    except Exception:
        logger.error('Unexpected polling failure')
        state, error = 'unknown', 'internal_error'
    # Failed writes escape to the supervisor; no invented backfill on restart.
    store.save(device.id, slot, time.time(), state, error)


async def collect(store, tuya, settings):
    last_slot = None
    cleanup_hour = None
    while True:
        try:
            now = time.time()
            hour = int(now // 3600)
            if hour != cleanup_hour:
                store.cleanup(now)
                cleanup_hour = hour
            slot = int(now // 60) * 60
            if slot != last_slot:
                results = await asyncio.gather(*(
                    poll_device(store, tuya, device, slot, settings.demo)
                    for device in settings.devices
                ), return_exceptions=True)
                if any(isinstance(result, Exception) for result in results):
                    logger.error('Observation write failed; missing slots will remain unknown')
                last_slot = slot
        except Exception:
            logger.error('Collector iteration failed; retrying next minute')
        # Align to wall-clock minutes rather than accumulating request duration drift.
        await asyncio.sleep(max(0.1, 60 - time.time() % 60))
