"""
NoleCareerShield — a curated job board for FSU students.

TWO LAYERS OF PROTECTION:
  1. Every submission is SCORED by the scam detector (scam_detector.scorer).
  2. Every submission then waits in a REVIEW QUEUE until an admin approves it.
     Nothing is public until a human approves it.

Anyone may BROWSE. Students (confirmed @fsu.edu email) log in to see how to apply;
employers (any confirmed email) log in to submit. Only an admin can approve postings.
Posting is account-gated and approval-gated, not open-publish.

PRIVACY BY DESIGN:
  Accounts hold an email, a role and a password hash: no names, resumes or profiles
  (see accounts.py). Storage otherwise holds what an employer types into the post form
  plus the scam score and review status. No analytics, no trackers, no third-party
  fonts; a third-party script only if Cloudflare Turnstile is configured. Cookies are
  login sessions, a short saved-listing cookie and the reviewer session. Outbound calls:
  SMTP mail, optional Turnstile check, and optional RDAP/DNS enrichment (OFF by default).
  The `contact` field is
  shown publicly and is optional; the form warns the poster.

  Admin auth is a single shared password read from the ADMIN_PASSWORD
  environment variable. In production (ENV=production) the app refuses to
  start without a strong ADMIN_PASSWORD, a SECRET_KEY and a CONTACT_EMAIL.
  It gates the review queue only and stores no personal data.

TRADEMARK NOTE:
  Original emblem and the garnet/gold color family only. No FSU seal or logos.
  "Nole" is evocative, not an official-affiliation claim, and "CareerShield" signals the safety focus without using FSU-protected terms like "Seminole." The footer states the
  project is independent and unaffiliated. Swap in official marks only with
  university permission.

Run locally:
  python -m uvicorn app:app --reload
Then open http://127.0.0.1:8000  (admin queue at /admin)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import json
import base64
import hashlib
import secrets
import sqlite3
import contextvars
import datetime as dt
from contextlib import closing, asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Cookie, Response, Request, HTTPException, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from scam_detector.scorer import score_posting
import accounts
import backup
import mailer
import security
from security import (
    enforce_rate_limit, login_limiter, submit_limiter, general_limiter,
    clean_text, clean_url, clean_choice, ValidationError, MAX_LEN,
    make_csrf, verify_csrf, new_session, session_valid, end_session,
    IS_PROD, ADMIN_PASSWORD, CONTACT_EMAIL, LISTING_TTL_DAYS, PURGE_REJECTED_DAYS,
    BASE_URL, user_login_limiter, user_login_email_limiter, signup_limiter, email_limiter,
)

security.validate_config()

DB_PATH = Path(os.environ.get("DB_PATH", "jobs.db"))
log = logging.getLogger("nolecareershield")


MAINTENANCE_HOURS = float(os.environ.get("MAINTENANCE_HOURS", "24"))


def daily_maintenance():
    """Purge expired data and take a database backup. Runs at startup and then every MAINTENANCE_HOURS."""
    purge_old()
    try:
        backup.run_backup(DB_PATH)
    except Exception:                      # noqa: BLE001 - a failed backup must never take the site down
        log.exception("database backup failed")


async def _maintenance_loop():
    while True:
        await asyncio.sleep(MAINTENANCE_HOURS * 3600)
        await asyncio.to_thread(daily_maintenance)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    daily_maintenance()
    task = asyncio.create_task(_maintenance_loop()) if MAINTENANCE_HOURS > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="NoleCareerShield", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

CATEGORIES = [
    "Data & Analytics", "Admin & Office", "Customer Service",
    "Marketing", "Finance & Accounting", "Operations & Warehouse", "Other",
]
WORK_TYPES = ["remote", "hybrid", "on-site"]


# ---------- database ----------

# Added after the first release; existing databases are migrated in place.
_EXTRA_COLUMNS = {"review_label": "TEXT", "ruleset_version": "TEXT", "reviewed_at": "TEXT", "employer_id": "INTEGER"}
REVIEW_REASONS = ["scam", "lead_gen", "other"]


def _ensure_columns(db):
    have = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    for col, typ in _EXTRA_COLUMNS.items():
        if col not in have:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Other',
                work_type TEXT NOT NULL,
                location TEXT,
                description TEXT NOT NULL,
                apply_url TEXT,
                contact TEXT,
                score INTEGER NOT NULL,
                band TEXT NOT NULL,
                scam_status TEXT NOT NULL,   -- from the scorer: 'clear'|'flagged'|'held'
                review_status TEXT NOT NULL, -- admin decision: 'pending'|'approved'|'rejected'
                findings_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        _ensure_columns(db)
        accounts.init_account_tables(db)
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_review ON jobs (review_status, created_at)")
        db.execute("PRAGMA journal_mode=WAL")
        db.commit()


def _cutoff(days: int) -> str:
    return (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()


def purge_old():
    """Data minimisation: rejected/removed submissions are deleted after PURGE_REJECTED_DAYS."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("DELETE FROM jobs WHERE review_status IN ('rejected','removed') AND created_at < ?",
                   (_cutoff(PURGE_REJECTED_DAYS),))
        db.commit()
        accounts.purge_expired(db)


def add_job(data: dict, employer_id: int | None = None) -> dict:
    result = score_posting(
        title=data["title"], description=data["description"], company=data["company"],
        run_network=False,
        url_chain=[data["apply_url"]] if data.get("apply_url") else None,
    )
    # The scorer's band is advisory to the admin; it does NOT auto-publish.
    scam_status = {"block": "held", "review": "flagged"}.get(result.band, "clear")
    findings = list(result.findings)
    lg = result.lead_gen or {}
    if lg.get("flag"):
        # Aggregator / lead-generation listing: not fraud, so it never raises the scam band,
        # but it does go to the reviewer with its own explanation.
        if scam_status == "clear":
            scam_status = "flagged"
        findings.append({
            "rule_id": "lead_gen", "severity": "warning", "weight": 0,
            "title": "Looks like an aggregator or lead-generation listing",
            "why": lg.get("verdict", ""),
            "matched": [r["reason"] for r in lg.get("reasons", [])][:4],
        })

    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("""
            INSERT INTO jobs (title, company, category, work_type, location,
                              description, apply_url, contact, score, band,
                              scam_status, review_status, findings_json, created_at,
                              ruleset_version, employer_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["title"], data["company"], data.get("category","Other"),
            data["work_type"], data.get("location",""), data["description"],
            data.get("apply_url",""), data.get("contact",""),
            result.score, result.band, scam_status, "pending",
            json.dumps(findings), dt.datetime.utcnow().isoformat(),
            result.ruleset_version, employer_id,
        ))
        db.commit()
        job_id = cur.lastrowid
    return {"id": job_id, "scam_status": scam_status, "score": result.score,
            "band": result.band, "findings": findings}


def query_public(search="", category="", work_type="") -> list:
    """Only APPROVED listings are ever shown publicly."""
    q = "SELECT * FROM jobs WHERE review_status = 'approved' AND created_at >= ? "
    params = [_cutoff(LISTING_TTL_DAYS)]
    if search.strip():
        q += "AND (title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\') "
        term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{term}%"; params += [like, like, like]
    if category in CATEGORIES:
        q += "AND category = ? "; params.append(category)
    if work_type in WORK_TYPES:
        q += "AND work_type = ? "; params.append(work_type)
    q += "ORDER BY created_at DESC"
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(q, params).fetchall()]


def query_live() -> list:
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT * FROM jobs WHERE review_status = 'approved' ORDER BY created_at DESC"
        ).fetchall()]


def query_pending() -> list:
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT jobs.*, u.email AS employer_email FROM jobs LEFT JOIN users u ON u.id = jobs.employer_id "
            "WHERE jobs.review_status = 'pending' ORDER BY jobs.created_at DESC"
        ).fetchall()]


def get_job(job_id: int) -> dict | None:
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def set_review(job_id: int, status: str, label: str | None = None, only_from: tuple | None = None) -> bool:
    """Record the reviewer's decision. `label` (legit|scam|lead_gen|other) is what the
    detector is later measured against, and what the export tool turns into training data.

    `only_from` limits which current states may change, so a stale browser tab cannot
    re-approve a listing someone else already rejected or removed. Returns True if a row changed."""
    sql = "UPDATE jobs SET review_status = ?, review_label = ?, reviewed_at = ? WHERE id = ?"
    params = [status, label, dt.datetime.utcnow().isoformat(), job_id]
    if only_from:
        sql += " AND review_status IN (%s)" % ",".join("?" * len(only_from))
        params += list(only_from)
    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute(sql, params)
        db.commit()
        return cur.rowcount > 0


def agreement_stats() -> dict:
    """How often the detector agreed with the human reviewers. `other` rejections
    (spam, duplicates, off-topic) are not scam decisions, so they are left out."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        rows = db.execute("SELECT scam_status, review_label FROM jobs "
                          "WHERE review_label IN ('legit','scam','lead_gen')").fetchall()
    n = len(rows)
    agree = missed = false_alarm = 0
    for scam_status, label in rows:
        flagged = scam_status in ("flagged", "held")
        bad = label in ("scam", "lead_gen")
        if flagged == bad:
            agree += 1
        elif bad:
            missed += 1
        else:
            false_alarm += 1
    return {"n": n, "agree": agree, "missed": missed, "false_alarm": false_alarm}


def public_count() -> int:
    with closing(sqlite3.connect(DB_PATH)) as db:
        return db.execute("SELECT COUNT(*) FROM jobs WHERE review_status='approved' AND created_at >= ?",
                          (_cutoff(LISTING_TTL_DAYS),)).fetchone()[0]


def pending_count() -> int:
    with closing(sqlite3.connect(DB_PATH)) as db:
        return db.execute("SELECT COUNT(*) FROM jobs WHERE review_status='pending'").fetchone()[0]


# ---------- markup ----------

def esc(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


EMBLEM = """<svg viewBox="0 0 40 40" width="34" height="34" aria-hidden="true">
<circle cx="20" cy="20" r="19" fill="var(--garnet)"/>
<path d="M20 7 L23 17 L33 20 L23 23 L20 33 L17 23 L7 20 L17 17 Z" fill="var(--gold)"/>
<circle cx="20" cy="20" r="3" fill="var(--garnet)"/>
</svg>"""

BASE_CSS = """
:root{--bg:#FAF8F4;--ink:#1C1A18;--soft:#6E6862;--line:#E6E1D8;--card:#FFF;
--garnet:#782F40;--garnet-dk:#5E2432;--gold:#CEB888;--gold-dk:#B79F6B;
--green:#2F7D5B;--amber:#B0721A;--red:#B23A2E;--green-bg:#EAF4EF;--amber-bg:#FBF2E2;--red-bg:#F8ECEA;}
*{box-sizing:border-box;margin:0}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
a{color:inherit}
.wrap{max-width:900px;margin:0 auto;padding:0 20px}
header{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.nav{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;max-width:900px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none}
.brand-name{font-family:Georgia,'Times New Roman',serif;font-weight:700;font-size:20px;color:var(--garnet);letter-spacing:-.01em}
.brand-name b{color:var(--gold-dk)}
.nav-actions{display:flex;gap:4px 8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.nav a.ghost{text-decoration:none;color:var(--soft);font-size:14px;font-weight:600;padding:9px 12px}
.nav a.btn{background:var(--garnet);color:#fff;text-decoration:none;padding:9px 16px;border-radius:7px;font-size:14px;font-weight:600}
.nav a.btn:hover{background:var(--garnet-dk)}
@media(max-width:560px){.nav{padding:12px 16px;gap:6px}.brand-name{font-size:18px}.nav a.ghost,.nav .ghostbtn{padding:8px 8px}.nav a.btn{padding:8px 12px}}
.hero{background:linear-gradient(160deg,var(--garnet) 0%,var(--garnet-dk) 100%);color:#fff;padding:56px 20px 60px;text-align:center;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 80% 20%,rgba(206,184,136,.18),transparent 55%);pointer-events:none}
.hero h1{font-family:Georgia,'Times New Roman',serif;font-weight:700;font-size:38px;line-height:1.15;letter-spacing:-.02em;max-width:16ch;margin:0 auto 14px}
.hero p{font-size:17px;color:rgba(255,255,255,.85);max-width:52ch;margin:0 auto 26px}
.hero .cta{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.hero .cta a{text-decoration:none;padding:13px 26px;border-radius:8px;font-weight:600;font-size:15px}
.cta .primary{background:var(--gold);color:var(--garnet-dk)}
.cta .primary:hover{background:#dcc99e}
.cta .secondary{background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.3)}
.cta .secondary:hover{background:rgba(255,255,255,.2)}
.hero .count{margin-top:22px;font-size:13px;color:rgba(255,255,255,.7)}
.how{background:var(--card);border-bottom:1px solid var(--line);padding:26px 20px}
.how-inner{max-width:900px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
@media(max-width:640px){.how-inner{grid-template-columns:1fr;gap:14px}}
.how-item{font-size:14px}
.how-item .n{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:var(--garnet);color:#fff;font-size:12px;font-weight:700;margin-right:8px}
.how-item b{font-weight:600}
.how-item p{color:var(--soft);font-size:13px;margin-top:4px;margin-left:32px}
.controls{margin:28px 0 8px}
.searchbar{display:flex;gap:8px;margin-bottom:16px}
.searchbar input{flex:1;border:1px solid var(--line);border-radius:8px;padding:12px 14px;font-family:inherit;font-size:15px;background:var(--card)}
.searchbar input:focus{outline:none;border-color:var(--garnet)}
.searchbar button{background:var(--garnet);color:#fff;border:none;border-radius:8px;padding:0 22px;font-weight:600;font-size:14px;cursor:pointer}
.filter-row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.filter-row .label{font-size:12px;color:var(--soft);font-weight:600;align-self:center;margin-right:4px;text-transform:uppercase;letter-spacing:.04em}
.chipf{border:1px solid var(--line);background:var(--card);color:var(--soft);padding:6px 13px;border-radius:18px;font-size:13px;text-decoration:none;font-weight:500}
.chipf.active{background:var(--garnet);color:#fff;border-color:var(--garnet)}
.results-head{font-size:13px;color:var(--soft);margin:18px 0 12px}
.job{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:12px;text-decoration:none;color:inherit;display:block;transition:border-color .15s,box-shadow .15s}
.job:hover{border-color:var(--gold);box-shadow:0 2px 10px rgba(120,47,64,.06)}
.job-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.job-title{font-weight:600;font-size:17px;color:var(--garnet)}
.job-co{color:var(--soft);font-size:14px;margin-top:2px}
.job-meta{display:flex;gap:7px;margin-top:11px;flex-wrap:wrap}
.chip{font-size:12px;padding:3px 9px;border-radius:5px;background:#F2EEE7;color:var(--soft);font-weight:500}
.badge{font-size:12px;font-weight:600;padding:4px 10px;border-radius:5px;white-space:nowrap}
.badge.verified{background:var(--green-bg);color:var(--green)}
.badge.warning{background:var(--amber-bg);color:var(--amber)}
.badge.held{background:var(--red-bg);color:var(--red)}
.empty{text-align:center;color:var(--soft);padding:56px 20px;font-size:15px;background:var(--card);border:1px solid var(--line);border-radius:10px}
h2.page{font-family:Georgia,'Times New Roman',serif;font-weight:700;font-size:28px;letter-spacing:-.02em;margin:28px 0 6px;color:var(--garnet)}
.lead{color:var(--soft);font-size:15px;margin-bottom:24px;max-width:56ch}
.form-field{margin-bottom:18px}
label{display:block;font-size:14px;font-weight:600;margin-bottom:5px}
.hint{font-size:13px;color:var(--soft);margin-bottom:7px}
input,textarea,select{width:100%;border:1px solid var(--line);border-radius:7px;padding:11px 13px;font-family:inherit;font-size:14px;background:var(--card);color:var(--ink)}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--garnet)}
textarea{min-height:150px;resize:vertical}
.submit-btn{background:var(--garnet);color:#fff;border:none;border-radius:7px;padding:13px 28px;font-size:15px;font-weight:600;cursor:pointer;font-family:inherit}
.submit-btn:hover{background:var(--garnet-dk)}
.banner{border-radius:8px;padding:14px 16px;margin-bottom:20px;font-size:14px}
.banner.verified{background:var(--green-bg);color:var(--green)}
.banner.warning{background:var(--amber-bg);color:var(--amber)}
.banner.held{background:var(--red-bg);color:var(--red)}
.banner.info{background:#EEF2F6;color:#3A4756}
.detail-desc{white-space:pre-wrap;margin:18px 0;font-size:15px;line-height:1.7}
.apply-btn{display:inline-block;background:var(--garnet);color:#fff;text-decoration:none;padding:12px 26px;border-radius:7px;font-weight:600;font-size:15px}
.apply-btn:hover{background:var(--garnet-dk)}
.finding{border-left:3px solid var(--line);padding:6px 0 6px 12px;margin:8px 0;font-size:13px}
.finding.critical{border-color:var(--red)}.finding.warning{border-color:var(--amber)}.finding.note{border-color:var(--soft)}
.finding b{font-weight:600}
.back{color:var(--soft);text-decoration:none;font-size:14px;display:inline-block;margin:24px 0 8px}
.rev-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:14px}
.rev-score{display:inline-block;font-weight:700;padding:3px 10px;border-radius:6px;font-size:13px}
.rev-score.clear{background:var(--green-bg);color:var(--green)}
.rev-score.flagged{background:var(--amber-bg);color:var(--amber)}
.rev-score.held{background:var(--red-bg);color:var(--red)}
.rev-actions{display:flex;gap:8px;margin-top:14px}
.rev-actions button{border:none;border-radius:7px;padding:9px 18px;font-weight:600;font-size:14px;cursor:pointer;font-family:inherit}
.btn-approve{background:var(--green);color:#fff}
.btn-reject{background:#eee;color:var(--red)}
footer{color:var(--soft);font-size:12px;border-top:1px solid var(--line);margin-top:52px;padding:22px;text-align:center;line-height:1.7}
footer .tm{display:block;margin-top:6px;font-size:11px;opacity:.8}
footer a{color:var(--soft)}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}
.navform{display:inline;margin:0}
.nav .ghostbtn{background:none;border:none;color:var(--soft);font:inherit;font-size:14px;font-weight:600;padding:9px 12px;cursor:pointer}
.nav .ghostbtn:hover{color:var(--garnet)}
.auth{max-width:440px;margin:36px auto 12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:30px 28px}
.auth-title{font-family:Georgia,'Times New Roman',serif;font-weight:700;font-size:28px;text-align:center;color:var(--garnet);margin-bottom:6px}
.auth-sub{text-align:center;color:var(--soft);font-size:14px;margin-bottom:18px}
.tabs{display:flex;gap:4px;background:#F2EEE7;border-radius:9px;padding:4px;margin:16px 0 22px}
.tabs a{flex:1;text-align:center;text-decoration:none;color:var(--soft);font-size:14px;font-weight:600;padding:8px 10px;border-radius:6px}
.tabs a.active{background:var(--card);color:var(--garnet);box-shadow:0 1px 3px rgba(0,0,0,.08)}
.label-row{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.forgot{font-size:14px;color:#1F5FBF;margin-bottom:5px}
.pwbox{position:relative}
.pwbox input{padding-right:64px}
.showpw{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--soft);font:inherit;font-size:14px;font-weight:600;cursor:pointer;padding:6px 8px}
.rules{list-style:none;padding:0;margin:-6px 0 16px;font-size:13px;color:var(--soft);display:grid;grid-template-columns:1fr 1fr;gap:2px 12px}
.rules li::before{content:"○ ";color:var(--soft)}
.rules li.ok{color:var(--green)}.rules li.ok::before{content:"✓ ";color:var(--green)}
.submit-btn.wide,.outline-btn{display:block;width:100%;text-align:center;text-decoration:none}
.fine{font-size:13px;color:var(--soft);text-align:center;margin-top:10px}
.or{display:flex;align-items:center;gap:12px;color:var(--soft);font-size:14px;margin:20px 0}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
.outline-btn{border:1px solid var(--line);border-radius:7px;padding:12px 16px;font-weight:600;font-size:15px;color:var(--ink);background:var(--card)}
.outline-btn:hover{border-color:var(--garnet);color:var(--garnet)}
.choose{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:8px 0 24px}
@media(max-width:640px){.choose{grid-template-columns:1fr}.auth{padding:24px 18px}}
.choose .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px}
.choose h3{font-family:Georgia,'Times New Roman',serif;color:var(--garnet);font-size:20px;margin-bottom:6px}
.choose p{color:var(--soft);font-size:14px;margin-bottom:16px}
.choose .row{display:flex;gap:8px;flex-wrap:wrap}
.choose .row a{text-decoration:none;font-size:14px;font-weight:600;padding:9px 16px;border-radius:7px}
.choose .row a.pri{background:var(--garnet);color:#fff}.choose .row a.sec{border:1px solid var(--line);color:var(--ink)}
.linkbtn{background:none;border:none;color:var(--garnet);text-decoration:underline;cursor:pointer;font:inherit;padding:0}
.inline-form{margin:0 0 14px;display:block}
.prose p{margin:0 0 14px;max-width:62ch}.prose h3{margin:26px 0 8px;font-size:16px;color:var(--garnet)}.prose ul{margin:0 0 14px 20px;max-width:62ch}
"""

# The only script the site ever runs, and only on the sign-up and log-in pages: the Show/Hide
# button on password fields and the live checklist under a new password. The page policy allows
# exactly this text by hash, so nothing else can run.
PAGE_SCRIPT = (
    "(function(){"
    "document.querySelectorAll('[data-showpw]').forEach(function(b){b.hidden=false;"
    "b.addEventListener('click',function(){var i=document.getElementById(b.getAttribute('data-showpw'));"
    "var s=i.type==='password';i.type=s?'text':'password';b.textContent=s?'Hide':'Show';"
    "b.setAttribute('aria-pressed',s?'true':'false');});});"
    "var pw=document.querySelector('[data-pwcheck]');"
    "if(pw){var R=[['len',function(v){return v.length>=8}],['upper',function(v){return /[A-Z]/.test(v)}],"
    "['num',function(v){return /[0-9]/.test(v)}],['sym',function(v){return /[!-\\/:-@\\[-`{-~]/.test(v)}]];"
    "var u=function(){R.forEach(function(r){var e=document.querySelector('[data-rule=\"'+r[0]+'\"]');"
    "if(e){e.className=r[1](pw.value)?'ok':''}})};pw.addEventListener('input',u);u();}"
    "})();"
)
PAGE_SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(PAGE_SCRIPT.encode()).digest()).decode()

_viewer: contextvars.ContextVar = contextvars.ContextVar("viewer", default=None)


def _nav_links(admin: bool) -> str:
    v = _viewer.get() or {}
    user = v.get("user")
    extra = '<a class="ghost" href="/admin">Review queue</a>' if admin else ''
    browse = '<a class="ghost" href="/jobs">Browse jobs</a>'
    if user:
        post = '<a class="btn" href="/post">Post a job</a>' if user["role"] == "employer" else ''
        out = (f'<form class="navform" method="post" action="/logout">'
               f'<input type="hidden" name="csrf" value="{make_csrf("user:" + v["token"])}">'
               f'<button class="ghostbtn" type="submit">Log out</button></form>')
        return extra + browse + out + post
    return extra + browse + '<a class="ghost" href="/login">Log in</a><a class="btn" href="/post">Post a job</a>'


def shell(body: str, title: str = "NoleCareerShield", hero: str = "", admin: bool = False, scripts: bool = False) -> str:
    nav_links = _nav_links(admin)
    tail = ""
    if scripts:
        if security.turnstile_enabled():
            tail += '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        tail += f"<script>{PAGE_SCRIPT}</script>"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{BASE_CSS}</style></head><body>
<header><div class="nav">
<a class="brand" href="/">{EMBLEM}<span class="brand-name">Nole<b>CareerShield</b></span></a>
<div class="nav-actions">{nav_links}</div>
</div></header>
{hero}
<div class="wrap">{body}</div>
<footer>Every listing is scanned for scam signals and reviewed by a human before it appears. A verified badge is not a guarantee — always confirm an employer through their own website before sharing personal information.
<span class="tm"><a href="/about">About</a> · <a href="/privacy">Privacy</a> · <a href="/report">Report a listing</a></span>
<span class="tm">An independent student project. Not affiliated with, sponsored by, or endorsed by Florida State University; uses no university trademarks or logos.</span></footer>
{tail}</body></html>"""


def _job_card(j: dict) -> str:
    badge = ('<span class="badge verified">✓ Verified</span>' if j["scam_status"]=="clear"
             else '<span class="badge warning">⚠ Check carefully</span>')
    loc = esc(j["location"]) if j["location"] else ""
    return f"""<a class="job" href="/job/{j['id']}">
<div class="job-top"><div><div class="job-title">{esc(j['title'])}</div>
<div class="job-co">{esc(j['company'])}</div></div>{badge}</div>
<div class="job-meta"><span class="chip">{esc(j['category'])}</span>
<span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}</div></a>"""


# ---------- public routes ----------

_script_src = f"'{PAGE_SCRIPT_HASH}'" + (" https://challenges.cloudflare.com" if security.turnstile_enabled() else "")
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
       f"script-src {_script_src}; "
       + ("frame-src https://challenges.cloudflare.com; " if security.turnstile_enabled() else "")
       + "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Who is logged in (if anyone), so every page can show the right buttons.
    raw = request.cookies.get("usession")
    user = None
    if raw:
        with closing(sqlite3.connect(DB_PATH)) as db:
            user = accounts.session_user(db, raw)
    request.state.user = user
    request.state.utoken = raw if user else None
    marker = _viewer.set({"user": user, "token": raw if user else None})
    try:
        response = await call_next(request)
    finally:
        _viewer.reset(marker)
    h = response.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if IS_PROD:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/admin"):
        h["Cache-Control"] = "no-store"
        h["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("SELECT 1").fetchone()
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /admin\nDisallow: /post\n"


_ERROR_TEXT = {
    404: ("Page not found", "That page doesn't exist. It may have been removed, or the link may have a typo."),
    405: ("That link can't be opened directly", "This address only works when it is used from a button on the site."),
}


@app.exception_handler(StarletteHTTPException)
def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Starlette's exception class is the parent of FastAPI's, so this also catches
    # unknown URLs (404) and wrong-method requests (405), which would otherwise
    # come back as raw JSON.
    if exc.status_code == 429:
        body = f"""<h2 class="page">Slow down</h2>
<div class="banner warning">{esc(str(exc.detail))}</div>
<a class="back" href="/">← Home</a>"""
        return HTMLResponse(shell(body, title="Too many requests"),
                             status_code=429, headers=exc.headers or {})
    # Everything else: a plain, safe fallback (no stack traces, no internals).
    heading, note = _ERROR_TEXT.get(exc.status_code, (f"Error {exc.status_code}", ""))
    note_html = f'<p class="lead">{esc(note)}</p>' if note else ""
    return HTMLResponse(
        shell(f'<h2 class="page">{esc(heading)}</h2>{note_html}<a class="back" href="/">← Home</a>', title=heading),
        status_code=exc.status_code, headers=exc.headers or {},
    )


@app.exception_handler(RequestValidationError)
def _validation_handler(request: Request, exc: RequestValidationError):
    # A malformed URL parameter or a form missing fields: friendly page, no internals echoed.
    body = ('<h2 class="page">That request wasn\'t valid</h2>'
            '<p class="lead">Something in the link or form was missing or malformed. Please go back and try again.</p>'
            '<a class="back" href="/">← Home</a>')
    return HTMLResponse(shell(body, title="Invalid request"), status_code=400)


@app.get("/", response_class=HTMLResponse)
def landing():
    n = public_count()
    count_line = f"{n} approved listing{'s' if n != 1 else ''} live right now" if n else "Approved listings will appear here"
    hero = f"""<section class="hero">
<h1>Student jobs, checked for scams before you see them</h1>
<p>A curated job board for FSU students. Every listing is scam-scanned and reviewed by a human before it goes live — only vetted postings make it to the feed.</p>
<div class="cta"><a class="primary" href="/jobs">Browse jobs</a><a class="secondary" href="/post">Post a job</a></div>
<div class="count">{count_line}</div>
</section>
<section class="how"><div class="how-inner">
<div class="how-item"><b><span class="n">1</span>Employers submit</b><p>Anyone can submit a listing — but submitting isn't publishing.</p></div>
<div class="how-item"><b><span class="n">2</span>Scanned &amp; reviewed</b><p>The scam scanner scores it, then a human approves or rejects it.</p></div>
<div class="how-item"><b><span class="n">3</span>Students browse safely</b><p>Only approved listings appear, each with its verdict shown.</p></div>
</div></section>"""
    jobs = query_public()[:3]
    if jobs:
        cards = "".join(_job_card(j) for j in jobs)
        body = f'<div class="results-head">Latest approved listings</div>{cards}<p style="margin:16px 0 40px"><a href="/jobs" style="color:var(--garnet);font-weight:600;text-decoration:none">See all jobs →</a></p>'
    else:
        body = '<div class="empty" style="margin:32px 0 48px">No approved listings yet. <a href="/post" style="color:var(--garnet);font-weight:600">Submit the first one.</a></div>'
    return shell(body, hero=hero)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_feed(request: Request, search: str = "", category: str = "", work_type: str = ""):
    enforce_rate_limit(request, general_limiter, "jobs_feed")
    # Query params are attacker-controlled input same as form fields --
    # oversized or malformed values get clipped/rejected here too.
    search = search.strip()[:200]
    category = clean_choice(category, CATEGORIES, "category", default="") if category else ""
    work_type = clean_choice(work_type, WORK_TYPES, "work_type", default="") if work_type else ""
    jobs = query_public(search=search, category=category, work_type=work_type)

    def chip(name, val, cur, param):
        qs = {}
        if search: qs["search"] = search
        if param != "category" and category: qs["category"] = category
        if param != "work_type" and work_type: qs["work_type"] = work_type
        if val: qs[param] = val
        href = "/jobs" + ("?" + urlencode(qs) if qs else "")
        return f'<a class="chipf {"active" if cur==val else ""}" href="{esc(href)}">{esc(name)}</a>'

    cat_chips = chip("All","",category,"category") + "".join(chip(c,c,category,"category") for c in CATEGORIES)
    wt_chips = chip("Any","",work_type,"work_type") + "".join(chip(w.title(),w,work_type,"work_type") for w in WORK_TYPES)

    controls = f"""<div class="controls">
<form class="searchbar" method="get" action="/jobs">
<input name="search" value="{esc(search)}" placeholder="Search title, company, or keyword">
{f'<input type="hidden" name="category" value="{esc(category)}">' if category else ''}
{f'<input type="hidden" name="work_type" value="{esc(work_type)}">' if work_type else ''}
<button type="submit">Search</button></form>
<div class="filter-row"><span class="label">Category</span>{cat_chips}</div>
<div class="filter-row"><span class="label">Type</span>{wt_chips}</div></div>"""

    if jobs:
        head = f'<div class="results-head">{len(jobs)} listing{"s" if len(jobs)!=1 else ""}' + (f' for "{esc(search)}"' if search else "") + '</div>'
        body = controls + head + "".join(_job_card(j) for j in jobs)
    else:
        body = controls + '<div class="empty">No listings match. Try clearing filters or a different search.</div>'
    return shell(body, title="Browse jobs — NoleCareerShield")


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request):
    enforce_rate_limit(request, general_limiter, "job_detail")
    j = get_job(job_id)
    if not j or j["review_status"] != "approved":
        return HTMLResponse(shell('<p class="empty" style="margin:40px 0">That listing isn\'t available.</p>'), status_code=404)

    if j["scam_status"] == "clear":
        banner = '<div class="banner verified">✓ This listing passed the scam check and was approved by a reviewer. Still verify the employer through their own website before sharing personal information.</div>'
    else:
        banner = '<div class="banner warning">⚠ This listing was approved but tripped some scam signals. Read the notes below and verify the employer independently before responding.</div>'

    findings = json.loads(j["findings_json"] or "[]")
    findings_html = ""
    if j["scam_status"] != "clear" and findings:
        items = "".join(
            f'<div class="finding {f["severity"]}"><b>{esc(f["title"])}</b><br>{esc(f["why"])}</div>'
            for f in findings if f["severity"] in ("critical","warning"))
        findings_html = f'<div style="margin:20px 0"><b style="font-size:14px">Signals to be aware of:</b>{items}</div>'

    apply = ""
    viewer = getattr(request.state, "user", None)
    if not (viewer and viewer["role"] == "student"):
        # How to apply is shown to signed-in FSU students only. Anyone can still read the listing.
        apply = (f'<a class="apply-btn" href="/login/student?next=/job/{int(j["id"])}">Log in as an FSU student to apply</a>'
                 '<p class="fine" style="text-align:left">Free, and only for @fsu.edu addresses. '
                 'Employers know their listing is only shown to students.</p>')
    elif j["apply_url"]:
        apply = f'<a class="apply-btn" href="{esc(j["apply_url"])}" target="_blank" rel="noopener noreferrer nofollow ugc">Apply →</a>'
    elif j["contact"]:
        apply = f'<p style="font-size:14px;color:var(--soft)">Contact: {esc(j["contact"])}</p>'

    loc = esc(j["location"]) if j["location"] else ""
    body = f"""<a class="back" href="/jobs">← All jobs</a>
{banner}
<h2 class="page" style="margin-top:8px">{esc(j['title'])}</h2>
<p class="job-co" style="font-size:16px">{esc(j['company'])}</p>
<div class="job-meta" style="margin:14px 0"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}</div>
{findings_html}<div class="detail-desc">{esc(j['description'])}</div>{apply}"""
    return shell(body, title=esc(j["title"]) + " — NoleCareerShield")


def _post_form_page(values: dict | None = None, error: str = "", status: int = 200) -> HTMLResponse:
    """The submit form. On a rejected submission it is shown again with everything the
    poster typed still in place and the reason at the top, so nobody retypes a long posting."""
    v = values or {}

    def val(name):
        return esc(v.get(name, ""))

    cat_opts = "".join(f'<option value="{esc(c)}"{" selected" if v.get("category") == c else ""}>{esc(c)}</option>' for c in CATEGORIES)
    wt_opts = "".join(f'<option value="{esc(w)}"{" selected" if v.get("work_type") == w else ""}>{esc(w.title())}</option>' for w in WORK_TYPES)
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    who = (_viewer.get() or {}).get("user")
    if who and who["role"] == "employer":
        under = f'<p class="fine" style="text-align:left">Sending as {esc(who["email"])}.</p>'
    else:
        under = '<p class="fine" style="text-align:left">You\'ll log in or sign up before it sends.</p>'
    body = f"""<a class="back" href="/">← Home</a>
<h2 class="page">Submit a job</h2>
<p class="lead">Submitting isn't publishing. Every listing is scam-scanned and then reviewed by a human before it appears — only vetted postings go live.</p>
{err}<form method="post" action="/post">
<input type="hidden" name="csrf" value="{make_csrf('form')}">
<div class="hp" aria-hidden="true"><label for="f-website">Leave this empty</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="form-field"><label for="f-title">Job title</label><input id="f-title" name="title" required maxlength="200" placeholder="e.g. Marketing Data Analyst" value="{val('title')}"></div>
<div class="form-field"><label for="f-company">Company</label><input id="f-company" name="company" required maxlength="200" placeholder="e.g. Leaf Home" value="{val('company')}"></div>
<div class="form-field"><label for="f-category">Category</label><select id="f-category" name="category">{cat_opts}</select></div>
<div class="form-field"><label for="f-work_type">Work type</label><select id="f-work_type" name="work_type">{wt_opts}</select></div>
<div class="form-field"><label for="f-location">Location</label><p class="hint">City/state, or leave blank if fully remote.</p><input id="f-location" name="location" maxlength="120" placeholder="e.g. Tallahassee, FL" value="{val('location')}"></div>
<div class="form-field"><label for="f-description">Description</label><p class="hint">The full posting — responsibilities, requirements, and pay if you can share it.</p><textarea id="f-description" name="description" required maxlength="8000">{val('description')}</textarea></div>
<div class="form-field"><label for="f-apply_url">Apply URL</label><p class="hint">Where applicants should go. The scanner checks this link too.</p><input id="f-apply_url" name="apply_url" maxlength="2000" placeholder="https://..." value="{val('apply_url')}"></div>
<div class="form-field"><label for="f-contact">Contact (optional)</label><p class="hint">Shown publicly if approved. Use a role or company address, not a personal one.</p><input id="f-contact" name="contact" maxlength="200" placeholder="careers@company.com" value="{val('contact')}"></div>
<button class="submit-btn" type="submit">Submit for review</button>{under}</form>"""
    return HTMLResponse(shell(body, title="Submit a job — NoleCareerShield"), status_code=status)


@app.get("/post", response_class=HTMLResponse)
def post_form():
    return _post_form_page()


def _clean_listing(f: dict) -> dict:
    """Validate the fields of a listing. Raises ValidationError with a message fit to show the poster."""
    return {
        "title": clean_text(f.get("title", ""), "title"),
        "company": clean_text(f.get("company", ""), "company"),
        "category": clean_choice(f.get("category", ""), CATEGORIES, "category", default="Other"),
        "work_type": clean_choice(f.get("work_type", ""), WORK_TYPES, "work_type"),
        "location": clean_text(f.get("location", ""), "location", required=False),
        "description": clean_text(f.get("description", ""), "description"),
        "apply_url": clean_url(f.get("apply_url", "")),
        "contact": clean_text(f.get("contact", ""), "contact", required=False),
    }


_SUBMITTED_BODY = """<h2 class="page">Submitted for review</h2>
<div class="banner info">Thanks, your listing has been submitted. It has been scanned and is now waiting for a human reviewer to approve it before it appears on the board. Nothing is published automatically. We also sent a confirmation to your email.</div>
<a class="apply-btn" href="/">Back to home</a>"""


@app.get("/submitted", response_class=HTMLResponse)
def submitted():
    return HTMLResponse(shell(_SUBMITTED_BODY, title="Submitted for review — NoleCareerShield"))


@app.post("/post", response_class=HTMLResponse)
def post_submit(
    request: Request, background: BackgroundTasks,
    title: str = Form(...), company: str = Form(...), category: str = Form("Other"),
    work_type: str = Form(...), location: str = Form(""), description: str = Form(...),
    apply_url: str = Form(""), contact: str = Form(""),
    csrf: str = Form(""), website: str = Form(""),
):
    enforce_rate_limit(request, submit_limiter, "post_submit")
    typed = {"title": title, "company": company, "category": category, "work_type": work_type,
             "location": location, "description": description, "apply_url": apply_url, "contact": contact}
    if not verify_csrf(csrf, "form"):
        return _post_form_page(typed, "That form had been open too long. Nothing was lost: your text is still here. "
                                      "Press Submit again to send it.", status=400)
    if website:
        # Honeypot filled: a bot. Show the normal confirmation, store nothing.
        return HTMLResponse(shell('<h2 class="page">Submitted for review</h2><div class="banner info">Thanks, your listing has been submitted.</div>'))

    try:
        clean = _clean_listing(typed)
    except ValidationError as e:
        return _post_form_page(typed, str(e), status=400)

    user = getattr(request.state, "user", None)
    if not user or user["role"] != "employer":
        # Not logged in as an employer: keep the listing safe for a few days, send them to log in
        # or sign up, and submit it for them the moment they are through.
        with closing(sqlite3.connect(DB_PATH)) as db:
            token = accounts.save_draft(db, clean)
        resp = RedirectResponse("/login/employer?next=/post", status_code=303)
        resp.set_cookie("draft", token, httponly=True, samesite="lax", secure=IS_PROD,
                        max_age=accounts.DRAFT_TTL, path="/")
        return resp

    add_job(clean, employer_id=user["id"])
    background.add_task(_mail_listing_received, user["email"], clean["title"])
    # Same confirmation regardless of scam score: the submitter is not told the internal verdict
    # (that is for the reviewer), only that it is in review.
    return HTMLResponse(shell(_SUBMITTED_BODY))


# ---------- trust pages ----------

def _contact_line() -> str:
    return (f'<a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a>' if CONTACT_EMAIL
            else "the site operator")


@app.get("/about", response_class=HTMLResponse)
def about():
    body = """<a class="back" href="/">← Home</a><h2 class="page">About NoleCareerShield</h2>
<div class="prose"><p>Students get targeted by fake job offers constantly: check-cashing schemes, money-mule
"recruiters", and pay-to-work training programs. NoleCareerShield is a job board built around one question:
<b>is this listing safe to respond to?</b></p>
<h3>How a listing gets on the board</h3>
<ul><li>Every submission is scored by an open, rule-based scam detector. Each rule that fires is explained in plain language, so the score is never a black box.</li>
<li>Every submission then waits for a human reviewer. Nothing is published automatically, no matter how clean the score.</li>
<li>Approved listings show their verdict. Listings that tripped signals are labeled and explain why.</li>
<li>Listings expire automatically, and any listing can be removed at any time.</li></ul>
<h3>What this is not</h3>
<p>A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information. This is an independent student project and is not affiliated with Florida State University.</p></div>"""
    return shell(body, title="About — NoleCareerShield")


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    bot = ("<li>The sign-up and log-in pages load a bot check from Cloudflare (Turnstile), which sees your IP address and browser details.</li>"
           if security.turnstile_enabled() else "")
    body = f"""<a class="back" href="/">← Home</a><h2 class="page">Privacy</h2>
<div class="prose"><p>Short version: browsing is anonymous. Accounts hold an email address and a password, and nothing else.</p>
<h3>Anyone browsing</h3>
<ul><li>You can read every approved listing without an account. No cookies are set for browsing or searching.</li>
<li>No analytics, advertising, trackers, resumes or messaging. Pages load only from this site, with no third-party fonts.</li></ul>
<h3>Students</h3>
<ul><li>A student account needs an @fsu.edu email address, confirmed by a link we send, and a password. It is used to show you how to apply to a listing.</li>
<li>We store the email address, a salted hash of the password (never the password itself) and when you confirmed. No name, no student ID, no grades, no resume, and no record of which listings you open or apply to.</li>
<li>Accounts that never confirm their email are deleted after 7 days. To delete your account, contact {_contact_line()}.</li></ul>
<h3>People who post a job</h3>
<ul><li>You need an employer account: an email address (confirmed by a link) and a password, stored the same way as above.</li>
<li>We store exactly what you type into the form (title, company, description, location, apply link, optional contact), the account that sent it, the automated scam score and the review decision.</li>
<li>The contact field is shown publicly if the listing is approved. Use a role or company address.</li>
<li>Rejected and removed submissions are deleted automatically after {PURGE_REJECTED_DAYS} days. Approved listings stop showing after {LISTING_TTL_DAYS} days.</li>
<li>If you fill in the form before logging in, the listing is kept for up to 3 days so it can be sent when you finish, then deleted.</li></ul>
<h3>Cookies and logs</h3>
<ul><li>Logging in sets one session cookie (HttpOnly, 7 days). Sending a listing before you log in sets a short-lived cookie that holds only a random reference to your saved listing.</li>
{bot}<li>Server logs may briefly hold IP addresses for security and abuse prevention. IP addresses are also held in memory, temporarily, to enforce rate limits.</li>
<li>We send email only for account confirmation, password reset and a receipt when you submit a listing. No marketing.</li></ul>
<h3>Reviewers</h3>
<p>The review queue uses a separate session cookie, set only after a reviewer signs in, marked HttpOnly and expired after 8 hours.</p></div>"""
    return shell(body, title="Privacy — NoleCareerShield")


@app.get("/report", response_class=HTMLResponse)
def report():
    body = f"""<a class="back" href="/">← Home</a><h2 class="page">Report a listing</h2>
<div class="prose"><p>See something that looks like a scam, or a listing that should be taken down? Email {_contact_line()}
with the listing title and company. Reports are reviewed by a person, and listings that look fraudulent are removed.</p>
<p>If you already sent money or personal information to a suspicious employer, contact your bank, and report it to the
FTC at reportfraud.ftc.gov.</p></div>"""
    return shell(body, title="Report a listing — NoleCareerShield")


# ---------- accounts: sign-up, log-in, email confirmation, password reset ----------

def _role(role: str) -> str:
    if role not in accounts.ROLES:
        raise HTTPException(status_code=404)
    return role


def _turnstile_widget() -> str:
    if not security.turnstile_enabled():
        return ""
    return f'<div class="cf-turnstile" data-sitekey="{esc(security.TURNSTILE_SITE_KEY)}" style="margin-bottom:14px"></div>'


def _auth_page(heading: str, body: str, *, title: str | None = None, status: int = 200, sub: str = "") -> HTMLResponse:
    inner = f'<div class="auth"><h2 class="auth-title">{heading}</h2>{sub}{body}</div>'
    return HTMLResponse(shell(inner, title=(title or heading) + " — NoleCareerShield", scripts=True), status_code=status)


def _tabs(active: str, kind: str, next_: str = "") -> str:
    q = f"?next={esc(next_)}" if next_ else ""
    return ('<div class="tabs">' + "".join(
        f'<a href="/{kind}/{r}{q}"{" class=active" if r == active else ""}>{lbl}</a>'
        for r, lbl in (("student", "Student"), ("employer", "Employer"))) + "</div>")


def _pw_field(fid: str = "f-password", name: str = "password", label: str = "Password",
              forgot_role: str = "", autocomplete: str = "current-password", check: bool = False) -> str:
    forgot = f'<a class="forgot" href="/forgot/{forgot_role}">Forgot password?</a>' if forgot_role else ""
    return (f'<div class="form-field"><div class="label-row"><label for="{fid}">{label}</label>{forgot}</div>'
            f'<div class="pwbox"><input id="{fid}" type="password" name="{name}" required maxlength="128" '
            f'autocomplete="{autocomplete}"{" data-pwcheck" if check else ""}>'
            f'<button type="button" class="showpw" data-showpw="{fid}" hidden>Show</button></div></div>')


_RULES_LIST = ('<ul class="rules" aria-label="Password requirements"><li data-rule="len">8+ characters</li>'
               '<li data-rule="upper">A capital letter</li><li data-rule="num">A number</li>'
               '<li data-rule="sym">A symbol (! ? # $ %)</li></ul>')


def _safe_next(value: str) -> str:
    """Only a few fixed on-site destinations are allowed, so a link can never bounce someone to another site."""
    value = (value or "").strip()
    return value if re.fullmatch(r"/job/\d{1,9}|/post|/jobs", value) else ""


def _has_draft(request: Request) -> bool:
    return bool(request.cookies.get("draft"))


def _email_ok(limiter, key: str) -> bool:
    """One shared allowance per address; True while under the cap."""
    allowed, _ = limiter.check(key)
    if allowed:
        limiter.hit(key)
    return allowed


def _csrf_input() -> str:
    return f'<input type="hidden" name="csrf" value="{make_csrf("form")}">'


def _link(path: str, token: str) -> str:
    return f"{BASE_URL}{path}?token={token}"


def _mail_verify(email: str, role: str, token: str) -> None:
    who = "student" if role == "student" else "employer"
    mailer.send(email, "Confirm your NoleCareerShield account",
                f"Confirm your email to finish creating your {who} account:\n\n{_link('/verify', token)}\n\n"
                "The link works for 24 hours. If you did not sign up, ignore this email and nothing will happen.\n\n"
                "NoleCareerShield is an independent student project and is not affiliated with Florida State University.")


def _mail_already(email: str, role: str) -> None:
    mailer.send(email, "You already have a NoleCareerShield account",
                f"Someone (hopefully you) tried to create a {role} account with this address, but one already exists.\n\n"
                f"Log in: {BASE_URL}/login/{role}\nForgot your password: {BASE_URL}/forgot/{role}\n\n"
                "If this wasn't you, you can ignore this email.")


def _mail_reset(email: str, token: str) -> None:
    mailer.send(email, "Reset your NoleCareerShield password",
                f"Choose a new password:\n\n{_link('/reset', token)}\n\n"
                "The link works for one hour and can be used once. If you did not ask for this, ignore this email; "
                "your password has not changed.")


def _mail_listing_received(email: str, title: str) -> None:
    mailer.send(email, "We received your listing",
                f'We received your listing "{title}". It has been scanned, and a person reviews every listing before '
                "it appears on the board. Nothing is published before that.\n\nNoleCareerShield")


def _login_cookie(resp, token: str):
    resp.set_cookie("usession", token, httponly=True, samesite="lax", secure=IS_PROD,
                    max_age=accounts.SESSION_TTL, path="/")
    return resp


def _clear_draft_cookie(resp):
    resp.delete_cookie("draft", path="/")
    return resp


def _resume_draft(request: Request, user: dict, background: BackgroundTasks) -> bool:
    """If this browser typed a listing before logging in, send it now. Returns True if a listing was submitted."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        data = accounts.take_draft(db, request.cookies.get("draft"))
    if not data or user["role"] != "employer":
        return False
    try:
        clean = _clean_listing(data)
    except ValidationError:
        return False
    add_job(clean, employer_id=user["id"])
    background.add_task(_mail_listing_received, user["email"], clean["title"])
    return True


# --- pick a side ---

@app.get("/login", response_class=HTMLResponse)
def login_choose(request: Request):
    body = """<h2 class="page">Log in</h2><p class="lead">Pick the kind of account you have.</p>
<div class="choose">
<div class="card"><h3>I'm a student</h3><p>Log in with your @fsu.edu email to see how to apply to a listing.</p>
<div class="row"><a class="pri" href="/login/student">Log in</a><a class="sec" href="/signup/student">Sign up</a></div></div>
<div class="card"><h3>I'm an employer</h3><p>Log in to send a listing for review, or create an account to post your first one.</p>
<div class="row"><a class="pri" href="/login/employer">Log in</a><a class="sec" href="/signup/employer">Sign up</a></div></div></div>"""
    return HTMLResponse(shell(body, title="Log in — NoleCareerShield"))


# --- log in ---

def _login_page(role: str, email: str = "", error: str = "", notice: str = "", next_: str = "",
                unverified: bool = False, status: int = 200) -> HTMLResponse:
    note = f'<div class="banner info">{esc(notice)}</div>' if notice else ""
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    resend = ""
    if unverified:
        resend = (f'<form method="post" action="/resend/{role}" class="inline-form">{_csrf_input()}'
                  f'<input type="hidden" name="email" value="{esc(email)}">'
                  '<button class="linkbtn" type="submit">Send me a new confirmation email</button></form>')
    ph = "you@fsu.edu" if role == "student" else "you@company.com"
    a_an = "a student" if role == "student" else "an employer"
    body = f"""{_tabs(role, "login", next_)}{note}{err}{resend}
<form method="post" action="/login/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required maxlength="254" autocomplete="username" placeholder="{ph}" value="{esc(email)}"></div>
{_pw_field(forgot_role=role)}
{_turnstile_widget()}<button class="submit-btn wide" type="submit">Log in</button></form>
<div class="or"><span>Or</span></div><a class="outline-btn" href="/signup/{role}{"?next=" + esc(next_) if next_ else ""}">Create {a_an} account</a>"""
    return _auth_page("Log in", body, status=status)


@app.get("/login/{role}", response_class=HTMLResponse)
def login_form(role: str, request: Request, next: str = ""):
    _role(role)
    nx = _safe_next(next)
    notice = ""
    if role == "employer" and nx == "/post" and _has_draft(request):
        notice = "Almost done. Log in or create an employer account and your listing is sent for review automatically."
    elif role == "student" and nx.startswith("/job/"):
        notice = "Log in with your FSU student account to see how to apply."
    return _login_page(role, next_=nx, notice=notice)


@app.post("/login/{role}")
def login_submit(role: str, request: Request, background: BackgroundTasks, email: str = Form(""),
                 password: str = Form(""), csrf: str = Form(""), next: str = Form(""),
                 cf_token: str = Form("", alias="cf-turnstile-response")):
    _role(role)
    enforce_rate_limit(request, user_login_limiter, "user_login")
    nx = _safe_next(next)
    if not verify_csrf(csrf, "form"):
        return _login_page(role, email=email[:254], next_=nx, status=400,
                           error="That page had been open too long. Please try again.")
    if not security.verify_turnstile(cf_token, security.client_ip(request)):
        return _login_page(role, email=email[:254], next_=nx, status=400,
                           error="The bot check did not pass. Please try again.")
    generic = "The email or password is incorrect."
    try:
        addr = accounts.normalize_email(email)
    except ValueError:
        return _login_page(role, email=email[:254], next_=nx, status=401, error=generic)
    if not _email_ok(user_login_email_limiter, f"login:{role}:{addr}"):
        raise HTTPException(status_code=429, detail="Too many attempts for this account. Try again in a few minutes.",
                            headers={"Retry-After": "600"})
    with closing(sqlite3.connect(DB_PATH)) as db:
        user = accounts.get_user(db, addr, role)
    good = accounts.verify_password(password[:accounts.PW_MAX], user["pw_hash"] if user else accounts.DUMMY_HASH)
    if not (user and good):
        return _login_page(role, email=addr, next_=nx, status=401, error=generic)
    if not user["verified"]:
        return _login_page(role, email=addr, next_=nx, status=403, unverified=True,
                           error="Confirm your email first. We sent you a link when you signed up.")
    with closing(sqlite3.connect(DB_PATH)) as db:
        token = accounts.create_session(db, user["id"])
    if _resume_draft(request, user, background):
        resp = RedirectResponse("/submitted", status_code=303)
        _clear_draft_cookie(resp)
    else:
        resp = RedirectResponse(nx or "/", status_code=303)
    return _login_cookie(resp, token)


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    raw = request.cookies.get("usession")
    resp = RedirectResponse("/", status_code=303)
    if raw and verify_csrf(csrf, "user:" + raw):
        with closing(sqlite3.connect(DB_PATH)) as db:
            accounts.end_session(db, raw)
        resp.delete_cookie("usession", path="/")
    # A request without the right token changes nothing, so another site cannot log someone out.
    return resp


# --- sign up ---

def _signup_page(role: str, email: str = "", error: str = "", next_: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    if role == "student":
        sub = '<p class="auth-sub">Use your @fsu.edu email. We send a link to confirm it.</p>'
        ph = "you@fsu.edu"
    else:
        sub = '<p class="auth-sub">Any email works. We send a link to confirm it before you can post.</p>'
        ph = "you@company.com"
    body = f"""{_tabs(role, "signup", next_)}{err}
<form method="post" action="/signup/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="hp" aria-hidden="true"><label for="f-website">Leave this empty</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required maxlength="254" autocomplete="username" placeholder="{ph}" value="{esc(email)}"></div>
{_pw_field(autocomplete="new-password", check=True)}{_RULES_LIST}
{_pw_field(fid="f-password2", name="password2", label="Confirm password", autocomplete="new-password")}
{_turnstile_widget()}<button class="submit-btn wide" type="submit">Create account</button></form>
<div class="or"><span>Or</span></div><a class="outline-btn" href="/login/{role}{"?next=" + esc(next_) if next_ else ""}">I already have an account</a>"""
    return _auth_page("Sign up", body, sub=sub, status=status)


@app.get("/signup/{role}", response_class=HTMLResponse)
def signup_form(role: str, next: str = ""):
    return _signup_page(_role(role), next_=_safe_next(next))


def _check_your_email(email: str, role: str) -> HTMLResponse:
    body = (f'<div class="banner info">If that address can receive an account, we just sent a confirmation link to '
            f'<b>{esc(email)}</b>. It works for 24 hours. Check your spam folder if it does not arrive in a few minutes.</div>'
            f'<p class="fine">Wrong address? <a href="/signup/{role}">Start over</a>.</p>')
    return _auth_page("Check your email", body, title="Check your email")


@app.post("/signup/{role}")
def signup_submit(role: str, request: Request, background: BackgroundTasks, email: str = Form(""),
                  password: str = Form(""), password2: str = Form(""), csrf: str = Form(""),
                  next: str = Form(""), website: str = Form(""),
                  cf_token: str = Form("", alias="cf-turnstile-response")):
    _role(role)
    enforce_rate_limit(request, signup_limiter, "signup")
    nx = _safe_next(next)
    shown = email.strip()[:254]
    if not verify_csrf(csrf, "form"):
        return _signup_page(role, shown, "That page had been open too long. Please try again.", nx, 400)
    if website:
        return _check_your_email(shown, role)          # honeypot: look normal, do nothing
    if not security.verify_turnstile(cf_token, security.client_ip(request)):
        return _signup_page(role, shown, "The bot check did not pass. Please try again.", nx, 400)
    try:
        addr = accounts.normalize_email(email)
    except ValueError as e:
        return _signup_page(role, shown, str(e), nx, 400)
    if role == "student" and not accounts.is_fsu_email(addr):
        return _signup_page(role, shown, "Student accounts need an @fsu.edu email address.", nx, 400)
    problems = accounts.password_problems(password, addr)
    if problems:
        return _signup_page(role, addr, accounts.requirement_text(problems), nx, 400)
    if password != password2:
        return _signup_page(role, addr, "The two passwords do not match.", nx, 400)

    # The response is the same whether or not the address already has an account,
    # so this form cannot be used to find out who is registered.
    if _email_ok(email_limiter, f"mail:{addr}"):
        with closing(sqlite3.connect(DB_PATH)) as db:
            uid = accounts.create_user(db, addr, role, password)
            if uid:
                token = accounts.issue_token(db, uid, "verify", accounts.VERIFY_TTL)
                background.add_task(_mail_verify, addr, role, token)
            else:
                existing = accounts.get_user(db, addr, role)
                if existing and not existing["verified"]:
                    accounts.restart_unverified(db, existing["id"], password)
                    token = accounts.issue_token(db, existing["id"], "verify", accounts.VERIFY_TTL)
                    background.add_task(_mail_verify, addr, role, token)
                else:
                    background.add_task(_mail_already, addr, role)
    return _check_your_email(addr, role)


@app.post("/resend/{role}")
def resend_confirmation(role: str, request: Request, background: BackgroundTasks, email: str = Form(""), csrf: str = Form("")):
    _role(role)
    enforce_rate_limit(request, signup_limiter, "resend")
    if verify_csrf(csrf, "form"):
        try:
            addr = accounts.normalize_email(email)
        except ValueError:
            addr = ""
        if addr and _email_ok(email_limiter, f"mail:{addr}"):
            with closing(sqlite3.connect(DB_PATH)) as db:
                user = accounts.get_user(db, addr, role)
                if user and not user["verified"]:
                    token = accounts.issue_token(db, user["id"], "verify", accounts.VERIFY_TTL)
                    background.add_task(_mail_verify, addr, role, token)
    body = ('<div class="banner info">If that address has an account waiting for confirmation, we sent a new link. '
            'It works for 24 hours.</div>')
    return _auth_page("Check your email", body, title="Check your email")


# --- confirm email ---

def _link_problem(kind: str) -> HTMLResponse:
    body = (f'<div class="banner warning">That link has expired or was already used.</div>'
            f'<p class="fine"><a href="/login">Log in</a> to ask for a new {kind}.</p>')
    return _auth_page("Link not valid", body, status=400)


@app.get("/verify", response_class=HTMLResponse)
def verify_page(token: str = ""):
    # Opening the link only shows a button. Confirming needs a click, so mail scanners that
    # pre-open links cannot confirm an address on someone's behalf.
    with closing(sqlite3.connect(DB_PATH)) as db:
        ok = accounts.peek_token(db, token, "verify")
    if not ok:
        return _link_problem("confirmation email")
    return _confirm_page(token)


def _confirm_page(token: str, error: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    body = (f'<p class="auth-sub">Enter the password you chose when you signed up. This makes sure the account is really yours.</p>{err}'
            f'<form method="post" action="/verify">{_csrf_input()}<input type="hidden" name="token" value="{esc(token)}">'
            f'{_pw_field(label="Password")}'
            '<button class="submit-btn wide" type="submit">Confirm my email</button></form>'
            '<p class="fine">Don\'t remember it? Sign up again with the same email to set a new one.</p>')
    return _auth_page("Confirm your email", body, status=status)


@app.post("/verify")
def verify_submit(request: Request, background: BackgroundTasks, token: str = Form(""),
                  password: str = Form(""), csrf: str = Form("")):
    enforce_rate_limit(request, user_login_limiter, "verify")
    if not verify_csrf(csrf, "form"):
        return _link_problem("confirmation email")
    with closing(sqlite3.connect(DB_PATH)) as db:
        peeked = accounts.peek_token(db, token, "verify")
        owner = accounts.get_user_by_id(db, peeked) if peeked else None
    if not owner:
        return _link_problem("confirmation email")
    if not _email_ok(user_login_email_limiter, f"login:{owner['role']}:{owner['email']}"):
        raise HTTPException(status_code=429, detail="Too many attempts for this account. Try again in a few minutes.",
                            headers={"Retry-After": "600"})
    if not accounts.verify_password(password[:accounts.PW_MAX], owner["pw_hash"]):
        return _confirm_page(token, "That is not the password this account was created with.", 401)
    with closing(sqlite3.connect(DB_PATH)) as db:
        uid = accounts.consume_token(db, token, "verify")
        if not uid:
            return _link_problem("confirmation email")
        accounts.mark_verified(db, uid)
        user = accounts.get_user_by_id(db, uid)
        session = accounts.create_session(db, uid)
    sent = _resume_draft(request, user, background)
    if user["role"] == "employer":
        msg = ("Your listing was sent for review. A person checks every listing before it appears." if sent
               else "You can post a job now.")
        cta = '<a class="apply-btn" href="/">Back to home</a>' if sent else '<a class="apply-btn" href="/post">Post a job</a>'
    else:
        msg = "You can now log in to see how to apply to any listing."
        cta = '<a class="apply-btn" href="/jobs">Browse jobs</a>'
    body = f'<div class="banner verified">Email confirmed. You are logged in. {esc(msg)}</div>{cta}'
    _viewer.set({"user": user, "token": session})       # this response is the first page they see logged in
    resp = _auth_page("You're in", body, title="Email confirmed")
    if sent:
        _clear_draft_cookie(resp)
    return _login_cookie(resp, session)


# --- forgot / reset password ---

@app.get("/forgot/{role}", response_class=HTMLResponse)
def forgot_form(role: str):
    _role(role)
    body = (f'<p class="auth-sub">Enter your email and we will send a link to choose a new password.</p>'
            f'<form method="post" action="/forgot/{role}">{_csrf_input()}'
            '<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required maxlength="254" autocomplete="username"></div>'
            f'{_turnstile_widget()}<button class="submit-btn wide" type="submit">Send reset link</button></form>'
            f'<p class="fine"><a href="/login/{role}">Back to log in</a></p>')
    return _auth_page("Forgot password", body)


@app.post("/forgot/{role}")
def forgot_submit(role: str, request: Request, background: BackgroundTasks, email: str = Form(""),
                  csrf: str = Form(""), cf_token: str = Form("", alias="cf-turnstile-response")):
    _role(role)
    enforce_rate_limit(request, signup_limiter, "forgot")
    if not verify_csrf(csrf, "form") or not security.verify_turnstile(cf_token, security.client_ip(request)):
        return _auth_page("Forgot password", '<div class="banner warning">That did not go through. Please go back and try again.</div>', status=400)
    try:
        addr = accounts.normalize_email(email)
    except ValueError:
        addr = ""
    if addr and _email_ok(email_limiter, f"mail:{addr}"):
        with closing(sqlite3.connect(DB_PATH)) as db:
            user = accounts.get_user(db, addr, role)
            if user:
                token = accounts.issue_token(db, user["id"], "reset", accounts.RESET_TTL)
                background.add_task(_mail_reset, addr, token)
    body = ('<div class="banner info">If that address has an account, we sent a reset link. It works for one hour. '
            'Check your spam folder if it does not arrive.</div>')
    return _auth_page("Check your email", body, title="Check your email")


def _reset_page(token: str, error: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    body = (f'{err}<form method="post" action="/reset">{_csrf_input()}<input type="hidden" name="token" value="{esc(token)}">'
            f'{_pw_field(autocomplete="new-password", label="New password", check=True)}{_RULES_LIST}'
            f'{_pw_field(fid="f-password2", name="password2", label="Confirm new password", autocomplete="new-password")}'
            '<button class="submit-btn wide" type="submit">Save new password</button></form>')
    return _auth_page("Choose a new password", body, status=status)


@app.get("/reset", response_class=HTMLResponse)
def reset_form(token: str = ""):
    with closing(sqlite3.connect(DB_PATH)) as db:
        ok = accounts.peek_token(db, token, "reset")
    return _reset_page(token) if ok else _link_problem("reset link")


@app.post("/reset")
def reset_submit(request: Request, token: str = Form(""), password: str = Form(""),
                 password2: str = Form(""), csrf: str = Form("")):
    enforce_rate_limit(request, signup_limiter, "reset")
    if not verify_csrf(csrf, "form"):
        return _reset_page(token, "That page had been open too long. Please try again.", 400)
    with closing(sqlite3.connect(DB_PATH)) as db:
        uid = accounts.peek_token(db, token, "reset")
        user = accounts.get_user_by_id(db, uid) if uid else None
    if not user:
        return _link_problem("reset link")
    problems = accounts.password_problems(password, user["email"])
    if problems:
        return _reset_page(token, accounts.requirement_text(problems), 400)
    if password != password2:
        return _reset_page(token, "The two passwords do not match.", 400)
    with closing(sqlite3.connect(DB_PATH)) as db:
        if not accounts.consume_token(db, token, "reset"):
            return _link_problem("reset link")
        accounts.set_password(db, user["id"], password)
        accounts.mark_verified(db, user["id"])          # the link proved they control this mailbox
    body = (f'<div class="banner verified">Password updated. Every device was logged out.</div>'
            f'<a class="apply-btn" href="/login/{user["role"]}">Log in</a>')
    return _auth_page("Password updated", body)


# ---------- admin (review queue) ----------

def _is_admin(session: str | None) -> bool:
    return session_valid(session)


def _admin_csrf(session: str) -> str:
    return f'<input type="hidden" name="csrf" value="{make_csrf("admin:" + session)}">'


def _admin_gate(session: str | None, csrf: str) -> bool:
    return _is_admin(session) and verify_csrf(csrf, "admin:" + session)


@app.get("/admin", response_class=HTMLResponse)
def admin_home(session: str | None = Cookie(default=None)):
    if not _is_admin(session):
        body = f"""<h2 class="page">Reviewer sign-in</h2>
<p class="lead">The review queue is restricted. Enter the admin password.</p>
<form method="post" action="/admin/login">
<input type="hidden" name="csrf" value="{make_csrf('form')}">
<div class="form-field"><label for="f-password">Password</label><input id="f-password" type="password" name="password" required maxlength="200" autocomplete="current-password"></div>
<button class="submit-btn" type="submit">Sign in</button></form>"""
        return shell(body, title="Reviewer sign-in")

    csrf = _admin_csrf(session)
    pending = query_pending()
    if not pending:
        inner = '<div class="empty">Nothing waiting for review. New submissions will appear here.</div>'
    else:
        inner = ""
        for j in pending:
            findings = json.loads(j["findings_json"] or "[]")
            fl = "".join(
                f'<div class="finding {esc(f["severity"])}"><b>{esc(f["title"])}</b><br>{esc(f["why"])}</div>'
                for f in findings if f["severity"] in ("critical","warning"))
            fl_block = f'<div style="margin:12px 0">{fl}</div>' if fl else '<p style="font-size:13px;color:var(--soft);margin:10px 0">No scam signals fired.</p>'
            loc = esc(j["location"]) if j["location"] else ""
            url_line = f'<p style="font-size:13px;color:var(--soft);margin-top:8px;word-break:break-all">Apply: {esc(j["apply_url"])}</p>' if j["apply_url"] else ''
            contact_line = f'<p style="font-size:13px;color:var(--soft);margin-top:4px">Contact: {esc(j["contact"])}</p>' if j["contact"] else ''
            contact_line += (f'<p style="font-size:13px;color:var(--soft);margin-top:4px">Posted by: {esc(j["employer_email"])} (email confirmed)</p>'
                             if j.get("employer_email") else '')
            inner += f"""<div class="rev-card">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
<div><div class="job-title">{esc(j['title'])}</div><div class="job-co">{esc(j['company'])}</div></div>
<span class="rev-score {esc(j['scam_status'])}">Score {int(j['score'])} · {esc(j['scam_status'])}</span></div>
<div class="job-meta" style="margin-top:10px"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}</div>
{fl_block}
<div class="detail-desc" style="font-size:14px;max-height:140px;overflow:auto;background:var(--bg);padding:10px 12px;border-radius:6px">{esc(j['description'])}</div>
{url_line}{contact_line}
<div class="rev-actions">
<form method="post" action="/admin/approve/{int(j['id'])}">{csrf}<button class="btn-approve" type="submit">Approve &amp; publish</button></form>
<form method="post" action="/admin/reject/{int(j['id'])}" style="display:flex;gap:8px;flex-wrap:wrap">{csrf}<button class="btn-reject" type="submit" name="reason" value="scam">Reject: scam</button><button class="btn-reject" type="submit" name="reason" value="lead_gen">Reject: aggregator</button><button class="btn-reject" type="submit" name="reason" value="other">Reject: other</button></form>
</div></div>"""
    st = agreement_stats()
    if st["n"] == 0:
        stats_html = ""
    elif st["n"] < 10:
        stats_html = (f'<p class="lead" style="font-size:13px">Detector vs your decisions: {st["n"]} labeled so far. '
                      f'Too few to judge; every decision you make here is training data for the next rule update.</p>')
    else:
        pct = round(100 * st["agree"] / st["n"])
        stats_html = (f'<p class="lead" style="font-size:13px">Detector vs your decisions: agreed on {pct}% of {st["n"]}. '
                      f'Missed {st["missed"]} listing(s) you rejected as bad; flagged {st["false_alarm"]} you approved.</p>')
    body = (f'<h2 class="page">Review queue</h2>{stats_html}<p class="lead">{len(pending)} submission{"s" if len(pending)!=1 else ""} waiting. '
            f'The scam score is advisory — you decide what publishes. '
            f'<a href="/admin/live">Live listings</a></p><div class="lead" style="margin-top:-12px">'
            f'<form method="post" action="/admin/logout" style="display:inline">{csrf}<button style="background:none;border:none;color:var(--garnet);text-decoration:underline;cursor:pointer;font:inherit">Sign out</button></form></div>{inner}')
    return shell(body, title="Review queue", admin=True)


@app.get("/admin/live", response_class=HTMLResponse)
def admin_live(session: str | None = Cookie(default=None)):
    if not _is_admin(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = _admin_csrf(session)
    live = query_live()
    if not live:
        inner = '<div class="empty">No live listings.</div>'
    else:
        inner = "".join(f"""<div class="rev-card"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
<div><div class="job-title">{esc(j['title'])}</div><div class="job-co">{esc(j['company'])} · posted {esc(j['created_at'][:10])}</div></div>
<form method="post" action="/admin/remove/{int(j['id'])}" style="display:flex;gap:8px;flex-wrap:wrap">{csrf}<button class="btn-reject" type="submit" name="reason" value="scam">Remove: scam</button><button class="btn-reject" type="submit" name="reason" value="lead_gen">Remove: aggregator</button><button class="btn-reject" type="submit" name="reason" value="other">Remove: other</button></form></div></div>""" for j in live)
    body = f'<h2 class="page">Live listings</h2><p class="lead">Removing a listing takes it off the board immediately. <a href="/admin">Back to queue</a></p>{inner}'
    return shell(body, title="Live listings", admin=True)


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...), csrf: str = Form("")):
    # 5 attempts per 15 minutes per client IP; every attempt counts.
    enforce_rate_limit(request, login_limiter, "admin_login")
    password = password[: MAX_LEN["password"]]
    ok_token = verify_csrf(csrf, "form")
    ok_pw = secrets.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    if ok_token and ok_pw:
        token = new_session()
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie("session", token, httponly=True, samesite="strict",
                        secure=IS_PROD, max_age=security.SESSION_TTL, path="/")
        return resp
    return HTMLResponse(shell(
        '<h2 class="page">Sign-in failed</h2><p class="lead">Check the password and try again.</p><a class="back" href="/admin">← Back</a>'
    ), status_code=401)


@app.post("/admin/logout")
def admin_logout(session: str | None = Cookie(default=None), csrf: str = Form("")):
    if _admin_gate(session, csrf):
        end_session(session)
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie("session", path="/")
    return resp


def _review_action(job_id: int, request: Request, session, csrf, status: str, reason: str = ""):
    if not _admin_gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    enforce_rate_limit(request, general_limiter, "admin_action")
    label = "legit" if status == "approved" else clean_choice(reason, REVIEW_REASONS, "reason", default="other")
    # Approve/reject only act on waiting submissions; remove only acts on live ones.
    set_review(job_id, status, label, only_from=("approved",) if status == "removed" else ("pending",))
    return RedirectResponse("/admin" if status != "removed" else "/admin/live", status_code=303)


@app.post("/admin/approve/{job_id}")
def admin_approve(job_id: int, request: Request, session: str | None = Cookie(default=None), csrf: str = Form("")):
    return _review_action(job_id, request, session, csrf, "approved")


@app.post("/admin/reject/{job_id}")
def admin_reject(job_id: int, request: Request, session: str | None = Cookie(default=None),
                 csrf: str = Form(""), reason: str = Form("other")):
    return _review_action(job_id, request, session, csrf, "rejected", reason)


@app.post("/admin/remove/{job_id}")
def admin_remove(job_id: int, request: Request, session: str | None = Cookie(default=None),
                 csrf: str = Form(""), reason: str = Form("other")):
    return _review_action(job_id, request, session, csrf, "removed", reason)
