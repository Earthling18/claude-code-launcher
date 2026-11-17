"""Package only tracked public source files; never include local profiles/deps."""
import json
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
version = json.loads((root / 'package.json').read_text(encoding='utf-8'))['version']
output = root / 'qa-artifacts' / f'Python-Connection_{version}.zip'
output.parent.mkdir(exist_ok=True)
files = subprocess.check_output(
    ['git', 'ls-files', '-z', 'python-connection'], cwd=root
).decode().split('\0')
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        if not name:
            continue
        parts = Path(name).parts
        if any(p in ('profiles', '.deps', '__pycache__') or p.startswith('.manager') for p in parts):
            raise SystemExit('Private path is tracked; refusing to package: ' + name)
        archive.write(root / name, name)
print(output)
