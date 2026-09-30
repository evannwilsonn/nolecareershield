"""Rebuild setup_jobboard.py, the one-file installer, from every tracked file.

    python tools/make_installer.py

Run it after `git add` and before committing. Every file is stored base64-encoded, so binary files (the display
font) survive. Not included: the installer itself and the built demo pages (run demo/build.py to make those).
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "setup_jobboard.py"

HEAD = '''"""NoleCareerShield: one-file setup. Run once in an empty folder: python setup_jobboard.py

Never overwrites a jobs.db or .env you already have (neither is included).
"""
import base64, os

FILES = {
'''
TAIL = '''}

def main():
    for path, b64 in FILES.items():
        d = os.path.dirname(path)
        if d: os.makedirs(d, exist_ok=True)
        open(path, 'wb').write(base64.b64decode(b64))
    print(f'Wrote {len(FILES)} files.\\n')
    print('Next:')
    print('  pip install -r requirements.txt')
    print('  python -m uvicorn app:app --reload')
    print('  site: http://127.0.0.1:8000   review queue: http://127.0.0.1:8000/admin (dev password: changeme)')
    print('  tests: pip install -r requirements-dev.txt && python -m pytest -q')
    print('  improving the detector: see scam_detector/ADAPTING.md')
    print('Production settings are documented in README.md and .env.example.')

if __name__ == '__main__':
    main()
'''


def main() -> None:
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
    names = sorted(n for n in names if n != OUT.name and not n.endswith(".html") and (ROOT / n).is_file())
    lines = [f"    {n!r}: {base64.b64encode((ROOT / n).read_bytes()).decode()!r},\n" for n in names]
    OUT.write_text(HEAD + "".join(lines) + TAIL)
    print(f"wrote {OUT.name} with {len(names)} files ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
