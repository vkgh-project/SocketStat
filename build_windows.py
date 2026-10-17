"""Run with the Windows Python that has requirements-build.txt installed."""
from pathlib import Path
import shutil
import subprocess
import sys

if sys.platform != 'win32':
    raise SystemExit('Build the Windows executable on Windows.')

root = Path(__file__).resolve().parent
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console', '--noupx',
    '--name', 'SocketStat', '--distpath', 'dist/windows', '--workpath', 'build', '--specpath', 'build',
    '--add-data', f'{root / "socketstat" / "static"}:socketstat/static',
    '--add-data', f'{root / ".env.example"}:.',
    'windows_launcher.py',
], cwd=root, check=True)
shutil.copyfile(root / '.env.example', root / 'dist' / 'windows' / '.env.example')
print('Created dist/windows/SocketStat.exe. No Python installation is required to run it.')
