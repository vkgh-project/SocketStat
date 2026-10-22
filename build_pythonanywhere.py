"""Build an upload archive from an explicit list; exclude credentials and history."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent


def build():
    files = [ROOT / name for name in (
        'requirements.txt', '.env.example', 'pythonanywhere_start.py',
        'PYTHONANYWHERE.md', 'README.md', 'build_pythonanywhere.py',
        'deploy_pythonanywhere.py', 'update_pythonanywhere.sh',
    )]
    files += sorted((ROOT / 'socketstat').glob('*.py'))
    files += [ROOT / 'socketstat' / 'static' / name
              for name in ('index.html', 'style.css', 'app.js', 'updates.html', 'updates.js')]
    output = ROOT / 'output' / 'socketstat-pythonanywhere.zip'
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path('SocketStat') / path.relative_to(ROOT))
    print(output)
    return output


if __name__ == '__main__':
    build()
