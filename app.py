"""
NoleCareerShield — a curated job board for FSU students.

TWO LAYERS OF PROTECTION:
  1. Every submission is SCORED by the scam detector (scam_detector.scorer).
  2. Every submission then waits in a REVIEW QUEUE until an admin approves it.
     Nothing is public until a human approves it.

Anyone may BROWSE. Students (confirmed @fsu.edu email) log in to see how to apply;
employers (any confirmed email) log in to submit. Only an admin can approve postings.
Posting is account-gated and approval-gated, not open-publish.

STUDENT NETWORK (profiles.py, messaging.py, feed.py, assistant.py, resume_tools.py, msgcheck.py):
  Profiles after sign-up, student <-> approved-employer messaging with every message
  scam-scanned, an FSU-only feed, the job assistant, resume studio and the message scam
  checker. Employers are reviewed by a person before they can message students or post.

PRIVACY BY DESIGN:
  Browsing listings is anonymous. Accounts hold an email and a password hash; students may
  add a profile and a resume, and choose whether approved employers can find them. No
  analytics, no trackers, no third-party fonts. AI features are optional (ANTHROPIC_API_KEY)
  and send text to Anthropic only when a signed-in person uses one. Outbound calls: SMTP
  mail, optional Turnstile, optional Anthropic API, optional RDAP/DNS enrichment (off).

  Admin auth is a single shared password read from the ADMIN_PASSWORD
  environment variable. In production (ENV=production) the app refuses to
  start without a strong ADMIN_PASSWORD, a SECRET_KEY and a CONTACT_EMAIL.

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
import hmac
import secrets
import time
import sqlite3
import contextvars
import datetime as dt
from contextlib import closing, asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Form, Cookie, Response, Request, HTTPException, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from scam_detector.scorer import score_posting
from scam_detector import ml
import accounts
import backup
import mailer
import security
import store
import ui
import public_ui
import web
import matching
import profiles
import profile_page
import fit
import jobboard
import jobfit
import messaging
import msgcheck
import learning
import defense
import defense_web
import cases
import assistant
import resume_tools
import feed
import admin_extra
import hiring
import easyapply
import emails
import quals
import network
import employer_page
import events
import teams
import guardian
import sso
import ai
from ui import esc, EMBLEM, BASE_CSS, PAGE_SCRIPT, PAGE_SCRIPT_HASH, _viewer, shell
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
    """Purge expired data, remind employers about listings about to expire, and take a database backup.
    Runs at startup and then every MAINTENANCE_HOURS."""
    purge_old()
    try:
        send_expiry_reminders()
    except Exception:                      # noqa: BLE001 - a failed reminder must never take the site down
        log.exception("expiry reminders failed")
    try:
        backup.run_backup(DB_PATH)
    except Exception:                      # noqa: BLE001 - a failed backup must never take the site down
        log.exception("database backup failed")
    learning.maybe_retrain()               # retrains the scam model in the background when a month and enough labels have passed
    defense.daily_jobs()                   # certificate-log watch, peer school feeds, scam archives (each only when configured)
    try:
        with store.db() as conn:
            cases.sync(conn)                   # every drift alert becomes an investigation case
    except Exception:                      # noqa: BLE001
        log.exception("case sync failed")


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

CATEGORIES = matching.CATEGORIES
WORK_TYPES = matching.WORK_TYPES


# ---------- database ----------

# Added after the first release; existing databases are migrated in place.
_EXTRA_COLUMNS = {"review_label": "TEXT", "ruleset_version": "TEXT", "reviewed_at": "TEXT", "reviewer": "TEXT NOT NULL DEFAULT ''", "employer_id": "INTEGER",
                  "easy_apply": "INTEGER NOT NULL DEFAULT 0", "questions": "TEXT NOT NULL DEFAULT '[]'",
                  "requirements": "TEXT NOT NULL DEFAULT '[]'",
                  "poster_name": "TEXT NOT NULL DEFAULT ''", "poster_title": "TEXT NOT NULL DEFAULT ''",
                  "show_email": "INTEGER NOT NULL DEFAULT 0",
                  # Listing controls (hiring.py): open | paused | closed, and when an approved listing drops off the board.
                  "listing_status": "TEXT NOT NULL DEFAULT 'open'", "expires_at": "REAL",
                  "expiry_days": f"INTEGER NOT NULL DEFAULT {store.LISTING_DAYS_DEFAULT}", "expiry_reminded": "REAL",
                  "learn_split": "TEXT",
                  # Team accounts: the member who posted it (employer_id stays the company's org id).
                  "posted_by": "INTEGER"}
REVIEW_REASONS = ["scam", "lead_gen", "other"]


def _ensure_columns(db):
    have = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    for col, typ in _EXTRA_COLUMNS.items():
        if col not in have:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")


def init_db():
    learning.configure()                   # the detector uses the model retrained on this board, when there is one
    with store.db() as conn:
        defense.ensure_schema(conn)            # hashed identifiers, intel cache, drift counters, campus calendar
        cases.ensure_schema(conn)              # investigation cases opened from drift alerts
        import release
        release.ensure_schema(conn)            # staged model releases, background comparisons, rollback
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
        store.init(db)
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
        store.purge(db)
    events.send_event_reminders()          # the day-before reminder; each RSVP is reminded once


visible_listing = store.visible_listing       # the one rule for what students can see (store.live_where is the SQL twin)


def _scan(data: dict, job_id: int | None = None) -> tuple:
    """Scam-scan a listing. Returns (result, scam_status, findings)."""
    result = score_posting(
        title=data["title"], description=data["description"] + ("\n" + easyapply.questions_text(data.get("questions") or [])
                                                                if data.get("questions") else ""), company=data["company"],
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

    # The learned model (scam_detector/ml.py) can only send a quiet listing to the reviewer with a note.
    second = ml.second_look(data["title"], data["description"], data["company"], data.get("apply_url", ""),
                            result.findings, result.score) if result.band in ("clear", "caution") else None
    if second:
        findings.append(second)
        if scam_status == "clear":
            scam_status = "flagged"

    # Identifiers from confirmed scams, copies of approved listings, look-alike domains and outside intel: only ever stricter.
    for f in defense.extra_findings(data["description"], sender=data.get("contact", ""), title=data["title"], company=data["company"],
                                    url=data.get("apply_url", ""), exclude_job=job_id):
        if f["weight"] <= 0 and f["severity"] == "note":
            continue
        findings.append(f)
        if f["severity"] == "critical" and scam_status != "held":
            scam_status = "held" if f["weight"] >= 35 else "flagged"
        elif scam_status == "clear" and f["weight"] >= 10:
            scam_status = "flagged"
    return result, scam_status, findings

defense.set_job_scanner(_scan)          # so revoking or confirming a contact detail re-scores the listings that contain it


def add_job(data: dict, employer_id: int | None = None, posted_by: int | None = None) -> dict:
    result, scam_status, findings = _scan(data)
    days = _expiry_days(data.get("expiry_days"))
    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("""
            INSERT INTO jobs (title, company, category, work_type, location,
                              description, apply_url, contact, score, band,
                              scam_status, review_status, findings_json, created_at,
                              ruleset_version, employer_id, easy_apply, questions, requirements,
                              poster_name, poster_title, show_email, expiry_days, posted_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["title"], data["company"], data.get("category","Other"),
            data["work_type"], data.get("location",""), data["description"],
            data.get("apply_url",""), data.get("contact",""),
            result.score, result.band, scam_status, "pending",
            json.dumps(findings), dt.datetime.utcnow().isoformat(),
            result.ruleset_version, employer_id,
            1 if data.get("easy_apply") else 0, json.dumps(data.get("questions") or []),
            json.dumps(data.get("requirements") or []),
            data.get("poster_name", ""), data.get("poster_title", ""), 1 if data.get("show_email") else 0, days,
            posted_by or employer_id,
        ))
        db.commit()
        job_id = cur.lastrowid
    with store.db() as conn:
        defense.index_job(conn, job_id, "\n".join(data.get(k, "") or "" for k in ("title", "company", "description", "apply_url", "contact")))
    return {"id": job_id, "scam_status": scam_status, "score": result.score,
            "band": result.band, "findings": findings}


def _expiry_days(v) -> int:
    try:
        d = int(v)
    except (TypeError, ValueError):
        return store.LISTING_DAYS_DEFAULT
    return max(store.LISTING_DAYS_MIN, min(store.LISTING_DAYS_MAX, d))


def query_public(search="", category="", work_type="") -> list:
    """Only approved listings that aren't paused, closed or expired are ever shown (store.live_where)."""
    q = f"SELECT * FROM jobs WHERE {store.live_where(ttl_days=LISTING_TTL_DAYS)} "
    params = []
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
    sql = "UPDATE jobs SET review_status = ?, review_label = ?, reviewed_at = ?"
    params = [status, label, dt.datetime.utcnow().isoformat()]
    if status == "approved":
        # Approval starts the clock: the listing drops off the board expiry_days (default 60) from now.
        sql += ", expires_at = ? + 86400 * COALESCE(expiry_days, ?), expiry_reminded = NULL"
        params += [time.time(), store.LISTING_DAYS_DEFAULT]
    sql += " WHERE id = ?"
    params.append(job_id)
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
        return db.execute(f"SELECT COUNT(*) FROM jobs WHERE {store.live_where(ttl_days=LISTING_TTL_DAYS)}").fetchone()[0]


def pending_count() -> int:
    with closing(sqlite3.connect(DB_PATH)) as db:
        return db.execute("SELECT COUNT(*) FROM jobs WHERE review_status='pending'").fetchone()[0]


# ---------- markup (the design system lives in ui.py) ----------

def _score_pill(j: dict) -> str:
    """The reviewer's verdict pill. The scam score only counts scam rules; a listing flagged by the separate
    aggregator/lead-gen check says so instead of showing "Score 0 · flagged"."""
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    text = f"Scam risk {ui.shown_score(j['score'], lead_gen, j['scam_status'])} · {j['scam_status']}"
    return f'<span class="rev-score {esc(j["scam_status"])}">{esc(text)}{" · Aggregator" if lead_gen else ""}</span>'


def _scan_chip(j: dict) -> str:
    """The job card's scan-status chip (ui.scan_chip): Secure / Caution / Threat and the shown score. The older
    "Scam risk N · status" wording stays as screen-reader text."""
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    sc = ui.shown_score(j["score"], lead_gen, j["scam_status"])
    return ui.scan_chip(ui.scan_state(j["scam_status"]), sc, label=f"Scam risk {sc} · {j['scam_status']}")


def _risk(j: dict) -> str:
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    return ui.risk_meter(int(j["score"]), j["scam_status"], aggregator=lead_gen)


def _teaser_card(j: dict) -> str:
    """What visitors see: title, company and category. Everything else is for signed-in students."""
    return (f'<a class="job teaser" href="/login?next=/job/{int(j["id"])}"><div class="job-top"><div><div class="job-title">{esc(j["title"])}</div>'
            f'<div class="job-co">{esc(j["company"])}</div></div><span class="pill">{ui.icon("shield", 13)} Log in to view</span></div>'
            f'<div class="job-meta"><span class="chip">{esc(j["category"])}</span></div></a>')


# ---------- public routes ----------

_script_src = f"'self' '{PAGE_SCRIPT_HASH}'" + (" https://challenges.cloudflare.com" if security.turnstile_enabled() else "")
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
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
            if user and user["role"] == "employer":
                # Team accounts: resolve once which company (org) this employer acts for, and their role on its team.
                user["org_id"] = store.org_of(db, user["id"])
                user["org_role"] = store.org_role(db, user["id"])
    request.state.user = user
    request.state.utoken = raw if user else None
    extra = {}
    if user and not request.url.path.startswith(("/static/", "/api/")):
        with store.db() as conn:
            extra["unread"] = (store.unread_count(conn, user["id"], org=user["org_id"]) if user["role"] == "employer"
                               else store.unread_count(conn, user["id"]))
            extra["emails"] = emails.unread(conn, user["id"])
            if user["role"] == "student":
                extra["requests"] = network.incoming_count(conn, user["id"])
    marker = _viewer.set({"user": user, "token": raw if user else None, "extra": extra})
    try:
        response = _beta_gate(request) or await call_next(request)
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
    path = request.url.path
    if BETA_CODE:
        h["X-Robots-Tag"] = "noindex, nofollow"
    if path.startswith(_PRIVATE_PREFIXES):
        h["Cache-Control"] = "no-store"
        h["X-Robots-Tag"] = "noindex, nofollow"
    elif user and "Cache-Control" not in h:
        h["Cache-Control"] = "private, no-store"     # signed-in pages show personal data
    return response


_PRIVATE_PREFIXES = ("/admin", "/messages", "/api/", "/profile", "/resume", "/u/", "/talent", "/feed", "/assistant", "/check", "/job", "/hiring", "/company")


def _guard_page(status: int, message: str, path: str):
    heading = {429: "Slow down", 413: "That's too large"}.get(status, "That didn't go through")
    resp = HTMLResponse(shell(f'<h2 class="page">{esc(heading)}</h2><div class="banner warning">{esc(message)}</div>'
                              f'<a class="back" href="/">← Home</a>', title=heading), status_code=status)
    resp.headers["Content-Security-Policy"] = CSP
    return resp


security.GUARD_RENDER = _guard_page
# Added last, so it is the outermost layer: rate limits, size caps and malformed-input checks run before
# sessions are looked up or the app reads anything.
app.add_middleware(security.RequestGuard)


# ---------- private beta ----------
# With PRIVATE_BETA_CODE set, the site is live but closed: every page asks for the code once per browser (a signed cookie,
# so changing the code locks everyone out again), nothing is indexed, and robots.txt disallows everything. The reviewer
# desk (/admin, which has its own password), the health check, site files and the mail webhook stay reachable.
# Remove the setting to open the site.
BETA_CODE = os.environ.get("PRIVATE_BETA_CODE", "").strip()
BETA_COOKIE = "ncs_beta"
_BETA_OPEN = ("/beta", "/healthz", "/robots.txt", "/static/", "/admin", "/inbound/")


def _beta_next(value: str) -> str:
    """Where to return after the code: any path on this site (email links carry tokens, so the whole path and query are
    kept), never another site."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value or len(value) > 600 or any(ord(c) < 32 for c in value):
        return ""
    return value


def _beta_token() -> str:
    return hmac.new(security.secret_key(), ("beta|" + BETA_CODE).encode(), hashlib.sha256).hexdigest()[:40]


def _beta_gate(request: Request):
    if not BETA_CODE or request.url.path.startswith(_BETA_OPEN):
        return None
    if hmac.compare_digest(request.cookies.get(BETA_COOKIE, ""), _beta_token()):
        return None
    if request.method in ("GET", "HEAD"):
        nx = _beta_next(request.url.path + (("?" + request.url.query) if request.url.query else ""))
        return RedirectResponse("/beta" + (f"?next={quote(nx, safe='')}" if nx and nx != "/" else ""), status_code=303)
    return HTMLResponse(shell('<h2 class="page">Private beta</h2><p class="lead">Enter the access code first.</p>'
                              '<a class="back" href="/beta">Enter code</a>', title="Private beta"), status_code=403)


def _beta_page(next_: str = "", error: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    body = f"""{err}<form method="post" action="/beta"><input type="hidden" name="csrf" value="{make_csrf('form')}">
<input type="hidden" name="next" value="{esc(next_)}"><div class="field"><label for="f-code">Access code</label>
<input id="f-code" name="code" type="password" autocomplete="off" required maxlength="200"></div>
<button class="submit-btn wide" type="submit">Continue</button></form>"""
    return _auth_page("NoleCareerShield isn't open yet", body, title="Private beta — NoleCareerShield", status=status,
                      kicker="Private beta", icon="lock",
                      sub="It's being tested by a small group. If you were given an access code, enter it here.")


@app.get("/beta", response_class=HTMLResponse)
def beta_form(next: str = ""):
    if not BETA_CODE:
        return RedirectResponse("/", status_code=303)
    return _beta_page(_beta_next(next))


@app.post("/beta", response_class=HTMLResponse)
def beta_submit(code: str = Form(""), csrf: str = Form(""), next: str = Form("")):
    if not BETA_CODE:
        return RedirectResponse("/", status_code=303)
    nx = _beta_next(next)
    if not verify_csrf(csrf, "form"):
        return _beta_page(nx, "That page had been open too long. Please try again.", 400)
    if not secrets.compare_digest(code.strip()[:200].encode(), BETA_CODE.encode()):
        return _beta_page(nx, "That code isn't right.", 401)          # 5 wrong codes per 15 minutes per address (RequestGuard)
    resp = RedirectResponse(nx or "/", status_code=303)
    resp.set_cookie(BETA_COOKIE, _beta_token(), httponly=True, samesite="lax", secure=IS_PROD, max_age=90 * 24 * 3600, path="/")
    return resp


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("SELECT 1").fetchone()
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    if BETA_CODE:
        return "User-agent: *\nDisallow: /\n"
    return ("User-agent: *\nDisallow: /admin\nDisallow: /post\nDisallow: /messages\nDisallow: /profile\nDisallow: /jobs\nDisallow: /job/\nDisallow: /hiring\n"
            "Disallow: /resume\nDisallow: /u/\nDisallow: /company/\nDisallow: /talent\nDisallow: /feed\n"
            "Disallow: /assistant\nDisallow: /api/\n")


_APP_JS = (Path(__file__).resolve().parent / "static" / "app.js").read_bytes()
ui.APP_JS_VERSION = hashlib.sha256(_APP_JS).hexdigest()[:10]


@app.get("/static/app.js")
def static_app_js():
    return Response(_APP_JS, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


_FX_JS = (Path(__file__).resolve().parent / "static" / "fx.js").read_bytes()
ui.FX_JS_VERSION = hashlib.sha256(_FX_JS).hexdigest()[:10]
_FONTS = {f: (Path(__file__).resolve().parent / "static" / "fonts" / f).read_bytes() for f in ui.FONT_FILES}


@app.get("/static/fx.js")
def static_fx_js():
    return Response(_FX_JS, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# Landing-page footage and photos. Loaded once; only files that exist in static/media can be named.
_MEDIA_DIR = Path(__file__).resolve().parent / "static" / "media"
_MEDIA = {f.name: f.read_bytes() for f in sorted(_MEDIA_DIR.glob("*.webp"))} if _MEDIA_DIR.is_dir() else {}
ui.MEDIA_VERSION = hashlib.sha256(b"".join(k.encode() + v for k, v in _MEDIA.items())).hexdigest()[:10]


@app.get("/static/media/{name}")
def static_media(name: str):
    data = _MEDIA.get(name)
    if data is None:
        raise StarletteHTTPException(status_code=404)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/static/fonts/{name}")
def static_font(name: str):
    # Fraunces, Graduate, Plus Jakarta Sans and Martian Mono, SIL Open Font License 1.1 (static/fonts/OFL.txt). Self-hosted: no
    # third-party font requests. Only the files in ui.FONT_FILES can be named.
    data = _FONTS.get(name)
    if data is None:
        raise StarletteHTTPException(status_code=404)
    return Response(data, media_type="font/woff2", headers={"Cache-Control": "public, max-age=31536000, immutable"})


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


@app.exception_handler(web.LoginRequired)
def _login_required(request: Request, exc: web.LoginRequired):
    nx = _safe_next(exc.next) or ""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Please log in again."}, status_code=401)
    return RedirectResponse(f"/login/{exc.role}" + (f"?next={nx}" if nx else ""), status_code=303)


@app.exception_handler(web.Forbidden)
def _forbidden(request: Request, exc: web.Forbidden):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.message}, status_code=403)
    body = ui.page_head("Not available") + ui.banner("info", exc.message) + '<a class="b sec" href="/">Home</a>'
    return web.page(body, "Not available", active="", status=403)


@app.exception_handler(RequestValidationError)
def _validation_handler(request: Request, exc: RequestValidationError):
    # A malformed URL parameter or a form missing fields: friendly page, no internals echoed.
    body = ('<h2 class="page">That request wasn\'t valid</h2>'
            '<p class="lead">Something in the link or form was missing or malformed. Please go back and try again.</p>'
            '<a class="back" href="/">← Home</a>')
    return HTMLResponse(shell(body, title="Invalid request"), status_code=400)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    user = getattr(request.state, "user", None)
    if user:
        # Signed in: the bento home. New students go through profile setup first.
        if user["role"] == "student":
            with store.db() as conn:
                p = store.student_profile(conn, user["id"])
            if not p or not p.get("setup_step"):
                return RedirectResponse("/profile/setup", status_code=303)
        return HTMLResponse(shell(profiles.dashboard(user), title="Home — NoleCareerShield", active="/", js=True))
    night, fair = ui.students_chapters()
    hero = (ui.cine_hero() + ui.marquee_block() + public_ui.proof() + night
            + ui.scan_block('<a href="/check">Check one you found →</a>') + public_ui.check_teaser() + ui.how_students() + fair)
    jobs = query_public()
    if jobs:
        with store.db() as conn:
            employers = conn.execute("SELECT COUNT(*) FROM employer_profiles WHERE status = 'approved'").fetchone()[0]
        emp = f" from {employers} approved employer{'s' if employers != 1 else ''}" if employers else ""
        cards = "".join(_teaser_card(j) for j in jobs[:3])
        body = (f'<h2 class="display section-title rv">Latest listings.</h2>'
                f'<p class="muted" style="margin:0 0 18px">{len(jobs)} verified listing{"s" if len(jobs) != 1 else ""}{emp}, every one scam-checked and '
                f'approved by a person. Log in with your @fsu.edu email to see the details and apply.</p><div class="teasers">{cards}</div>'
                '<p style="margin:16px 0 40px"><a href="/login?next=/jobs" style="color:var(--accent-ink);font-weight:600;text-decoration:none">Log in to see all jobs →</a></p>')
    else:
        body = '<div class="empty" style="margin:32px 0 48px">No approved listings yet. <a href="/employers" style="color:var(--accent-ink);font-weight:600">Hiring? Post the first one.</a></div>'
    return shell(f'<section class="home-list">{body}</section>{public_ui.employer_cta()}', hero=hero, wide=True)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_feed(request: Request):
    enforce_rate_limit(request, general_limiter, "jobs_feed")
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return RedirectResponse("/login?next=/jobs", status_code=303)       # the board is for FSU students and employers only
    if viewer["role"] == "employer":
        return RedirectResponse("/hiring", status_code=303)                 # employers manage their own listings; the board is for students
    old = jobboard.old_pane_link(request.query_params)            # /jobs?job=ID was the two-pane board; listings have their own page now
    if old:
        return RedirectResponse(f"/job/{old}", status_code=301)
    # Query params are attacker-controlled input same as form fields: jobboard.parse_params drops anything unexpected.
    with store.db() as conn:
        # Each card's scan chip links to the listing's security report; it shows the result once the student has opened it.
        opened = guardian.opened_ids(conn, viewer["id"])
        body = jobboard.board(conn, viewer, dict(request.query_params), query_public(), pill=lambda j: guardian.chip(j, opened), risk=_risk)
    return shell(body, title="Browse jobs — NoleCareerShield", active="/jobs")


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request):
    enforce_rate_limit(request, general_limiter, "job_detail")
    viewer = getattr(request.state, "user", None)
    if not viewer:
        return RedirectResponse(f"/login?next=/job/{int(job_id)}", status_code=303)
    j = get_job(job_id)
    if not visible_listing(j):
        return HTMLResponse(shell('<p class="empty" style="margin:40px 0">That listing isn\'t available.</p>'), status_code=404)
    after = ""
    with store.db() as conn:
        prof = store.student_profile(conn, viewer["id"]) if viewer["role"] == "student" else None
        saved = (int(j["id"]) in jobboard.saved_ids(conn, viewer["id"])) if viewer["role"] == "student" else None
        if viewer["role"] == "student":
            after = jobfit.tailor_panel(j, prof)
            opened = guardian.opened_ids(conn, viewer["id"])
            pill = lambda x: guardian.chip(x, opened)
        else:
            own = j.get("employer_id") == store.org_id(viewer)
            pill = lambda x: guardian.chip(x, None, link=own)
        body = '<div class="jb jb-page">' + jobboard.detail(conn, viewer, j, prof, pill=pill, risk=_risk, next_=f"/job/{int(j['id'])}",
                                                           record=True, saved=saved, extra=after) + "</div>"
    return shell(body, title=j["title"] + " — NoleCareerShield", active="/jobs", js=bool(after))


@app.get("/job/{job_id}/apply")
def job_apply(job_id: int, request: Request):
    """Counts a student's Apply click (once per student, for the employer's totals), then goes to the apply link."""
    viewer = getattr(request.state, "user", None)
    j = get_job(job_id)
    if not visible_listing(j) or not j["apply_url"] or not (viewer and viewer["role"] == "student"):
        return RedirectResponse(f"/job/{int(job_id)}", status_code=303)
    enforce_rate_limit(request, general_limiter, "job_apply")
    with store.db() as conn:
        hiring.record_apply_click(conn, int(j["id"]), viewer["id"])
    return RedirectResponse(j["apply_url"], status_code=303)


def _post_form_page(values: dict | None = None, error: str = "", status: int = 200, edit_id: int = 0) -> HTMLResponse:
    """The submit form. On a rejected submission it is shown again with everything the
    poster typed still in place and the reason at the top, so nobody retypes a long posting.
    With edit_id it is the edit form for that listing (prefilled, posts to /hiring/{id}/edit)."""
    # Editing a live listing is a signed-in action, so its token is bound to the employer's session.
    csrf_field = ui.user_csrf_input() if edit_id else f'<input type="hidden" name="csrf" value="{make_csrf("form")}">'
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
    qv = v.get("questions") if isinstance(v.get("questions"), list) else []
    qv = list(qv) + [{}] * (easyapply.MAX_QUESTIONS - len(qv))
    q_rows = "".join(
        f'<div class="qrow"><label class="sr" for="f-qtext{i}">Question {i + 1}</label><input id="f-qtext{i}" name="qtext" maxlength="{easyapply.Q_LEN}" placeholder="Question {i + 1}" value="{esc(q.get("q", ""))}">'
        f'<label class="sr" for="f-qkind{i}">Answer type for question {i + 1}</label><select id="f-qkind{i}" name="qkind">' + "".join(f'<option value="{k}"{" selected" if q.get("kind") == k else ""}>{esc(n)}</option>' for k, n in easyapply.KINDS) + '</select>'
        f'<label class="sr" for="f-qreq{i}">Required or optional for question {i + 1}</label><select id="f-qreq{i}" name="qreq"><option value="0">Optional</option><option value="1"{" selected" if q.get("required") else ""}>Required</option></select></div>'
        for i, q in enumerate(qv[:easyapply.MAX_QUESTIONS]))
    rv = v.get("requirements") if isinstance(v.get("requirements"), list) else []
    rv = list(rv) + [{}] * (quals.MAX_ITEMS - len(rv))
    r_rows = "".join(
        f'<div class="qrow"><label class="sr" for="f-rkind{i}">Qualification {i + 1} type</label><select id="f-rkind{i}" name="rkind">' + "".join(f'<option value="{k}"{" selected" if r.get("kind") == k else ""}>{esc(n)}</option>' for k, n in quals.KINDS.items()) + '</select>'
        f'<label class="sr" for="f-rlabel{i}">Qualification {i + 1}</label><input id="f-rlabel{i}" name="rlabel" maxlength="{quals.LABEL_LEN}" placeholder="e.g. Excel, Marketing, 3.0" value="{esc(r.get("label", ""))}">'
        f'<label class="sr" for="f-rmust{i}">Required or preferred for qualification {i + 1}</label><select id="f-rmust{i}" name="rmust"><option value="0">Preferred</option><option value="1"{" selected" if r.get("must") else ""}>Required</option></select></div>'
        for i, r in enumerate(rv[:quals.MAX_ITEMS]))
    easy_on = " checked" if v.get("easy_apply") in (1, True, "1", "on") else ""
    if edit_id:
        top = (f'<a class="back" href="/hiring/{int(edit_id)}">← Back to the listing</a>\n<h2 class="page">Edit listing</h2>\n'
               '<p class="lead">Changing the title, company, description, apply URL, contact or questions scans the listing again and sends it back '
               'to a reviewer; it is off the board until they approve it. Category, work type, location, qualifications and who\'s posting '
               'change right away.</p>')
        action, button, expiry = f"/hiring/{int(edit_id)}/edit", "Save changes", ""
    else:
        top = ('<a class="back" href="/">← Home</a>\n<h2 class="page">Submit a job</h2>\n<p class="lead">Submitting isn\'t publishing. '
               'Every listing is scam-scanned and then reviewed by a human before it appears — only vetted postings go live.</p>')
        action, button = "/post", "Submit for review"
        cur_days = _expiry_days(v.get("expiry_days"))
        expiry = ('<div class="form-field"><label for="f-expiry">Keep it up for</label><p class="hint">Counted from the day a reviewer approves it. '
                  'You can extend, pause or close it any time from Your listings. We email you 5 days before it ends.</p>'
                  '<select id="f-expiry" name="expiry_days">' + "".join(
                      f'<option value="{d}"{" selected" if d == cur_days else ""}>{d} days</option>' for d in (7, 14, 30, 45, 60, 90, 120)) + '</select></div>')
    body = f"""{top}
{err}<form method="post" action="{action}">
{csrf_field}
<div class="hp" aria-hidden="true"><label for="f-website">Leave this empty</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="form-field"><label for="f-title">Job title</label><input id="f-title" name="title" required maxlength="200" placeholder="e.g. Marketing Data Analyst" value="{val('title')}"></div>
<div class="form-field"><label for="f-company">Company</label><input id="f-company" name="company" required maxlength="200" placeholder="e.g. Leaf Home" value="{val('company')}"></div>
<div class="form-field"><label for="f-category">Category</label><select id="f-category" name="category">{cat_opts}</select></div>
<div class="form-field"><label for="f-work_type">Work type</label><select id="f-work_type" name="work_type">{wt_opts}</select></div>
<div class="form-field"><label for="f-location">Location</label><p class="hint">City/state, or leave blank if fully remote.</p><input id="f-location" name="location" maxlength="120" placeholder="e.g. Tallahassee, FL" value="{val('location')}"></div>
<div class="form-field"><label for="f-description">Description</label><p class="hint">The full posting — responsibilities, requirements, and pay if you can share it.</p><textarea id="f-description" name="description" required maxlength="8000">{val('description')}</textarea></div>
<div class="form-field"><label for="f-apply_url">Apply URL</label><p class="hint">Where applicants should go. The scanner checks this link too.</p><input id="f-apply_url" name="apply_url" maxlength="2000" placeholder="https://..." value="{val('apply_url')}"></div>
<div class="form-field"><label for="f-contact">Contact (optional)</label><p class="hint">Shown publicly if approved. Use a role or company address, not a personal one.</p><input id="f-contact" name="contact" maxlength="200" placeholder="careers@company.com" value="{val('contact')}"></div>
{expiry}
<fieldset class="form-field easyset"><legend>Who's posting</legend>
<p class="hint">Your name appears on the listing so students know who they'd be talking to. Students who apply can message you on NoleCareerShield.</p>
<div class="form-field"><label for="f-poster_name">Your name</label><input id="f-poster_name" name="poster_name" maxlength="80" placeholder="e.g. Dana Whitfield" value="{val('poster_name')}"></div>
<div class="form-field"><label for="f-poster_title">Your job title</label><input id="f-poster_title" name="poster_title" maxlength="80" placeholder="e.g. Campus Recruiting Manager" value="{val('poster_title')}"></div>
<label class="toggle" for="f-show_email"><input id="f-show_email" type="checkbox" name="show_email" value="1"{" checked" if v.get("show_email") in (1, True, "1", "on") else ""}><span><b>Show my email on this listing.</b> Off by default. Students can always message you here after they apply.</span></label>
<label class="toggle" for="f-direct" style="margin-top:12px"><input id="f-direct" type="checkbox" name="direct" value="1" required{" checked" if v.get("direct") in (1, True, "1", "on") else ""}><span><b>I work directly for this company.</b> Staffing agencies and second- or third-party recruiters can't post jobs for a client.</span></label></fieldset>
<fieldset class="form-field easyset"><legend>Qualifications</legend>
<p class="hint">Choose what applicants need. Students see which ones they meet, and you see the same on every applicant. Skills, majors, certifications, class standing, graduation year and GPA only. Up to {quals.MAX_ITEMS}.</p>{r_rows}</fieldset>
<fieldset class="form-field easyset"><legend>Quick apply</legend>
<label class="toggle" for="f-easy"><input id="f-easy" type="checkbox" name="easy_apply" value="1"{easy_on}><span><b>Collect applications on NoleCareerShield.</b> Students apply from their profile in one step, and you get their answers in your candidate tracker. Leave it off to send them to your Apply URL.</span></label>
<p class="hint" style="margin-top:10px">Optional questions for applicants (up to {easyapply.MAX_QUESTIONS}). Nothing that asks for an SSN, bank or card details or a password.</p>{q_rows}</fieldset>
<button class="submit-btn" type="submit">{button}</button>{"" if edit_id else under}</form>"""
    return HTMLResponse(shell(body, title=("Edit listing" if edit_id else "Submit a job") + " — NoleCareerShield",
                              active="/hiring" if edit_id else "/post"), status_code=status)


@app.get("/post", response_class=HTMLResponse)
def post_form(request: Request):
    user = getattr(request.state, "user", None)
    if user and user["role"] == "employer":
        # "Your name" and "Your job title" start as the signed-in team member's own (the company contact for an owner).
        with store.db() as conn:
            card = store.member_card(conn, user["id"])
        return _post_form_page({"poster_name": card["name"], "poster_title": card["title"]})
    return _post_form_page()


def _clean_questions(raw) -> list[dict]:
    try:
        return easyapply.clean_questions(raw)
    except easyapply.QuestionError as e:
        raise ValidationError(str(e))


def _clean_quals(raw) -> list[dict]:
    try:
        return quals.clean(raw)
    except quals.QualError as e:
        raise ValidationError(str(e))


# Only the hiring organization may post its jobs: no staffing agencies, no second- or third-party recruiters.
_RECRUITER = re.compile(r"\b(on behalf of (?:our|a|my|an?) (?:valued |esteemed )?client|our client(?:'s)?|for (?:a|our) client|"
                        r"staffing (?:agency|firm|company|partner)|recruit(?:ing|ment) (?:agency|firm|company|partner)|"
                        r"(?:third|3rd|second|2nd)[- ]party recruit\w*|headhunter|placement (?:agency|firm)|talent acquisition (?:agency|firm)|"
                        r"we are a (?:recruit\w*|staffing) )", re.IGNORECASE)
RECRUITER_MSG = ("Only the company that is hiring can post its jobs here. Staffing agencies and second- or third-party "
                 "recruiters can't post on behalf of a client.")
_CO_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|ltd|co|corp|corporation|company|the|group|pllc|pa|plc)\b\.?", re.IGNORECASE)


def _co_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _CO_SUFFIX.sub("", (name or "").lower()))


def company_mismatch(employer_company: str, posted: str) -> bool:
    """True when an employer tries to post for an organization other than their own."""
    a, b = _co_key(employer_company), _co_key(posted)
    return bool(a and b and a not in b and b not in a)


def _clean_listing(f: dict, form: bool = False) -> dict:
    """Validate the fields of a listing. Raises ValidationError with a message fit to show the poster."""
    if form and f.get("direct") not in ("1", "on", 1, True):
        raise ValidationError("Confirm that you work directly for this company. " + RECRUITER_MSG)
    if _RECRUITER.search(" ".join(str(f.get(k) or "") for k in ("title", "company", "description", "poster_title"))):
        raise ValidationError(RECRUITER_MSG)
    return {
        "title": clean_text(f.get("title", ""), "title"),
        "company": clean_text(f.get("company", ""), "company"),
        "category": clean_choice(f.get("category", ""), CATEGORIES, "category", default="Other"),
        "work_type": clean_choice(f.get("work_type", ""), WORK_TYPES, "work_type"),
        "location": clean_text(f.get("location", ""), "location", required=False),
        "description": clean_text(f.get("description", ""), "description"),
        "apply_url": clean_url(f.get("apply_url", "")),
        "contact": clean_text(f.get("contact", ""), "contact", required=False),
        "easy_apply": 1 if f.get("easy_apply") in (1, True, "1", "on", "yes") else 0,
        "questions": _clean_questions(f.get("questions")),
        "requirements": _clean_quals(f.get("requirements")),
        "poster_name": clean_text(f.get("poster_name", ""), "poster_name", required=False),
        "poster_title": clean_text(f.get("poster_title", ""), "poster_title", required=False),
        "show_email": 1 if f.get("show_email") in (1, True, "1", "on", "yes") else 0,
        "expiry_days": _expiry_days(f.get("expiry_days")),
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
    poster_name: str = Form(""), poster_title: str = Form(""), show_email: str = Form(""), direct: str = Form(""),
    rkind: list[str] = Form([]), rlabel: list[str] = Form([]), rmust: list[str] = Form([]),
    easy_apply: str = Form(""), qtext: list[str] = Form([]), qkind: list[str] = Form([]), qreq: list[str] = Form([]),
    expiry_days: str = Form(""),
):
    enforce_rate_limit(request, submit_limiter, "post_submit")
    typed = {"expiry_days": expiry_days,"title": title, "company": company, "category": category, "work_type": work_type,
             "location": location, "description": description, "apply_url": apply_url, "contact": contact,
             "easy_apply": easy_apply, "poster_name": poster_name, "poster_title": poster_title,
             "show_email": show_email, "direct": direct,
             "requirements": [{"kind": (rkind[i] if i < len(rkind) else "skill"), "label": t, "must": (rmust[i] if i < len(rmust) else "0") == "1"}
                              for i, t in enumerate(rlabel[:quals.MAX_ITEMS])],
             "questions": [{"q": t, "kind": (qkind[i] if i < len(qkind) else "short"), "required": (qreq[i] if i < len(qreq) else "0") == "1"}
                           for i, t in enumerate(qtext[:easyapply.MAX_QUESTIONS])]}
    if not verify_csrf(csrf, "form"):
        return _post_form_page(typed, "That form had been open too long. Nothing was lost: your text is still here. "
                                      "Press Submit again to send it.", status=400)
    if website:
        # Honeypot filled: a bot. Show the normal confirmation, store nothing.
        return HTMLResponse(shell('<h2 class="page">Submitted for review</h2><div class="banner info">Thanks, your listing has been submitted.</div>'))

    try:
        clean = _clean_listing(typed, form=True)
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

    with store.db() as conn:
        ep = store.employer_profile(conn, user["id"]) or {}
        card = store.member_card(conn, user["id"])
    if company_mismatch(ep.get("company", ""), clean["company"]):
        return _post_form_page(typed, f"You can only post jobs for your own organization ({ep['company']}). " + RECRUITER_MSG, status=400)
    _poster_defaults(clean, ep, card)
    add_job(clean, employer_id=store.org_id(user), posted_by=user["id"])
    background.add_task(_mail_listing_received, user["email"], clean["title"])
    # Same confirmation regardless of scam score: the submitter is not told the internal verdict
    # (that is for the reviewer), only that it is in review.
    return HTMLResponse(shell(_SUBMITTED_BODY))


# ---------- listing controls that need the scanner: edit and duplicate (pause/close/expiry live in hiring.py) ----------

# Changing any of these re-scans the listing and sends it back to a reviewer; the rest change right away.
_REVIEW_FIELDS = ("title", "company", "description", "apply_url", "contact")


def _listing_values(j: dict) -> dict:
    """A stored listing as form values (for the edit form and for duplicating)."""
    v = {k: j.get(k) or "" for k in ("title", "company", "category", "work_type", "location", "description", "apply_url",
                                      "contact", "poster_name", "poster_title")}
    v.update(easy_apply=int(j.get("easy_apply") or 0), show_email=int(j.get("show_email") or 0), direct="1",
             questions=store.jload(j.get("questions"), []), requirements=store.jload(j.get("requirements"), []),
             expiry_days=int(j.get("expiry_days") or store.LISTING_DAYS_DEFAULT))
    return v


def _own_listing(user: dict, job_id: int) -> dict | None:
    """A listing of the company this employer works for (any member of the team can manage it)."""
    j = get_job(job_id)
    return j if j and j.get("employer_id") == store.org_id(user) else None


@app.get("/hiring/{job_id}/edit", response_class=HTMLResponse)
def listing_edit_form(job_id: int, request: Request):
    user = web.require_user(request, "employer")
    enforce_rate_limit(request, general_limiter, "listing_edit")
    j = _own_listing(user, job_id)
    if not j or j["review_status"] in ("rejected", "removed"):
        return web.page(ui.page_head("Listing can't be edited") + '<a class="b sec" href="/hiring">Your listings</a>', "Not found", active="/hiring", status=404)
    return _post_form_page(_listing_values(j), edit_id=job_id)


@app.post("/hiring/{job_id}/edit", response_class=HTMLResponse)
def listing_edit_save(job_id: int, request: Request, f=Depends(web.form_data)):
    user = web.require_user(request, "employer")
    enforce_rate_limit(request, submit_limiter, "listing_edit")
    one = lambda k: str(f.get(k) or "")                                       # noqa: E731
    many = lambda k: [str(x) for x in f.getlist(k)]                           # noqa: E731
    rkind, rlabel, rmust, qtext, qkind, qreq = (many(k) for k in ("rkind", "rlabel", "rmust", "qtext", "qkind", "qreq"))
    typed = {k: one(k) for k in ("title", "company", "category", "work_type", "location", "description", "apply_url", "contact",
                                  "easy_apply", "poster_name", "poster_title", "show_email", "direct")}
    typed["requirements"] = [{"kind": (rkind[i] if i < len(rkind) else "skill"), "label": t, "must": (rmust[i] if i < len(rmust) else "0") == "1"}
                             for i, t in enumerate(rlabel[:quals.MAX_ITEMS])]
    typed["questions"] = [{"q": t, "kind": (qkind[i] if i < len(qkind) else "short"), "required": (qreq[i] if i < len(qreq) else "0") == "1"}
                          for i, t in enumerate(qtext[:easyapply.MAX_QUESTIONS])]
    j = _own_listing(user, job_id)
    if not j or j["review_status"] in ("rejected", "removed"):
        return web.page(ui.page_head("Listing can't be edited") + '<a class="b sec" href="/hiring">Your listings</a>', "Not found", active="/hiring", status=404)
    if not web.csrf_ok(request, one("csrf")):
        return _post_form_page(typed, "That form had been open too long. Your changes are still here: press Save again.", status=400, edit_id=job_id)
    try:
        clean = _clean_listing(typed, form=True)
    except ValidationError as e:
        return _post_form_page(typed, str(e), status=400, edit_id=job_id)
    with store.db() as conn:
        ep = store.employer_profile(conn, user["id"]) or {}
        card = store.member_card(conn, j.get("posted_by") or user["id"])
    if company_mismatch(ep.get("company", ""), clean["company"]):
        return _post_form_page(typed, f"You can only post jobs for your own organization ({ep['company']}). " + RECRUITER_MSG, status=400, edit_id=job_id)
    _poster_defaults(clean, ep, card)
    old_q = store.jload(j.get("questions"), [])
    review = any(clean[k] != (j.get(k) or "") for k in _REVIEW_FIELDS) or clean["questions"] != old_q
    minor = {"category": clean["category"], "work_type": clean["work_type"], "location": clean["location"],
             "requirements": json.dumps(clean["requirements"]), "easy_apply": clean["easy_apply"],
             "poster_name": clean["poster_name"], "poster_title": clean["poster_title"], "show_email": clean["show_email"]}
    with closing(sqlite3.connect(DB_PATH)) as db:
        if review:
            result, scam_status, findings = _scan(clean, int(j["id"]))
            with store.db() as conn:
                defense.index_job(conn, int(j["id"]), "\n".join(clean.get(k, "") or "" for k in ("title", "company", "description", "apply_url", "contact")))
            full = dict(minor, title=clean["title"], company=clean["company"], description=clean["description"], apply_url=clean["apply_url"],
                        contact=clean["contact"], questions=json.dumps(clean["questions"]), score=result.score, band=result.band,
                        scam_status=scam_status, findings_json=json.dumps(findings), ruleset_version=result.ruleset_version,
                        review_status="pending", review_label=None, reviewed_at=None, expires_at=None, expiry_reminded=None)
            if j.get("expires_at") and j["review_status"] == "approved":
                # Keep the time it had left, so a re-approved listing doesn't quietly run longer than chosen.
                left = max(store.LISTING_DAYS_MIN, round((float(j["expires_at"]) - time.time()) / 86400))
                full["expiry_days"] = min(store.LISTING_DAYS_MAX, left)
        else:
            full = minor
        db.execute(f"UPDATE jobs SET {', '.join(k + ' = ?' for k in full)} WHERE id = ? AND employer_id = ?",
                   list(full.values()) + [job_id, store.org_id(user)])
        db.commit()
    return RedirectResponse(f"/hiring/{job_id}?done={'review' if review else 'saved'}", status_code=303)


@app.post("/hiring/{job_id}/duplicate")
def listing_duplicate(job_id: int, request: Request, background: BackgroundTasks, csrf: str = Form("")):
    """A new listing with the same fields (requirements, questions, poster). It is scanned and reviewed like any new one."""
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/hiring/{job_id}", status_code=303)
    enforce_rate_limit(request, submit_limiter, "listing_duplicate")
    j = _own_listing(user, job_id)
    if not j or j["review_status"] == "removed":
        return RedirectResponse("/hiring", status_code=303)
    try:
        clean = _clean_listing(_listing_values(j))
    except ValidationError:
        return RedirectResponse(f"/hiring/{job_id}/edit", status_code=303)
    new = add_job(clean, employer_id=store.org_id(user), posted_by=user["id"])
    background.add_task(_mail_listing_received, user["email"], clean["title"])
    return RedirectResponse(f"/hiring/{int(new['id'])}?done=copied", status_code=303)


def send_expiry_reminders(now: float | None = None) -> int:
    """Email each employer once, REMIND_DAYS before a live listing expires. Idempotent: jobs.expiry_reminded holds the
    expiry date the reminder was sent for, so re-running sends nothing new, and extending the listing re-arms it.
    Runs from daily_maintenance (startup, then every MAINTENANCE_HOURS). Returns how many were sent."""
    now = now or time.time()
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        due = [dict(r) for r in db.execute(
            f"SELECT j.id, j.title, j.expires_at, u.email FROM jobs j JOIN users u ON u.id = j.employer_id "
            f"WHERE {store.live_where('j')} AND j.expires_at IS NOT NULL AND j.expires_at <= ? "
            "AND (j.expiry_reminded IS NULL OR j.expiry_reminded != j.expires_at)", (now + store.REMIND_DAYS * 86400,)).fetchall()]
    sent = 0
    for j in due:
        days = max(1, round((j["expires_at"] - now) / 86400))
        with closing(sqlite3.connect(DB_PATH)) as db:           # claim it first, so two runs can't both send
            claimed = db.execute("UPDATE jobs SET expiry_reminded = expires_at WHERE id = ? AND "
                                 "(expiry_reminded IS NULL OR expiry_reminded != expires_at)", (j["id"],)).rowcount
            db.commit()
        if not claimed:
            continue
        mailer.send(j["email"], f'Your listing "{j["title"]}" ends in {days} day{"s" if days != 1 else ""}',
                    f'Your NoleCareerShield listing "{j["title"]}" comes off the board on '
                    f'{time.strftime("%B %d, %Y", time.gmtime(j["expires_at"]))}. Students who applied stay in your tracker.\n\n'
                    f'To keep it up, open it and choose Extend: {BASE_URL}/hiring/{int(j["id"])}\n'
                    "If you've filled the role, you can close it there too.\n\nNoleCareerShield")
        sent += 1
    return sent


mailer.copy_hook = emails.keep

# ---------- student network ----------

for _r in (profile_page.router, profiles.router, messaging.router, msgcheck.router, learning.router, assistant.router, resume_tools.router,
           feed.router, admin_extra.router, defense_web.router, cases.router, hiring.router, easyapply.router, network.router, jobboard.router, emails.router,
           events.router, teams.router, guardian.router):
    app.include_router(_r)


# ---------- trust pages ----------

def _contact_line() -> str:
    return (f'<a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a>' if CONTACT_EMAIL
            else "the site operator")


@app.get("/employers", response_class=HTMLResponse)
def employers_landing(request: Request):
    """The employer side door: what they get, then log in or create an account (separate from students)."""
    user = getattr(request.state, "user", None)
    if user and user["role"] == "employer":
        return RedirectResponse("/hiring", status_code=303)
    n_students = 0
    with store.db() as conn:
        n_students = conn.execute("SELECT COUNT(*) FROM student_profiles s JOIN users u ON u.id = s.user_id "
                                  "WHERE u.verified = 1 AND s.setup_step >= 1").fetchone()[0]
    reach = f"{n_students} FSU student{'s' if n_students != 1 else ''} on the board. " if n_students >= 25 else ""
    hero = ui.employer_hero(reach=reach) + ui.employer_gets() + ui.how_employers() + ui.employer_chapter()
    body = """<div class="card rv" style="margin:28px 0 40px"><h3 class="sec" style="margin-top:0">What students see about you</h3><p>Your company page shows your details, open listings and a trust score from 0 to 100 built from what we can check: reviewer approval, your email domain and website, how your listings were reviewed, how you answer students, and how complete your profile is. <a href="/privacy">How we handle data</a>.</p>
<p style="margin-top:12px"><a href="/post" style="color:var(--accent-ink);font-weight:600;text-decoration:none">Or write your first listing now and sign up when you send it →</a></p></div>"""
    return shell(f'<section class="home-list">{body}</section>{public_ui.employer_vault()}', hero=hero,
                 title="For employers — NoleCareerShield", wide=True)


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
<h3>Beyond the board</h3>
<ul><li><b>Profiles</b> that students control, including whether approved employers can find them.</li>
<li><b>Messaging</b> between students and reviewed employers, with every message scanned for scam signs.</li>
<li><b>Quick apply</b> on listings that choose it: a short form filled from your profile, sent only to that employer.</li>
<li><b>A network</b> where students connect with each other and follow the companies they like, with no student-to-student inbox.</li>
<li><b>A career assistant</b> that answers in plain words and only suggests listings that passed review.</li>
<li><b>A resume studio</b> that scores a resume, rewrites weak lines without inventing anything, and tailors it to a job.</li>
<li><b>A scam checker</b> for any message a student receives, here or anywhere else.</li>
<li><b>An FSU-only feed</b> where employer posts must be opportunities or advice for FSU students.</li></ul>
<h3>What this is not</h3>
<p>A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information. This is an independent student project and is not affiliated with Florida State University.</p></div>"""
    return shell(body, title="About — NoleCareerShield")


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    bot = ("<li>The sign-up and log-in pages load a bot check from Cloudflare (Turnstile), which sees your IP address and browser details.</li>"
           if security.turnstile_enabled() else "")
    ai_on = ai.enabled()
    beta = ("<li>While the site is in private beta, entering the access code sets a cookie that remembers it for 90 days.</li>"
            if BETA_CODE else "")
    ai_block = ("""<h3>AI features</h3>
<ul><li>The job assistant, resume review, resume tailoring, the scam checker's second opinion and feed moderation can use Claude, made by Anthropic.</li>
<li>Text is sent to Anthropic only when you use one of those features: your question, your resume or profile summary, the job you picked, or the message you asked us to check. Anthropic processes it to answer and, under its commercial terms, does not use it to train models.</li>
<li>Nothing is sent for browsing, messaging or anything you don't ask the AI to do. Each account has a daily limit.</li></ul>""" if ai_on else
                """<h3>AI features</h3><ul><li>AI features are currently off. The job assistant, resume tools and scam checker run entirely on this site's own rules, so nothing is sent to an AI provider.</li></ul>""")
    body = f"""<a class="back" href="/">← Home</a><h2 class="page">Privacy</h2>
<div class="prose"><p class="muted">Last updated October 3, 2026.</p>
<p>Short version: browsing is anonymous, you choose what goes on your profile and who sees it, we never sell your data or use it for advertising, and you can download or delete everything at any time.</p>
<h3>Anyone browsing</h3>
<ul><li>Job listings are for signed-in FSU students and employers. Visitors see only a few titles on the home page.</li>
<li>Anyone can use the scam checker without an account, up to 10 checks a day. Visitors see the verdict and the main reasons; signed-in FSU students see every signal and the exact words it caught. No cookies are set for browsing. Pages with a log-in, sign-up or scam-check form set one security cookie, which stops other sites from submitting those forms in your name.</li>
<li>If you tell us which school you'd like NoleCareerShield at, we store only the school name.</li>
<li>No analytics, advertising or trackers. Pages load only from this site, with no third-party fonts.</li></ul>
<h3>Students</h3>
<ul><li>A student account needs an @fsu.edu email address, confirmed by a link we send, and a password. We store the address and a salted hash of the password, never the password itself.</li>
<li>If FSU single sign-on is available, you can sign in on FSU's own page instead. FSU confirms your @fsu.edu address to us; we never see your FSU password, and we keep only the address.</li>
<li>Your profile holds what you type in: the name you choose to show, major, graduation term, headline, skills, interests and optional links. We never ask for a student ID, date of birth or SSN.</li>
<li>If you add a resume, we keep its text (not the file) and any versions you save. Only you can see it unless you turn on "share my resume with approved employers".</li>
<li>Other students can see your name, school, major, class year, headline, about, skills and what you're looking for, never your experience, education entries, projects or resume. Employers see your full profile only if our reviewers approved them and you either turned on "let approved employers find me" or are already talking with them.</li>
<li>If you're visible to approved employers, they can see how well you fit their listings: the same fit score and evidence you see on the listing, worked out from your profile.</li>
<li>If you add a resume, we can fill your profile sections from it. You can edit or delete any entry.</li>
<li>Each listing shows a fit score calculated from your profile when you open it. It isn't stored.</li>
<li>We count which listings you open and whether you press Apply, so employers can see totals (for example "40 students viewed, 12 clicked Apply"). Employers never see who viewed or clicked.</li>
<li>If you message an employer about a listing, or they invite you or save you from their matches, you appear in that employer's candidate list for it, where they can add a stage and a private note.</li>
<li><b>Quick apply.</b> When you apply on a listing that collects applications here, that employer (and only that employer) sees your name, major, graduation term, profile links, your answers and note, and your resume only if you tick it. Never your email. Applying also lets that employer open your profile and message you. You can withdraw an application any time, which deletes the answers.</li>
<li><b>Career assistant chats.</b> Your questions and its answers are saved in your account so you can come back to them. Only you can see them. You can delete any chat from Chat history, they are removed after 180 days without use, and they are included in your data download and deleted with your account.</li>
<li><b>What the assistant remembers.</b> When you tell the Career assistant a goal or preference (like the roles you want or when you graduate), it can save a short note so later answers fit you. It never saves ID or account numbers, passwords, contact details, health, religion, sexuality, immigration status, finances or criminal history. It also uses your thumbs up and down and the jobs you save, view and apply to as light hints. You can see, delete or clear every note at What I remember (in the assistant); notes are in your data download, deleted with your account, and removed after a year.</li>
<li><b>Connections and follows.</b> A connection is a mutual link between two students that shows as a count and as mutual connections on profiles. It doesn't let anyone message you. You can switch off connection requests and "People you may know" in your profile settings. Following a company adds its listings to a filter for you; the company sees how many students follow it, never who.</li></ul>
<h3>Messages</h3>
<ul><li>Messages are only between students and employers our reviewers approved. Every message is scanned for scam signs when it is sent. Messages that match a pattern only scams use are held for a reviewer instead of being delivered; others may be delivered with a warning.</li>
<li>Reviewers read a message only when it was held by the scanner or reported by someone in the conversation.</li>
<li>Email notifications say only that a message is waiting, never what it says.</li></ul>
<h3>The FSU feed</h3>
<ul><li>Only signed-in FSU students and approved employers can read or post. Employer posts are reviewed before they appear and must be relevant to FSU students.</li>
<li>Anyone can report a post; reported posts are checked by a reviewer. Rejected and removed posts are deleted after 30 days.</li></ul>
<h3>Scam checker</h3>
<ul><li>Messages and listings you paste into the scam checker are not saved, unless you press "Send this to our reviewers" to help improve the detector.</li>
<li>The exception: a small random share (about 3%) of checks that come out "no known scam signs" or "be careful" is kept so a reviewer can double-check that the detector didn't miss a scam. It's kept without your name, with email addresses and phone numbers masked, for up to a year.</li>
<li>Checks you send to reviewers are kept for up to a year, without your name. When a reviewer confirms whether one was a scam, that text (with email addresses and phone numbers masked) can be used to retrain the detector.</li>
<li>Files you attach to a check (an offer letter, a photo of a check, a screenshot) are read once to check them and never stored.</li>
<li>If you forward an email to our check address, we reply to you with the verdict. We keep the forwarded message for our reviewers, but not your email address.</li>
<li>Contact details in scam reports and listings (phone numbers, emails, web domains, chat handles, crypto wallets) are kept as one-way keyed codes, so we can spot a scammer who comes back with new wording. When a reviewer confirms a scam, those codes may be shared with partner schools; the codes can't be turned back into the details.</li>
<li>When outside checks are on, the web addresses and phone numbers in what you check are looked up with reputation services (for example domain registration dates and malware-link lists). The rest of your text is not sent.</li></ul>
{ai_block}
<h3>People who post a job</h3>
<ul><li>You need an employer account: an email address (confirmed by a link) and a password, stored the same way as above, plus a company profile that a reviewer approves before you can message students or post to the feed.</li>
<li>We store what you type into the listing form, the account that sent it, the automated scam score and the review decision. The contact field is shown publicly if the listing is approved.</li>
<li>Approved employers get a trust score (0-100, higher is safer) that signed-in students see on the company page and listings. It comes only from what this site can check: reviewer approval, your email domain and website, how your listings were reviewed, scanner flags and reports on your messages, how you answer students, and how complete your profile is. You can see how yours is worked out, and how to raise it, on your company profile.</li>
<li>Rejected and removed listings are deleted automatically after {PURGE_REJECTED_DAYS} days. Approved listings come off the board when they expire ({store.LISTING_DAYS_DEFAULT} days after approval unless the employer picks {store.LISTING_DAYS_MIN} to {store.LISTING_DAYS_MAX}), or when the employer pauses or closes them.</li>
<li>If you fill in the form before logging in, the listing is kept for up to 3 days so it can be sent when you finish, then deleted.</li></ul>
<h3>Your data</h3>
<ul><li>On your profile page you can download everything we store about your account as a file, and delete your account. Deleting removes your profile, resume, versions, posts and comments, and blanks the messages you sent.</li>
<li>Accounts that never confirm their email are deleted after 7 days. Questions: {_contact_line()}.</li></ul>
<h3>Cookies and logs</h3>
<ul><li>Logging in sets one session cookie (HttpOnly, 7 days). Sending a listing before you log in sets a short-lived cookie that holds only a random reference to your saved listing.</li>
<li>Logging in also sets a "known browser" cookie (HttpOnly, about a year) holding a random browser code and your account number, signed so it can't be forged. It only means that if someone else keeps guessing your password, your own browser can still log you in. It isn't used to track you.</li>
<li>Signing in with FSU single sign-on sets a short-lived cookie that's only used to finish that sign-in.</li>
{beta}{bot}<li>Server logs may briefly hold IP addresses for security and abuse prevention. To enforce rate limits (for example, 5 failed log-ins per 15 minutes), the server keeps a record of recent requests by IP address and deletes it within two days.</li>
<li>We send email only for account confirmation, password reset, listing receipts and "you have a new message" notices. No marketing.</li></ul>
<h3>Reviewers</h3>
<p>The review queue uses a separate session cookie, set only after a reviewer signs in, marked HttpOnly and expired after 8 hours.</p>
<p>The rules for using the site are in the <a href="/terms">Terms of Use</a>.</p>
<h3>Who runs this and who helps</h3>
<ul><li>NoleCareerShield is an independent student project. It isn't run by, or affiliated with, Florida State University, and FSU doesn't send us any student records.</li>
<li>We never sell or rent personal data, and never share it for advertising.</li>
<li>Services that handle data for us: our hosting provider (the site and its database run on servers in the United States), our email provider (to send the emails listed above){", Anthropic (only for the AI features above)" if ai_on else ""}{", Cloudflare (the bot check)" if security.turnstile_enabled() else ""}{", and Microsoft (FSU single sign-on)" if sso.enabled() else ""}. They may only use it to provide their service to us.</li>
<li>We'd share information with authorities only when the law requires it, or to report a confirmed scam targeting students.</li>
<li>If this policy changes, we'll update the date at the top. If a change affects what we do with data you've already given us, we'll tell you by email or on the site first.</li></ul></div>"""
    return shell(body, title="Privacy — NoleCareerShield")


TERMS_UPDATED = "October 4, 2026"


@app.get("/terms", response_class=HTMLResponse)
def terms():
    body = f"""<a class="back" href="/">← Home</a><h2 class="page">Terms of Use</h2>
<div class="prose"><p class="muted">Last updated {TERMS_UPDATED}.</p>
<p>These terms cover your use of NoleCareerShield, a job board for Florida State University students with a built-in scam
checker. By creating an account or using the site you agree to them. How we handle your data is in the
<a href="/privacy">Privacy Policy</a>, which is part of these terms.</p>

<h3>1. Who runs this</h3>
<p>NoleCareerShield is an independent student project. It is not run by, sponsored by or endorsed by Florida State
University, and it doesn't use FSU's trademarks or logos. Questions about these terms go to {_contact_line()}.</p>

<h3>2. Who can use it</h3>
<ul><li><b>Students:</b> you need an @fsu.edu email address that you control. Accounts are personal: don't share yours or
use someone else's.</li>
<li><b>Employers:</b> you must work for the organization you post for and be authorized to hire on its behalf. Third-party
recruiters, staffing agencies and anyone posting "on behalf of a client" are not allowed. Your company profile is reviewed
before you can message students or post to the feed, and approval can be withdrawn.</li>
<li>You must be at least 18, or have a parent or guardian's permission, to use the site.</li>
<li>Keep your password private and tell us right away if you think someone else has used your account. You're responsible
for what happens under your account.</li></ul>

<h3>3. Rules for employers</h3>
<ul><li>Post only real, currently open positions at your own organization, with an honest description of the work, pay and
location.</li>
<li>Never charge students anything: no fees for applying, training, equipment, background checks or "starter kits," and no
requests for payment, gift cards, crypto or bank transfers.</li>
<li>Don't ask for Social Security numbers, bank details, ID photos or similar sensitive information before a real job
offer, and never through site messages.</li>
<li>Follow employment and anti-discrimination laws. Don't post listings that discriminate based on race, color, religion,
sex, sexual orientation, gender identity, national origin, age, disability, veteran status or any other protected
characteristic.</li>
<li>Use what you learn about students only to recruit for the role they were considered for. Don't sell it, add students to
marketing lists or contact them about unrelated products.</li>
<li>Pyramid schemes, multi-level marketing, commission-only "opportunities," reshipping, payment processing and other
schemes are not jobs and will be removed.</li></ul>

<h3>4. Rules for everyone</h3>
<ul><li>Don't post anything false, misleading, harassing, hateful, sexually explicit, threatening or illegal, or anything
that infringes someone else's rights.</li>
<li>Don't impersonate a person, company, FSU or any of its offices.</li>
<li>Don't scrape the site, collect other users' information, send spam, or use bots or automated tools against it.</li>
<li>Don't try to get around the scam scanner, the rate limits, reviews or any other security measure, or probe or test
the site's security without our written permission. If you find a security problem, please report it to
{_contact_line()}.</li>
<li>Messages are scanned for scam signs and some are held for a reviewer, as the Privacy Policy explains.</li></ul>

<h3>5. Your content</h3>
<p>You keep ownership of what you post: your profile, resume, listings, messages and feed posts. You give us permission to
store, display and process it only as needed to run the site, for example showing your profile to the people you've
chosen, scanning messages for scams, and showing listings to students. That permission ends when you delete the content or
your account, except for copies we're required to keep or that were already shared with someone you chose. You're
responsible for having the right to post what you post.</p>

<h3>6. The scam checker, scores and AI features</h3>
<ul><li>The scam checker, risk scores, employer trust scores, fit scores and resume feedback are automated estimates meant
to help you decide. They are not guarantees. A clean result doesn't prove a job is real, and a warning doesn't prove it's
a scam. Always confirm an employer through their own website before sharing personal information or money.</li>
<li>Listings are reviewed before they appear, but we can't verify everything an employer says. Decisions about applying,
interviewing and accepting offers are yours.</li>
<li>AI features can make mistakes. Check anything important they tell you, and review AI-written resume text before you
send it to an employer.</li></ul>

<h3>7. Removing content and accounts</h3>
<p>We may review, hold, edit the visibility of, or remove any listing, message, post or account that breaks these terms or
looks like a scam, and we may suspend or close accounts, with or without notice where needed to protect students. You can
delete your account at any time from your profile. If we remove something by mistake, contact us and we'll take another
look.</p>

<h3>8. Reporting scams</h3>
<p>If you think a listing or message is a scam, use Report or the <a href="/report">report page</a>. If you've lost money or
shared banking details, contact your bank right away and report it at reportfraud.ftc.gov.</p>

<h3>9. No warranties</h3>
<p>The site is provided "as is" and "as available." To the fullest extent the law allows, we make no promises that it will
be uninterrupted, error-free or secure, that listings or employers are genuine, or that you'll get a job or any other
result.</p>

<h3>10. Limits on liability</h3>
<p>To the fullest extent the law allows, we aren't liable for indirect, incidental or consequential losses, or for losses
caused by employers, other users or third parties, including scams that get past our checks. Nothing in these terms limits
liability that can't be limited by law.</p>

<h3>11. If you break these terms</h3>
<p>If your use of the site breaks these terms or the law and that causes a claim against us, you agree to cover the
reasonable costs of that claim.</p>

<h3>12. Governing law</h3>
<p>These terms are governed by the laws of the State of Florida and applicable U.S. federal law. Any dispute will be
handled in the state or federal courts located in Leon County, Florida, unless the law gives you a right to bring it
somewhere else.</p>

<h3>13. Changes</h3>
<p>We may update these terms. The date at the top shows the latest version. If a change is significant, we'll tell you on
the site or by email before it takes effect. Using the site after a change means you accept the updated terms.</p></div>"""
    return shell(body, title="Terms of Use — NoleCareerShield")


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


def _vault_fine() -> list[str]:
    """The fine print under the sign-in card: only what this site actually does. HTTPS is claimed only in production
    (HSTS is sent there); passwords are scrypt-hashed (accounts.hash_password); sessions end after
    accounts.SESSION_TTL; the privacy page promises no analytics, advertising or trackers."""
    days = accounts.SESSION_TTL // 86400
    return (["HTTPS"] if IS_PROD else []) + ["Passwords hashed", f"{days}-day sessions", "No trackers"]


def _vault_response(card: str, title: str, role: str = "student", status: int = 200) -> HTMLResponse:
    return HTMLResponse(shell(public_ui.vault(card, role), title=title + " — NoleCareerShield", scripts=True, wide=True),
                        status_code=status)


def _auth_page(heading: str, body: str, *, title: str | None = None, status: int = 200, sub: str = "",
               role: str = "student", kicker: str = "", icon: str = "lock") -> HTMLResponse:
    """Every account page is the vault: the brand column on the left, this card on the right. `sub` is HTML."""
    card = public_ui.vault_card(esc(heading), body, kicker=kicker, sub=sub, icon=icon,
                                fine=public_ui.fine_print(_vault_fine()))
    return _vault_response(card, title or heading, role, status)


def _sso_button(email: str = "", next_: str = "") -> str:
    """FSU single sign-on, only when it is configured (sso.enabled)."""
    if not sso.enabled():
        return ""
    return (f'<form method="post" action="/sso/start" class="vx-alt">{_csrf_input()}<input type="hidden" name="email" value="{esc(email)}">'
            f'<input type="hidden" name="next" value="{esc(next_)}"><button class="vx-sso" type="submit">Continue with {esc(sso.NAME)} single sign-on</button></form>')


def _fsu_ok(email: str) -> bool:
    """True only for a value the server has checked is an @fsu.edu address (the field's green check)."""
    try:
        return accounts.is_fsu_email(accounts.normalize_email(email))
    except ValueError:
        return False


def _other_side(role: str) -> str:
    """Students and employers have separate doors; each page points to the other one."""
    return ('<p class="start-foot" style="text-align:center">Hiring? <a href="/employers">Employer log in or sign up →</a></p>' if role == "student" else
            '<p class="start-foot" style="text-align:center">Student? <a href="/login">Log in with your @fsu.edu email →</a></p>')


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
    return value if _NEXT_OK.fullmatch(value) else ""


_NEXT_OK = re.compile(r"/job/\d{1,9}|/post|/jobs|/feed(?:/\d{1,9})?|/assistant|/resume|/check|/talent|/profile(?:/setup(?:/\d)?)?"
                      r"|/messages(?:/\d{1,9})?|/messages/new\?to=\d{1,9}(?:&job=\d{1,9})?|/u/\d{1,9}|/company/\d{1,9}")


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
    with closing(sqlite3.connect(DB_PATH)) as db:
        user = accounts.session_user(db, token)
    if user:        # remember this browser for this account (see security.login_identity)
        resp.set_cookie(security.DEVICE_COOKIE, security.device_cookie_for(user["id"]), httponly=True, samesite="lax",
                        secure=IS_PROD, max_age=400 * 24 * 3600, path="/")
    return resp


def _clear_draft_cookie(resp):
    resp.delete_cookie("draft", path="/")
    return resp


def _poster_defaults(clean: dict, ep: dict, card: dict | None = None) -> None:
    """A listing always names the person who posted it: the team member's own name and title (card), falling back
    to the organization's contact."""
    card = card or {}
    if not clean.get("poster_name"):
        clean["poster_name"] = card.get("name") or ep.get("contact_name", "")
    if not clean.get("poster_title"):
        clean["poster_title"] = (card.get("title") if card.get("name") else "") or ep.get("contact_title", "")


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
    with store.db() as conn:
        ep = store.employer_profile(conn, user["id"]) or {}
        card = store.member_card(conn, user["id"])
        org = store.org_of(conn, user["id"])
    if company_mismatch(ep.get("company", ""), clean["company"]):
        return False
    _poster_defaults(clean, ep, card)
    add_job(clean, employer_id=org, posted_by=user["id"])
    background.add_task(_mail_listing_received, user["email"], clean["title"])
    return True


# --- one place to start: email first, like Handshake ---

def _start_page(email: str = "", error: str = "", next_: str = "", status: int = 200) -> HTMLResponse:
    """Step one of signing in: just the email. The address decides the path (see login_start)."""
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    note = ('<div class="banner info">Log in with your FSU student account to see how to apply.</div>'
            if next_.startswith("/job/") else "")
    sso_btn = _sso_button(next_=next_)
    field = public_ui.email_field(email, label="Email", fid="s-email", hint="Students: @fsu.edu",
                                  verified=bool(email) and _fsu_ok(email), placeholder="you@fsu.edu", autofocus=True)
    body = f"""{note}{err}<form method="post" action="/login">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
{field}
<button class="submit-btn wide" type="submit">Continue with email</button></form>
{f'<div class="or"><span>or</span></div>{sso_btn}' if sso_btn else ""}
<p class="start-foot">Hiring? <a href="/employers">Employer log in or sign up →</a></p>"""
    card = public_ui.vault_card("Enter the vault", body, kicker="Log in or sign up",
                                sub="Students use their @fsu.edu address.",
                                fine=public_ui.fine_print(_vault_fine()))
    return _vault_response(card, "Log in or sign up", "student", status)


def _sso_welcome(email: str, next_: str) -> HTMLResponse:
    hidden = f'{_csrf_input()}<input type="hidden" name="email" value="{esc(email)}"><input type="hidden" name="next" value="{esc(next_)}">'
    body = f"""<form method="post" action="/sso/start">{hidden}<button class="submit-btn wide" type="submit">Continue to {esc(sso.NAME)} single sign-on →</button></form>
<div class="or"><span>or</span></div>
<form method="post" action="/login" class="vx-alt">{hidden}<input type="hidden" name="how" value="password">
<button class="outline-btn" type="submit">Log in another way</button></form>
<p class="fine">You'll sign in on {esc(sso.NAME)}'s own page, with Duo if your account uses it. NoleCareerShield never sees your {esc(sso.NAME)} password.</p>"""
    sub = (f'Use your {esc(sso.NAME)} account to log in as <b>{esc(email)}</b> '
           f'<a href="/login{"?next=" + esc(next_) if next_ else ""}">Edit</a>')
    card = public_ui.vault_card("Enter the vault", body, kicker="Welcome to NoleCareerShield", sub=sub,
                                fine=public_ui.fine_print(_vault_fine()))
    return _vault_response(card, "Welcome")


@app.get("/login", response_class=HTMLResponse)
def login_start_page(request: Request, next: str = ""):
    return _start_page(next_=_safe_next(next))


@app.post("/login", response_class=HTMLResponse)
def login_start(request: Request, email: str = Form(""), csrf: str = Form(""), next: str = Form(""), how: str = Form("")):
    """Step one: the address decides the path. @fsu.edu goes to FSU single sign-on (when it is set up) or the student
    password page; anything else is an employer. The email never goes into a URL."""
    enforce_rate_limit(request, general_limiter, "login_start")
    nx = _safe_next(next)
    if not verify_csrf(csrf, "form"):
        return _start_page(email[:254], next_=nx, status=400, error="That page had been open too long. Please try again.")
    try:
        addr = accounts.normalize_email(email)
    except ValueError:
        return _start_page(email[:254], next_=nx, status=400, error="Enter a valid email address.")
    if accounts.is_fsu_email(addr):
        if sso.enabled() and how != "password":
            return _sso_welcome(addr, nx)
        return _login_page("student", email=addr, next_=nx)
    return _login_page("employer", email=addr, next_=nx,
                       notice="That isn't an @fsu.edu address, so this is an employer login. Students: go back and use your FSU email.")


@app.post("/sso/start")
def sso_start(request: Request, email: str = Form(""), csrf: str = Form(""), next: str = Form("")):
    # Log-in lockout (failed attempts per IP) is applied to every log-in route by security.RequestGuard.
    if not sso.enabled():
        return RedirectResponse("/login", status_code=303)
    if not verify_csrf(csrf, "form"):
        return _start_page(status=400, error="That page had been open too long. Please try again.")
    try:
        addr = accounts.normalize_email(email)
    except ValueError:
        addr = ""
    url, cookie = sso.start(addr if accounts.is_fsu_email(addr) else "", _safe_next(next))
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(sso.COOKIE, cookie, max_age=sso.COOKIE_TTL, httponly=True, secure=IS_PROD, samesite="lax", path="/sso")
    return resp


@app.get("/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    # Log-in lockout (failed attempts per IP) is applied to every log-in route by security.RequestGuard.
    if error:
        resp = _start_page(status=400, error="FSU sign-in was cancelled or didn't finish. Try again, or log in another way.")
    else:
        try:
            email, nx = sso.finish(code[:4000], state[:200], request.cookies.get(sso.COOKIE))
        except sso.SSOError as e:
            resp = _start_page(status=400, error=str(e))
        else:
            with closing(sqlite3.connect(DB_PATH)) as db:
                user = sso.user_for(db, email)
                token = accounts.create_session(db, user["id"])
            resp = _login_cookie(RedirectResponse(_safe_next(nx) or _home_for(user), status_code=303), token)
    resp.delete_cookie(sso.COOKIE, path="/sso")
    return resp


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
    student = role == "student"
    a_an = "a student" if student else "an employer"
    field = (public_ui.email_field(email, label="University email", hint="Use your @fsu.edu address",
                                   verified=bool(email) and _fsu_ok(email), placeholder="you@fsu.edu") if student
             else public_ui.email_field(email, label="Work email", placeholder="you@company.com"))
    sso_btn = _sso_button(email if _fsu_ok(email) else "", next_) if student else ""
    body = f"""{note}{err}{resend}
<form method="post" action="/login/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
{field}
{_pw_field(forgot_role=role)}
{_turnstile_widget()}<button class="submit-btn wide" type="submit">Sign in securely</button></form>
<div class="or"><span>or</span></div>{sso_btn}<a class="outline-btn" href="/signup/{role}{"?next=" + esc(next_) if next_ else ""}">Create {a_an} account</a>{_other_side(role)}"""
    kicker = "Student log in" if student else "Employer log in"
    sub = "Sign in with your Florida State account." if student else "Sign in with your work email."
    return _auth_page("Enter the vault", body, title=kicker, kicker=kicker, sub=sub, role=role, status=status)


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
    # Log-in lockout (failed attempts per IP) is applied to every log-in route by security.RequestGuard.
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
    with closing(sqlite3.connect(DB_PATH)) as db:
        user = accounts.get_user(db, addr, role)
    who = security.login_identity(security.client_ip(request), request.cookies.get(security.DEVICE_COOKIE),
                                  user["id"] if user else None)
    verdict, slots = security.account_attempt(role, addr, who)
    too_many = HTTPException(status_code=429, detail="Too many failed attempts for this account. Try again in a few minutes.",
                             headers={"Retry-After": "600"})
    if verdict == "blocked":
        raise too_many
    good = accounts.verify_password(password[:accounts.PW_MAX], user["pw_hash"] if user else accounts.DUMMY_HASH)
    if not (user and good):
        if verdict == "only_correct":
            raise too_many
        return _login_page(role, email=addr, next_=nx, status=401, error=generic)
    security.account_success(slots)
    if not user["verified"]:
        return _login_page(role, email=addr, next_=nx, status=403, unverified=True,
                           error="Confirm your email first. We sent you a link when you signed up.")
    with closing(sqlite3.connect(DB_PATH)) as db:
        token = accounts.create_session(db, user["id"])
    if _resume_draft(request, user, background):
        resp = RedirectResponse("/submitted", status_code=303)
        _clear_draft_cookie(resp)
    else:
        resp = RedirectResponse(nx or _home_for(user), status_code=303)
    return _login_cookie(resp, token)


def _home_for(user: dict) -> str:
    """Where someone lands after logging in: profile setup until it is done, then home."""
    with store.db() as conn:
        if user["role"] == "student":
            p = store.student_profile(conn, user["id"])
            done = bool(p and p.get("setup_step"))
        else:
            p = store.employer_profile(conn, user["id"])
            done = bool(p and p.get("company"))
    return "/" if done else "/profile/setup"


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
        sub = "Use your @fsu.edu email. We send a link to confirm it."
        field = public_ui.email_field(email, label="University email", hint="Use your @fsu.edu address",
                                      verified=bool(email) and _fsu_ok(email), placeholder="you@fsu.edu")
    else:
        sub = "Any email works. We send a link to confirm it before you can post."
        field = public_ui.email_field(email, label="Work email", placeholder="you@company.com")
    body = f"""{err}
<form method="post" action="/signup/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="hp" aria-hidden="true"><label for="f-website">Leave this empty</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
{field}
{_pw_field(autocomplete="new-password", check=True)}{_RULES_LIST}
{_pw_field(fid="f-password2", name="password2", label="Confirm password", autocomplete="new-password")}
{_turnstile_widget()}<p class="fine">By creating an account you agree to the <a href="/terms">Terms of Use</a> and <a href="/privacy">Privacy Policy</a>.</p><button class="submit-btn wide" type="submit">Create account</button></form>
<div class="or"><span>or</span></div><a class="outline-btn" href="/login/{role}{"?next=" + esc(next_) if next_ else ""}">I already have an account</a>{_other_side(role)}"""
    return _auth_page("Create your student account" if role == "student" else "Create your employer account", body, sub=sub,
                      status=status, role=role, kicker="Student sign-up" if role == "student" else "Employer sign-up", icon="key")


@app.get("/signup/{role}", response_class=HTMLResponse)
def signup_form(role: str, next: str = ""):
    return _signup_page(_role(role), next_=_safe_next(next))


def _check_your_email(email: str, role: str) -> HTMLResponse:
    body = (f'<div class="banner info">If that address can receive an account, we just sent a confirmation link to '
            f'<b>{esc(email)}</b>. It works for 24 hours. Check your spam folder if it does not arrive in a few minutes.</div>'
            f'<p class="fine">Wrong address? <a href="/signup/{role}">Start over</a>.</p>')
    return _auth_page("Check your email", body, title="Check your email", role=role, kicker="One more step", icon="mail")


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
    return _auth_page("Check your email", body, title="Check your email", role=role, kicker="One more step", icon="mail")


# --- confirm email ---

def _link_problem(kind: str) -> HTMLResponse:
    body = (f'<div class="banner warning">That link has expired or was already used.</div>'
            f'<p class="fine"><a href="/login">Log in</a> to ask for a new {kind}.</p>')
    return _auth_page("Link not valid", body, status=400, kicker="Link problem", icon="alert")


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
    body = (f'{err}<form method="post" action="/verify">{_csrf_input()}<input type="hidden" name="token" value="{esc(token)}">'
            f'{_pw_field(label="Password")}'
            '<button class="submit-btn wide" type="submit">Confirm my email</button></form>'
            '<p class="fine">Don\'t remember it? Sign up again with the same email to set a new one.</p>')
    return _auth_page("Confirm your email", body, status=status, kicker="Almost in", icon="mail",
                      sub="Enter the password you chose when you signed up. This makes sure the account is really yours.")


@app.post("/verify")
def verify_submit(request: Request, background: BackgroundTasks, token: str = Form(""),
                  password: str = Form(""), csrf: str = Form("")):
    # Log-in lockout (failed attempts per IP) is applied to every log-in route by security.RequestGuard.
    if not verify_csrf(csrf, "form"):
        return _link_problem("confirmation email")
    with closing(sqlite3.connect(DB_PATH)) as db:
        peeked = accounts.peek_token(db, token, "verify")
        owner = accounts.get_user_by_id(db, peeked) if peeked else None
    if not owner:
        return _link_problem("confirmation email")
    verdict, slots = security.account_attempt(owner["role"], owner["email"], security.login_identity(security.client_ip(request), request.cookies.get(security.DEVICE_COOKIE), owner["id"]))
    too_many = HTTPException(status_code=429, detail="Too many failed attempts for this account. Try again in a few minutes.",
                             headers={"Retry-After": "600"})
    if verdict == "blocked":
        raise too_many
    if not accounts.verify_password(password[:accounts.PW_MAX], owner["pw_hash"]):
        if verdict == "only_correct":
            raise too_many
        return _confirm_page(token, "That is not the password this account was created with.", 401)
    security.account_success(slots)
    with closing(sqlite3.connect(DB_PATH)) as db:
        uid = accounts.consume_token(db, token, "verify")
        if not uid:
            return _link_problem("confirmation email")
        accounts.mark_verified(db, uid)
        user = accounts.get_user_by_id(db, uid)
        session = accounts.create_session(db, uid)
    sent = _resume_draft(request, user, background)
    if user["role"] == "employer":
        msg = ("Your listing was sent for review. A person checks every listing before it appears. "
               "Next, tell students about your organization." if sent
               else "Next, set up your company profile. A reviewer approves it before you can message students or post to the feed.")
        cta = '<a class="apply-btn" href="/profile/setup">Set up company profile</a>'
        with store.db() as conn:
            if not sent and teams.pending_for(conn, user["email"]):
                # Invited to a company's team: joining it comes first (their own company profile would be empty anyway).
                msg = "You've been invited to join a company's hiring team. Accept the invite to start."
                cta = '<a class="apply-btn" href="/team/join">See your team invite</a>'
    else:
        msg = "Next, set up your profile. It takes about two minutes and powers your job matches."
        cta = '<a class="apply-btn" href="/profile/setup">Set up my profile</a>'
    body = f'<div class="banner verified">Email confirmed. You are logged in. {esc(msg)}</div>{cta}'
    _viewer.set({"user": user, "token": session})       # this response is the first page they see logged in
    resp = _auth_page("You're in", body, title="Email confirmed", role=user["role"], kicker="Email confirmed", icon="check")
    if sent:
        _clear_draft_cookie(resp)
    return _login_cookie(resp, session)


# --- forgot / reset password ---

@app.get("/forgot/{role}", response_class=HTMLResponse)
def forgot_form(role: str):
    _role(role)
    field = public_ui.email_field(label="University email" if role == "student" else "Work email",
                                  placeholder="you@fsu.edu" if role == "student" else "you@company.com")
    body = (f'<form method="post" action="/forgot/{role}">{_csrf_input()}{field}'
            f'{_turnstile_widget()}<button class="submit-btn wide" type="submit">Send reset link</button></form>'
            f'<p class="fine"><a href="/login/{role}">Back to log in</a></p>')
    return _auth_page("Forgot password", body, role=role, kicker="Student account" if role == "student" else "Employer account",
                      icon="key", sub="Enter your email and we will send a link to choose a new password.")


@app.post("/forgot/{role}")
def forgot_submit(role: str, request: Request, background: BackgroundTasks, email: str = Form(""),
                  csrf: str = Form(""), cf_token: str = Form("", alias="cf-turnstile-response")):
    _role(role)
    enforce_rate_limit(request, signup_limiter, "forgot")
    if not verify_csrf(csrf, "form") or not security.verify_turnstile(cf_token, security.client_ip(request)):
        return _auth_page("Forgot password", '<div class="banner warning">That did not go through. Please go back and try again.</div>',
                          status=400, role=role, icon="key")
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
    return _auth_page("Check your email", body, title="Check your email", role=role, kicker="Reset link sent", icon="mail")


def _reset_page(token: str, error: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    body = (f'{err}<form method="post" action="/reset">{_csrf_input()}<input type="hidden" name="token" value="{esc(token)}">'
            f'{_pw_field(autocomplete="new-password", label="New password", check=True)}{_RULES_LIST}'
            f'{_pw_field(fid="f-password2", name="password2", label="Confirm new password", autocomplete="new-password")}'
            '<button class="submit-btn wide" type="submit">Save new password</button></form>')
    return _auth_page("Choose a new password", body, status=status, kicker="Password reset", icon="key")


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
    return _auth_page("Password updated", body, role=user["role"], kicker="All set", icon="check")


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
            fl_block = f'<div style="margin:12px 0">{fl}</div>' if fl else '<p style="font-size:13px;color:var(--muted);margin:10px 0">No scam signals fired.</p>'
            loc = esc(j["location"]) if j["location"] else ""
            url_line = f'<p style="font-size:13px;color:var(--muted);margin-top:8px;word-break:break-all">Apply: {esc(j["apply_url"])}</p>' if j["apply_url"] else ''
            contact_line = f'<p style="font-size:13px;color:var(--muted);margin-top:4px">Contact: {esc(j["contact"])}</p>' if j["contact"] else ''
            contact_line += (f'<p style="font-size:13px;color:var(--muted);margin-top:4px">Posted by: {esc(j["employer_email"])} (email confirmed)</p>'
                             if j.get("employer_email") else '')
            inner += f"""<div class="rev-card">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
<div><div class="job-title">{esc(j['title'])}</div><div class="job-co">{esc(j['company'])}</div></div>
{_score_pill(j)}</div>
{_risk(j)}
<div class="job-meta" style="margin-top:10px"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}</div>
{fl_block}
<div class="detail-desc" style="font-size:14px;max-height:140px;overflow:auto;background:var(--sunk);padding:10px 12px;border-radius:8px">{esc(j['description'])}</div>
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
    body = (f'{admin_extra.tabs("/admin", "Review queue")}{stats_html}<p class="lead">{len(pending)} submission{"s" if len(pending)!=1 else ""} waiting. '
            f'The scam score is advisory; you decide what publishes. '
            f'<form method="post" action="/admin/logout" style="display:inline">{csrf}<button style="background:none;border:none;color:var(--accent-ink);text-decoration:underline;cursor:pointer;font:inherit">Sign out</button></form></p>{inner}')
    return shell(body, title="Review queue", admin=True)


@app.get("/admin/ai", response_class=HTMLResponse)
def admin_ai_usage(session: str | None = Cookie(default=None)):
    """AI requests and tokens by day, model and feature, so real costs can be checked against Anthropic's price list."""
    if not _is_admin(session):
        return RedirectResponse("/admin", status_code=303)
    rows = ai.usage_rows(31)
    tot = {k: sum(r[k] for r in rows) for k in ("requests", "input_tokens", "output_tokens", "cache_read", "cache_write")}
    by_feat: dict = {}
    for r in rows:
        f = by_feat.setdefault((r["feature"], r["model"]), {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cache_read": 0})
        for k in f:
            f[k] += r[k]
    n = lambda v: f"{int(v):,}"                                                  # noqa: E731
    feat_rows = "".join(f"<tr><td>{esc(fe)}</td><td><code>{esc(mo)}</code></td><td>{n(v['requests'])}</td><td>{n(v['input_tokens'])}</td>"
                        f"<td>{n(v['cache_read'])}</td><td>{n(v['output_tokens'])}</td></tr>"
                        for (fe, mo), v in sorted(by_feat.items(), key=lambda kv: -kv[1]["requests"]))
    day_rows = "".join(f"<tr><td>{esc(r['day'])}</td><td>{esc(r['feature'])}</td><td><code>{esc(r['model'])}</code></td><td>{n(r['requests'])}</td>"
                       f"<td>{n(r['input_tokens'])}</td><td>{n(r['cache_read'])}</td><td>{n(r['output_tokens'])}</td></tr>" for r in rows[:200])
    state = ("on" if ai.enabled() else "off (no ANTHROPIC_API_KEY, so every feature uses the built-in engines)")
    body = (f'{admin_extra.tabs("/admin/live", "AI usage")}<p class="lead">AI is {esc(state)}. Main model <code>{esc(ai.model())}</code>, '
            f'fast model <code>{esc(ai.model("fast"))}</code>. Last 31 days: {n(tot["requests"])} requests, {n(tot["input_tokens"])} input tokens '
            f'(+{n(tot["cache_read"])} read from cache, {n(tot["cache_write"])} written to it) and {n(tot["output_tokens"])} output tokens. '
            'Multiply by the per-token prices on Anthropic\'s pricing page to get the cost, and keep a monthly spend limit set in the '
            'Anthropic Console: when it\'s reached, the site falls back to the built-in engines.</p>'
            '<h3 class="sec">By feature</h3><table class="t"><tr><th>Feature</th><th>Model</th><th>Requests</th><th>Input</th><th>Cached input</th><th>Output</th></tr>'
            f'{feat_rows or "<tr><td colspan=6>No AI requests yet.</td></tr>"}</table>'
            '<h3 class="sec">By day</h3><table class="t"><tr><th>Day (UTC)</th><th>Feature</th><th>Model</th><th>Requests</th><th>Input</th><th>Cached input</th><th>Output</th></tr>'
            f'{day_rows or "<tr><td colspan=7>No AI requests yet.</td></tr>"}</table>')
    return HTMLResponse(shell(body, title="AI usage", admin=True), headers={"Cache-Control": "no-store"})


@app.get("/admin/client-ip", response_class=HTMLResponse)
def admin_client_ip(request: Request, session: str | None = Cookie(default=None)):
    """Shows which address the rate limits see for you, and where it came from. Open it once after deploying: the
    address should be your own public IP (search "what is my ip"), not a Cloudflare or Render one."""
    if not _is_admin(session):
        return RedirectResponse("/admin", status_code=303)
    ip, source = security.resolve_ip(request.client.host if request.client else "", lambda n: ",".join(request.headers.getlist(n)))
    rows = [("Address the limits use", ip), ("Taken from", source), ("TRUST_PROXY", "on" if security.TRUST_PROXY else "off"),
            ("Headers checked first", ", ".join(security.CLIENT_IP_HEADERS) or "none (set CLIENT_IP_HEADER)"),
            ("Connection address", request.client.host if request.client else "unknown")]
    rows += [(h, request.headers.get(h, "(not sent)")) for h in ("cf-connecting-ip", "true-client-ip", "x-forwarded-for", "x-real-ip")]
    table = "".join(f'<tr><th scope="row">{esc(k)}</th><td><code>{esc(v)}</code></td></tr>' for k, v in rows)
    body = (f'{admin_extra.tabs("/admin/live", "Client address check")}<p class="lead">If "Address the limits use" isn\'t your own '
            f'public IP, every visitor is sharing one rate limit. Set CLIENT_IP_HEADER (or TRUST_PROXY_HOPS) in Render to fix it.</p>'
            f'<table class="kv">{table}</table>')
    return HTMLResponse(shell(body, title="Client address check", admin=True), headers={"Cache-Control": "no-store"})


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
    body = f'{admin_extra.tabs("/admin/live")}<p class="lead">Removing a listing takes it off the board immediately.</p>{inner}'
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
    if set_review(job_id, status, label, only_from=("approved",) if status == "removed" else ("pending",)):
        who = defense.reviewer_name(session)
        with store.db() as conn:
            conn.execute("UPDATE jobs SET reviewer = ? WHERE id = ?", (who, job_id))
            defense.log_label(conn, "job", job_id, label, who, reason)
            defense.recheck(conn, defense.hashes_of(conn, "job", [job_id]))   # other listings sharing its contact details
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
