"""Build the portable macOS package using requirements-build.txt."""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


if sys.platform != 'darwin':
    raise SystemExit('Build the macOS executable on macOS.')

root = Path(__file__).resolve().parent
output = root / 'dist' / 'macos'
package = output / 'SocketStat'
package.mkdir(parents=True, exist_ok=True)
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console', '--noupx',
    '--name', 'SocketStat', '--distpath', str(package),
    '--workpath', 'build/macos', '--specpath', 'build/macos',
    '--add-data', f'{root / "socketstat" / "static"}:socketstat/static',
    '--add-data', f'{root / ".env.example"}:.',
    'desktop_launcher.py',
], cwd=root, check=True)
shutil.copyfile(root / '.env.example', package / '.env.example')
launcher = package / 'Start SocketStat.command'
launcher.write_text('#!/bin/bash\ncd "$(dirname "$0")" || exit 1\nexec ./SocketStat "$@"\n')
launcher.chmod(0o755)
(package / 'README.txt').write_text(
    'SocketStat for macOS (' + platform.machine() + ')\n\n'
    'Extract this folder to a writable location, such as Documents.\n'
    'Double-click Start SocketStat.command. The first launch creates .env;\n'
    'edit it with your Tuya settings,\n'
    'then launch again. Credentials are not included in this package.\n'
    'The dashboard opens at http://127.0.0.1:8000. Keep Terminal open;\n'
    'press Ctrl+C to stop. The Mac must stay awake to collect observations.\n'
    'History is stored in data/socketstat.db beside the executable.\n'
    'Run only one instance. Python is not required.\n\n'
    'This local build is ad-hoc signed and is not Apple notarized.\n'
    'For a downloaded copy blocked by macOS, use System Settings >\n'
    'Privacy & Security > Open Anyway if you trust its source.\n', encoding='utf-8')
archive = output / f'SocketStat-macos-{platform.machine()}.zip'
# Include only release files, even if this folder has been used to run the app.
with ZipFile(archive, 'w', ZIP_DEFLATED) as zipped:
    for name in ('SocketStat', '.env.example', launcher.name, 'README.txt'):
        zipped.write(package / name, f'{package.name}/{name}')
print(f'Created {archive}. No Python installation is required to run it.')
