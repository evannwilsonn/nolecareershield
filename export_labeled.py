"""
Export reviewer decisions as labeled data for the scam detector.

Every time a reviewer approves, rejects or removes a listing, the board records a
label: legit, scam, lead_gen (aggregator), or other (spam, duplicate, off-topic).
This turns those decisions into the JSONL format the detector's tools read, so the
detector can learn from what the humans actually caught.

    python export_labeled.py --db /data/jobs.db -o labeled.jsonl

    # then, inside the scam_detector package:
    python -m scam_detector.tools.mine_candidates labeled.jsonl scam_detector/data/*.jsonl -o proposed.json
    python -m scam_detector.tools.regress --candidate proposed.json
    python -m scam_detector.tools.regress --candidate proposed.json --promote   # after you have read it

Notes
  * `other` decisions are skipped: they are not scam judgments.
  * Employer contact and location fields are never exported, and email addresses and
    phone numbers in the text are masked (email domains are kept because the detector
    checks them).
  * Rejected and removed rows are purged from the board after PURGE_REJECTED_DAYS
    (default 90). Export before then, for example monthly, or those examples are lost.
  * Labels are only as good as the reviewers who set them. Never feed this from
    anything the public can influence directly.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

_EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")


def mask(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub(lambda m: "[email]@" + m.group(1), text or ""))


def export(db_path: Path, out_path: Path) -> dict:
    counts = {"legit": 0, "scam": 0, "lead_gen": 0, "skipped_other": 0, "detector_missed": 0}
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
        if "review_label" not in cols:
            raise SystemExit("This database predates reviewer labels. Start the app once to migrate it, "
                             "then review some listings.")
        rows = db.execute("SELECT * FROM jobs WHERE review_label IS NOT NULL ORDER BY id").fetchall()
        check_cols = {r[1] for r in db.execute("PRAGMA table_info(submitted_checks)")}
        checks = (db.execute("SELECT * FROM submitted_checks WHERE review_label IN ('legit','scam','lead_gen') ORDER BY id").fetchall()
                  if "review_label" in check_cols else [])
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            label = r["review_label"]
            if label not in ("legit", "scam", "lead_gen"):
                counts["skipped_other"] += 1
                continue
            if label != "legit" and r["scam_status"] == "clear":
                counts["detector_missed"] += 1
            counts[label] += 1
            f.write(json.dumps({
                "label": label,
                "title": mask(r["title"]), "company": mask(r["company"]),
                "description": mask(r["description"]),
                "url": r["apply_url"] or "",
                "context_flags": [],
                "notes": f"review-queue export; detector band={r['band']} score={r['score']} "
                         f"ruleset={r['ruleset_version'] or 'unknown'}",
            }) + "\n")
        # Things people sent in from the scam check, once a reviewer confirmed the label (the label queue).
        for r in checks:
            counts[r["review_label"]] += 1
            counts["from_checks"] = counts.get("from_checks", 0) + 1
            desc = r["body"] if r["kind"] == "listing" else r["body"] + (f"\n{r['sender']}" if r["sender"] else "")
            f.write(json.dumps({
                "label": r["review_label"], "kind": r["kind"], "title": mask(r["title"]), "company": mask(r["company"]),
                "description": mask(desc), "url": r["url"] or "", "context_flags": [],
                "notes": f"scam-check submission ({r['source']}), reviewer label; detector band={r['band']}",
            }) + "\n")
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path("jobs.db"))
    ap.add_argument("-o", "--out", type=Path, default=Path("labeled.jsonl"))
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"no database at {args.db}", file=sys.stderr)
        return 1
    c = export(args.db, args.out)
    print(f"wrote {args.out}: {c['legit']} legit, {c['scam']} scam, {c['lead_gen']} lead_gen "
          f"({c['skipped_other']} 'other' skipped)")
    print(f"detector had scored {c['detector_missed']} of the bad ones as clear (these are what the miner learns from)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
