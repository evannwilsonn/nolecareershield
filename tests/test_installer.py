"""The one-file installer must unpack every tracked file exactly as it is in the repo."""
import ast
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import make_installer  # noqa: E402


def _files() -> dict:
    tree = ast.parse((ROOT / "setup_jobboard.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "FILES")
    return ast.literal_eval(node.value)


def test_installer_unpacks_every_tracked_file():
    files = _files()
    try:
        expected = make_installer.tracked()
    except Exception:  # not a git checkout (e.g. unpacked from the installer): check what's there
        expected = sorted(files)
    missing = sorted(set(expected) - set(files))
    assert not missing, f"setup_jobboard.py is missing {missing}. Run: python make_installer.py"
    for path, b64 in files.items():
        data = base64.b64decode(b64, validate=True)
        assert data == (ROOT / path).read_bytes(), f"setup_jobboard.py has an old copy of {path}. Run: python make_installer.py"
