"""Backups: consistent copies, owner-only files, old copies pruned."""
import datetime as dt, os, sqlite3, sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backup


def make_db(p):
    with closing(sqlite3.connect(p)) as db:
        db.execute("CREATE TABLE t (x)"); db.execute("INSERT INTO t VALUES (42)"); db.commit()


def test_backup_copies_data_and_prunes(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    db = tmp_path / "jobs.db"; make_db(db)
    made = [backup.run_backup(db, keep=3, now=dt.datetime(2026, 1, 1) + dt.timedelta(days=i)) for i in range(5)]
    left = sorted((tmp_path / "backups").glob("jobs-*.db"))
    assert left == made[-3:]
    with closing(sqlite3.connect(left[-1])) as c:
        assert c.execute("SELECT x FROM t").fetchone() == (42,)
    if os.name == "posix":
        assert (left[-1].stat().st_mode & 0o077) == 0
    assert not list((tmp_path / "backups").glob("*.part"))


def test_backup_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "elsewhere"))
    db = tmp_path / "jobs.db"; make_db(db)
    out = backup.run_backup(db)
    assert out.parent == tmp_path / "elsewhere"
