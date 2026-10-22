"""Single-process ASGI entry point for PythonAnywhere's DOMAIN_SOCKET."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

from socketstat.config import Settings

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Validate configuration without starting the server or contacting Tuya')
    args = parser.parse_args(argv)
    socket = os.environ.get('DOMAIN_SOCKET')
    if not args.check and not socket:
        parser.error('DOMAIN_SOCKET is required; run this entry point as a PythonAnywhere ASGI website')

    # The hosting service may start us from an unrelated working directory.
    os.chdir(Path(os.environ.get('SOCKETSTAT_WORK_DIR', str(ROOT))))
    load_dotenv(Path(os.environ.get('SOCKETSTAT_ENV_FILE', str(ROOT / '.env'))))
    Settings.from_env()  # Fail before listening if credentials/configuration are invalid.
    if args.check:
        print('Configuration OK. Tuya connectivity has not been checked.')
        return

    # A single lifespan owns the minute-by-minute collector. Never enable reload
    # or additional workers: each would create another collector.
    uvicorn.run('socketstat.app:app', uds=socket, workers=1, lifespan='on')


if __name__ == '__main__':
    main()
