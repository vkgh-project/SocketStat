"""Portable desktop entry point; writable files stay beside the executable."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import sys
import threading
import webbrowser

from dotenv import load_dotenv
import uvicorn

from socketstat.app import create_app
from socketstat.config import Settings


def main():
    parser = argparse.ArgumentParser(description='SocketStat local dashboard')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')

    bundled = getattr(sys, 'frozen', False)
    folder = Path(sys.executable if bundled else __file__).resolve().parent
    os.chdir(folder)
    env_path = folder / '.env'
    if not env_path.exists():
        shutil.copyfile(Path(__file__).resolve().parent / '.env.example', env_path)
        print(f'Створено {env_path}. Заповніть налаштування та запустіть програму повторно.')
        return 1
    load_dotenv(env_path)
    settings = Settings.from_env()

    # Reserve the port before opening the browser: a second launch cannot
    # accidentally open another service or start a duplicate collector.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if sys.platform == 'win32':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', args.port))
        listener.listen(128)
        config = uvicorn.Config(create_app(settings), host='127.0.0.1', port=args.port,
                                loop='asyncio', http='h11', ws='none', workers=1)
        server = uvicorn.Server(config)
        stopped = threading.Event()
        url = f'http://127.0.0.1:{args.port}'

        def open_when_ready():
            for _ in range(150):
                if stopped.wait(.2):
                    return
                if server.started:
                    webbrowser.open(url)
                    return

        print(f'SocketStat: {url}\nЗупинка: Ctrl+C. Для моніторингу залиште це вікно відкритим.')
        if not args.no_browser:
            threading.Thread(target=open_when_ready, daemon=True).start()
        try:
            server.run(sockets=[listener])
        except KeyboardInterrupt:
            # Uvicorn re-raises Ctrl+C after completing graceful shutdown.
            pass
        finally:
            stopped.set()
        return 0 if server.started else 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        result = main()
    except (OSError, ValueError) as exc:
        print(f'Не вдалося запустити SocketStat: {exc}', file=sys.stderr)
        result = 1
    if result and sys.stdin.isatty():
        input('Натисніть Enter, щоб закрити вікно…')
    raise SystemExit(result)
