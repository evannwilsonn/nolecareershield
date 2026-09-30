"""
Nightly database backups.

Uses SQLite's online backup API, so a copy is consistent even while the site is
serving requests. Copies go to BACKUP_DIR (default: a `backups` folder next to the
database, i.e. /data/backups on Render) and the newest BACKUP_KEEP (default 14) are kept.

These copies live on the same disk as the database. They protect against mistakes
(a bad delete, a broken migration). Render's own daily disk snapshots protect against
losing the disk. For an off-site copy, download one with `python backup.py --latest`
from a Render shell, or add object storage later.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def backup_dir(db_path: Path) -> Path:
    return Path(os.environ.get("BACKUP_DIR") or (Path(db_path).resolve().parent / "backups"))


def run_backup(db_path: Path, keep: int | None = None, now: dt.datetime | None = None) -> Path:
    """Write one consistent copy of the database and prune old copies. Returns the new file."""
    keep = keep if keep is not None else int(os.environ.get("BACKUP_KEEP", "14"))
    dest_dir = backup_dir(db_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.utcnow()).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"jobs-{stamp}.db"
    tmp = dest.with_suffix(".db.part")
    with closing(sqlite3.connect(db_path)) as src, closing(sqlite3.connect(tmp)) as out:
        src.backup(out)
    tmp.replace(dest)
    try:
        os.chmod(dest, 0o600)                      # database copies hold password hashes: owner-only
    except OSError:
        pass
    copies = sorted(dest_dir.glob("jobs-*.db"))
    for old in copies[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return dest


if __name__ == "__main__":
    db = Path(os.environ.get("DB_PATH", "jobs.db"))
    if "--latest" in sys.argv:
        copies = sorted(backup_dir(db).glob("jobs-*.db"))
        print(copies[-1] if copies else "no backups yet")
    else:
        print("wrote", run_backup(db))
