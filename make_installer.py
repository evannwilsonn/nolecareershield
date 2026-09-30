"""Rebuild setup_jobboard.py, the one-file installer, from every file git tracks.

    python make_installer.py

Run it before each commit. The built demo pages are left out (python demo/build.py makes
them), and so is the installer itself. tests/test_installer.py fails if it's out of date.
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "setup_jobboard.py"
SKIP = {"setup_jobboard.py", "demo/index.html", "demo/NoleCareerShield_Demo.html"}

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


def tracked() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split("\n")
    return sorted(p for p in out if p and p not in SKIP and (ROOT / p).is_file())


def build(paths: list[str] | None = None) -> str:
    rows = [f"    {p!r}: {base64.b64encode((ROOT / p).read_bytes()).decode()!r},\n" for p in (paths or tracked())]
    return HEAD + "".join(rows) + TAIL


if __name__ == "__main__":
    paths = tracked()
    text = build(paths)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.name}: {len(paths)} files, {len(text) // 1024} KB")
