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
import secrets
import sqlite3
import contextvars
import datetime as dt
from contextlib import closing, asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Cookie, Response, Request, HTTPException, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from scam_detector.scorer import score_posting
import accounts
import backup
import mailer
import security
import store
import ui
import web
import matching
import profiles
import profile_page
import fit
import jobfit
import messaging
import msgcheck
import assistant
import resume_tools
import feed
import admin_extra
import hiring
import easyapply
import network
import employer_page
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

CATEGORIES = matching.CATEGORIES
WORK_TYPES = matching.WORK_TYPES


# ---------- database ----------

# Added after the first release; existing databases are migrated in place.
_EXTRA_COLUMNS = {"review_label": "TEXT", "ruleset_version": "TEXT", "reviewed_at": "TEXT", "employer_id": "INTEGER",
                  "easy_apply": "INTEGER NOT NULL DEFAULT 0", "questions": "TEXT NOT NULL DEFAULT '[]'"}
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


def add_job(data: dict, employer_id: int | None = None) -> dict:
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

    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("""
            INSERT INTO jobs (title, company, category, work_type, location,
                              description, apply_url, contact, score, band,
                              scam_status, review_status, findings_json, created_at,
                              ruleset_version, employer_id, easy_apply, questions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["title"], data["company"], data.get("category","Other"),
            data["work_type"], data.get("location",""), data["description"],
            data.get("apply_url",""), data.get("contact",""),
            result.score, result.band, scam_status, "pending",
            json.dumps(findings), dt.datetime.utcnow().isoformat(),
            result.ruleset_version, employer_id,
            1 if data.get("easy_apply") else 0, json.dumps(data.get("questions") or []),
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


# ---------- markup (the design system lives in ui.py) ----------

def _score_pill(j: dict) -> str:
    """The reviewer's verdict pill. The scam score only counts scam rules; a listing flagged by the separate
    aggregator/lead-gen check says so instead of showing "Score 0 · flagged"."""
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    text = f"Scam risk {ui.shown_score(j['score'], lead_gen)} · {j['scam_status']}"
    return f'<span class="rev-score {esc(j["scam_status"])}">{esc(text)}</span>'


def _risk(j: dict) -> str:
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    return ui.risk_meter(int(j["score"]), j["scam_status"], aggregator=lead_gen)


def _teaser_card(j: dict) -> str:
    """What visitors see: title, company and category. Everything else is for signed-in students."""
    return (f'<a class="job teaser" href="/login?next=/job/{int(j["id"])}"><div class="job-top"><div><div class="job-title">{esc(j["title"])}</div>'
            f'<div class="job-co">{esc(j["company"])}</div></div><span class="pill">{ui.icon("shield", 13)} Log in to view</span></div>'
            f'<div class="job-meta"><span class="chip">{esc(j["category"])}</span></div></a>')


def _job_card(j: dict) -> str:
    badge = ('<span class="badge verified">✓ Verified</span>' if j["scam_status"]=="clear"
             else '<span class="badge warning">⚠ Check carefully</span>')
    loc = esc(j["location"]) if j["location"] else ""
    return f"""<a class="job" href="/job/{j['id']}">
<div class="job-top"><div><div class="job-title">{esc(j['title'])}</div>
<div class="job-co">{esc(j['company'])}</div></div>{badge}</div>
<div class="job-meta"><span class="chip">{esc(j['category'])}</span>
<span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}{'<span class="chip easy">Easy apply</span>' if easyapply.is_easy(j) else ''}</div></a>"""


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
    request.state.user = user
    request.state.utoken = raw if user else None
    extra = {}
    if user and not request.url.path.startswith(("/static/", "/api/")):
        with store.db() as conn:
            extra["unread"] = store.unread_count(conn, user["id"])
            if user["role"] == "student":
                extra["requests"] = network.incoming_count(conn, user["id"])
    marker = _viewer.set({"user": user, "token": raw if user else None, "extra": extra})
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
    path = request.url.path
    if path.startswith(_PRIVATE_PREFIXES):
        h["Cache-Control"] = "no-store"
        h["X-Robots-Tag"] = "noindex, nofollow"
    elif user and "Cache-Control" not in h:
        h["Cache-Control"] = "private, no-store"     # signed-in pages show personal data
    return response


_PRIVATE_PREFIXES = ("/admin", "/messages", "/api/", "/profile", "/resume", "/u/", "/talent", "/feed", "/assistant", "/check", "/job", "/hiring", "/company")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("SELECT 1").fetchone()
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
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
_FONT = (Path(__file__).resolve().parent / "static" / "fonts" / "archivo.woff2").read_bytes()


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


@app.get("/static/fonts/archivo.woff2")
def static_font():
    # Archivo, SIL Open Font License 1.1 (static/fonts/OFL.txt). Self-hosted: no third-party font requests.
    return Response(_FONT, media_type="font/woff2", headers={"Cache-Control": "public, max-age=31536000, immutable"})


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
    hero = (ui.cine_hero() + ui.marquee_block() + night
            + ui.scan_block('<a href="/check">Check one you found →</a>') + ui.how_students() + fair)
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
    return shell(f'<section class="home-list">{body}</section>', hero=hero, wide=True)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_feed(request: Request, search: str = "", category: str = "", work_type: str = "", following: int = 0):
    enforce_rate_limit(request, general_limiter, "jobs_feed")
    if not getattr(request.state, "user", None):
        return RedirectResponse("/login?next=/jobs", status_code=303)       # the board is for FSU students and employers only
    # Query params are attacker-controlled input same as form fields --
    # oversized or malformed values get clipped/rejected here too.
    search = search.strip()[:200]
    category = clean_choice(category, CATEGORIES, "category", default="") if category else ""
    work_type = clean_choice(work_type, WORK_TYPES, "work_type", default="") if work_type else ""
    jobs = query_public(search=search, category=category, work_type=work_type)
    viewer = getattr(request.state, "user", None)
    is_student = bool(viewer and viewer["role"] == "student")
    following = 1 if (following and is_student) else 0
    if following:
        with store.db() as conn:
            followed = set(network.followed_ids(conn, viewer["id"]))
        jobs = [j for j in jobs if j.get("employer_id") in followed]

    def chip(name, val, cur, param):
        qs = {}
        if search: qs["search"] = search
        if param != "category" and category: qs["category"] = category
        if param != "work_type" and work_type: qs["work_type"] = work_type
        if val: qs[param] = val
        if following: qs["following"] = 1
        href = "/jobs" + ("?" + urlencode(qs) if qs else "")
        return f'<a class="chipf {"active" if cur==val else ""}" href="{esc(href)}">{esc(name)}</a>'

    cat_chips = chip("All","",category,"category") + "".join(chip(c,c,category,"category") for c in CATEGORIES)
    wt_chips = chip("Any","",work_type,"work_type") + "".join(chip(w.title(),w,work_type,"work_type") for w in WORK_TYPES)

    follow_row = ""
    if is_student:
        base = {k: v for k, v in (("search", search), ("category", category), ("work_type", work_type)) if v}
        follow_row = ('<div class="filter-row"><span class="label">From</span>'
                      f'<a class="chipf {"" if following else "active"}" href="{esc("/jobs" + ("?" + urlencode(base) if base else ""))}">All companies</a>'
                      f'<a class="chipf {"active" if following else ""}" href="{esc("/jobs?" + urlencode({**base, "following": 1}))}">Companies I follow</a></div>')
    controls = f"""<div class="controls">
<form class="searchbar" method="get" action="/jobs">
<input name="search" value="{esc(search)}" placeholder="Search title, company, or keyword">
{f'<input type="hidden" name="category" value="{esc(category)}">' if category else ''}
{f'<input type="hidden" name="work_type" value="{esc(work_type)}">' if work_type else ''}
{'<input type="hidden" name="following" value="1">' if following else ''}
<button type="submit">Search</button></form>
<div class="filter-row"><span class="label">Category</span>{cat_chips}</div>
<div class="filter-row"><span class="label">Type</span>{wt_chips}</div>{follow_row}</div>"""

    if jobs:
        head = f'<div class="results-head">{len(jobs)} listing{"s" if len(jobs)!=1 else ""}' + (f' for "{esc(search)}"' if search else "") + '</div>'
        body = controls + head + "".join(_job_card(j) for j in jobs)
    else:
        body = controls + ('<div class="empty">Nothing from companies you follow right now. <a href="/network?tab=following">Who you follow</a></div>' if following else
                           '<div class="empty">No listings match. Try clearing filters or a different search.</div>')
    head = ui.page_head("Jobs", "Every listing here was scam-scanned and approved by a person.", num="Jobs") if getattr(request.state, "user", None) else ""
    return shell(head + body, title="Browse jobs — NoleCareerShield", active="/jobs")


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request):
    enforce_rate_limit(request, general_limiter, "job_detail")
    if not getattr(request.state, "user", None):
        return RedirectResponse(f"/login?next=/job/{int(job_id)}", status_code=303)
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
    elif easyapply.is_easy(j):
        apply = ""      # filled in below, once we know whether the employer is approved and whether the student already applied
    elif j["apply_url"]:
        # Through /job/{id}/apply so the employer's Apply-click total counts it; the student lands on the same link.
        apply = f'<a class="apply-btn" href="/job/{int(j["id"])}/apply" target="_blank" rel="noopener noreferrer nofollow ugc">Apply →</a>'
    elif j["contact"]:
        apply = f'<p style="font-size:14px;color:var(--muted)">Contact: {esc(j["contact"])}</p>'

    extras = after = trust_html = ""
    if viewer and j.get("employer_id"):
        with store.db() as conn:
            if store.employer_approved(conn, j["employer_id"]):
                trust_html = ('<div style="margin-top:8px">' + employer_page.trust_pill(employer_page.trust(conn, j["employer_id"]), "/company/%d#trust" % int(j["employer_id"])) + "</div>")
    if viewer and viewer["role"] == "student":
        with store.db() as conn:
            prof = store.student_profile(conn, viewer["id"])
            hiring.record_view(conn, int(j["id"]), viewer["id"])
            emp_ok = bool(j.get("employer_id")) and store.employer_approved(conn, j["employer_id"])
            done = easyapply.application(conn, int(j["id"]), viewer["id"]) if easyapply.is_easy(j) else None
            following = network.is_following(conn, viewer["id"], j["employer_id"]) if emp_ok else False
        if easyapply.is_easy(j):
            if done:
                apply = (f'<div class="banner verified">✓ You applied {esc(web.ago(done["created_at"]))}. <a href="/applications">Your applications</a></div>')
            elif emp_ok:
                apply = (f'<a class="apply-btn" href="/job/{int(j["id"])}/easy">Easy apply →</a>'
                         '<p class="fine" style="text-align:left">Applies from your profile without leaving the site. You choose what the employer sees.</p>')
            elif j["contact"]:
                apply = f'<p style="font-size:14px;color:var(--muted)">Contact: {esc(j["contact"])}</p>'
        btns = [f'<a class="b sec" href="#tailor">{ui.icon("file", 16)} Tailor my resume</a>']
        if emp_ok:
            btns.insert(0, f'<a class="b ghost" href="/messages/new?to={int(j["employer_id"])}&amp;job={int(j["id"])}">{ui.icon("chat", 16)} Message the employer</a>')
            btns.append(f'<a class="b sec" href="/company/{int(j["employer_id"])}">Company profile</a>')
            btns.append(network.follow_button(int(j["employer_id"]), following, next_=f"/job/{int(j['id'])}", small=False))
        extras = jobfit.fit_panel(j, prof) + f'<div class="row" style="margin:14px 0">{"".join(btns)}</div>'
        after = jobfit.tailor_panel(j, prof)
    if viewer and viewer["role"] == "employer" and j.get("employer_id") == viewer["id"]:
        extras = (f'<div class="banner info">This is your listing. <a href="/hiring/{int(j["id"])}">See ranked student matches, candidates and stats →</a></div>')
    loc = esc(j["location"]) if j["location"] else ""
    body = f"""<a class="back" href="/jobs">← All jobs</a>
{banner}
<h2 class="page" style="margin-top:8px">{esc(j['title'])}</h2>
<p class="job-co" style="font-size:16px">{esc(j['company'])}</p>{trust_html}
<div class="job-meta" style="margin:14px 0"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span>{f'<span class="chip">{loc}</span>' if loc else ''}</div>
{findings_html}{extras}<div class="detail-desc">{esc(j['description'])}</div>{apply}{after}"""
    return shell(body, title=esc(j["title"]) + " — NoleCareerShield", active="/jobs", js=bool(after))


@app.get("/job/{job_id}/apply")
def job_apply(job_id: int, request: Request):
    """Counts a student's Apply click (once per student, for the employer's totals), then goes to the apply link."""
    viewer = getattr(request.state, "user", None)
    j = get_job(job_id)
    if not j or j["review_status"] != "approved" or not j["apply_url"] or not (viewer and viewer["role"] == "student"):
        return RedirectResponse(f"/job/{int(job_id)}", status_code=303)
    enforce_rate_limit(request, general_limiter, "job_apply")
    with store.db() as conn:
        hiring.record_apply_click(conn, int(j["id"]), viewer["id"])
    return RedirectResponse(j["apply_url"], status_code=303)


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
    qv = v.get("questions") if isinstance(v.get("questions"), list) else []
    qv = list(qv) + [{}] * (easyapply.MAX_QUESTIONS - len(qv))
    q_rows = "".join(
        f'<div class="qrow"><label class="sr" for="f-qtext{i}">Question {i + 1}</label><input id="f-qtext{i}" name="qtext" maxlength="{easyapply.Q_LEN}" placeholder="Question {i + 1}" value="{esc(q.get("q", ""))}">'
        f'<label class="sr" for="f-qkind{i}">Answer type for question {i + 1}</label><select id="f-qkind{i}" name="qkind">' + "".join(f'<option value="{k}"{" selected" if q.get("kind") == k else ""}>{esc(n)}</option>' for k, n in easyapply.KINDS) + '</select>'
        f'<label class="sr" for="f-qreq{i}">Required or optional for question {i + 1}</label><select id="f-qreq{i}" name="qreq"><option value="0">Optional</option><option value="1"{" selected" if q.get("required") else ""}>Required</option></select></div>'
        for i, q in enumerate(qv[:easyapply.MAX_QUESTIONS]))
    easy_on = " checked" if v.get("easy_apply") in (1, True, "1", "on") else ""
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
<fieldset class="form-field easyset"><legend>Easy apply</legend>
<label class="toggle" for="f-easy"><input id="f-easy" type="checkbox" name="easy_apply" value="1"{easy_on}><span><b>Collect applications on NoleCareerShield.</b> Students apply from their profile in one step, and you get their answers in your candidate tracker. Leave it off to send them to your Apply URL.</span></label>
<p class="hint" style="margin-top:10px">Optional questions for applicants (up to {easyapply.MAX_QUESTIONS}). Nothing that asks for an SSN, bank or card details or a password.</p>{q_rows}</fieldset>
<button class="submit-btn" type="submit">Submit for review</button>{under}</form>"""
    return HTMLResponse(shell(body, title="Submit a job — NoleCareerShield", active="/post"), status_code=status)


@app.get("/post", response_class=HTMLResponse)
def post_form():
    return _post_form_page()


def _clean_questions(raw) -> list[dict]:
    try:
        return easyapply.clean_questions(raw)
    except easyapply.QuestionError as e:
        raise ValidationError(str(e))


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
        "easy_apply": 1 if f.get("easy_apply") in (1, True, "1", "on", "yes") else 0,
        "questions": _clean_questions(f.get("questions")),
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
    easy_apply: str = Form(""), qtext: list[str] = Form([]), qkind: list[str] = Form([]), qreq: list[str] = Form([]),
):
    enforce_rate_limit(request, submit_limiter, "post_submit")
    typed = {"title": title, "company": company, "category": category, "work_type": work_type,
             "location": location, "description": description, "apply_url": apply_url, "contact": contact,
             "easy_apply": easy_apply,
             "questions": [{"q": t, "kind": (qkind[i] if i < len(qkind) else "short"), "required": (qreq[i] if i < len(qreq) else "0") == "1"}
                           for i, t in enumerate(qtext[:easyapply.MAX_QUESTIONS])]}
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


# ---------- student network ----------

for _r in (profile_page.router, profiles.router, messaging.router, msgcheck.router, assistant.router, resume_tools.router,
           feed.router, admin_extra.router, hiring.router, easyapply.router, network.router):
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
    return shell(f'<section class="home-list">{body}</section>', hero=hero, title="For employers — NoleCareerShield", wide=True)


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
<li><b>Easy apply</b> on listings that choose it: a short form filled from your profile, sent only to that employer.</li>
<li><b>A network</b> where students connect with each other and follow the companies they like, with no student-to-student inbox.</li>
<li><b>A job assistant</b> that answers in plain words and only suggests listings that passed review.</li>
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
    ai_block = ("""<h3>AI features</h3>
<ul><li>The job assistant, resume review, resume tailoring, the scam checker's second opinion and feed moderation can use Claude, made by Anthropic.</li>
<li>Text is sent to Anthropic only when you use one of those features: your question, your resume or profile summary, the job you picked, or the message you asked us to check. Anthropic processes it to answer and, under its commercial terms, does not use it to train models.</li>
<li>Nothing is sent for browsing, messaging or anything you don't ask the AI to do. Each account has a daily limit.</li></ul>""" if ai_on else
                """<h3>AI features</h3><ul><li>AI features are currently off. The job assistant, resume tools and scam checker run entirely on this site's own rules, so nothing is sent to an AI provider.</li></ul>""")
    body = f"""<a class="back" href="/">← Home</a><h2 class="page">Privacy</h2>
<div class="prose"><p>Short version: browsing is anonymous, you choose what goes on your profile and who sees it, and you can download or delete everything at any time.</p>
<h3>Anyone browsing</h3>
<ul><li>Job listings are for signed-in FSU students and employers. Visitors see only a few titles on the home page.</li>
<li>Anyone can use the scam checker without an account, up to 10 checks a day. Visitors see the verdict and the main reasons; signed-in FSU students see every signal and the exact words it caught. No cookies are set for browsing.</li>
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
<li><b>Easy apply.</b> When you apply on a listing that collects applications here, that employer (and only that employer) sees your name, major, graduation term, profile links, your answers and note, and your resume only if you tick it. Never your email. Applying also lets that employer open your profile and message you. You can withdraw an application any time, which deletes the answers.</li>
<li><b>Connections and follows.</b> A connection is a mutual link between two students that shows as a count and as mutual connections on profiles. It doesn't let anyone message you. You can switch off connection requests and "People you may know" in your profile settings. Following a company adds its listings to a filter for you; the company sees how many students follow it, never who.</li></ul>
<h3>Messages</h3>
<ul><li>Messages are only between students and employers our reviewers approved. Every message is scanned for scam signs when it is sent. Messages that match a pattern only scams use are held for a reviewer instead of being delivered; others may be delivered with a warning.</li>
<li>Reviewers read a message only when it was held by the scanner or reported by someone in the conversation.</li>
<li>Email notifications say only that a message is waiting, never what it says.</li></ul>
<h3>The FSU feed</h3>
<ul><li>Only signed-in FSU students and approved employers can read or post. Employer posts are reviewed before they appear and must be relevant to FSU students.</li>
<li>Anyone can report a post; reported posts are checked by a reviewer. Rejected and removed posts are deleted after 30 days.</li></ul>
<h3>Scam checker</h3>
<ul><li>Messages you paste into the scam checker are not saved, unless you press "send to reviewers" to help improve the detector. Those are kept for up to a year.</li></ul>
{ai_block}
<h3>People who post a job</h3>
<ul><li>You need an employer account: an email address (confirmed by a link) and a password, stored the same way as above, plus a company profile that a reviewer approves before you can message students or post to the feed.</li>
<li>We store what you type into the listing form, the account that sent it, the automated scam score and the review decision. The contact field is shown publicly if the listing is approved.</li>
<li>Approved employers get a trust score (0-100, higher is safer) that signed-in students see on the company page and listings. It comes only from what this site can check: reviewer approval, your email domain and website, how your listings were reviewed, scanner flags and reports on your messages, how you answer students, and how complete your profile is. You can see how yours is worked out, and how to raise it, on your company profile.</li>
<li>Rejected and removed listings are deleted automatically after {PURGE_REJECTED_DAYS} days. Approved listings stop showing after {LISTING_TTL_DAYS} days.</li>
<li>If you fill in the form before logging in, the listing is kept for up to 3 days so it can be sent when you finish, then deleted.</li></ul>
<h3>Your data</h3>
<ul><li>On your profile page you can download everything we store about your account as a file, and delete your account. Deleting removes your profile, resume, versions, posts and comments, and blanks the messages you sent.</li>
<li>Accounts that never confirm their email are deleted after 7 days. Questions: {_contact_line()}.</li></ul>
<h3>Cookies and logs</h3>
<ul><li>Logging in sets one session cookie (HttpOnly, 7 days). Sending a listing before you log in sets a short-lived cookie that holds only a random reference to your saved listing.</li>
{bot}<li>Server logs may briefly hold IP addresses for security and abuse prevention. IP addresses are also held in memory, temporarily, to enforce rate limits.</li>
<li>We send email only for account confirmation, password reset, listing receipts and "you have a new message" notices. No marketing.</li></ul>
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


# --- one place to start: email first, like Handshake ---

def _start_shell(inner: str, title: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(shell(f'<div class="auth start"><div class="startmark" aria-hidden="true">{EMBLEM}</div>{inner}</div>',
                              title=title + " — NoleCareerShield", scripts=True), status_code=status)


def _start_page(email: str = "", error: str = "", next_: str = "", status: int = 200) -> HTMLResponse:
    err = f'<div class="banner warning" role="alert">{esc(error)}</div>' if error else ""
    note = ('<div class="banner info">Log in with your FSU student account to see how to apply.</div>'
            if next_.startswith("/job/") else "")
    inner = f"""<h2 class="auth-title">Log in or sign up</h2><p class="auth-sub">Students use their @fsu.edu address.</p>{note}{err}
<form method="post" action="/login">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="form-field"><input id="s-email" type="email" name="email" required maxlength="254" autocomplete="username" aria-label="Email"
placeholder="Email" value="{esc(email)}" autofocus></div>
<button class="submit-btn wide" type="submit">Continue with email</button></form>
<p class="start-foot">Hiring? <a href="/employers">Employer log in or sign up →</a></p>"""
    return _start_shell(inner, "Log in or sign up", status)


def _sso_welcome(email: str, next_: str) -> HTMLResponse:
    hidden = f'{_csrf_input()}<input type="hidden" name="email" value="{esc(email)}"><input type="hidden" name="next" value="{esc(next_)}">'
    inner = f"""<h2 class="auth-title">Welcome to NoleCareerShield</h2>
<p class="auth-sub">Use your {esc(sso.NAME)} account to log in as<br><b>{esc(email)}</b> <a href="/login{"?next=" + esc(next_) if next_ else ""}">Edit</a></p>
<form method="post" action="/sso/start">{hidden}<button class="submit-btn wide" type="submit">Continue to {esc(sso.NAME)} single sign-on →</button></form>
<form method="post" action="/login" style="margin-top:12px;text-align:center">{hidden}<input type="hidden" name="how" value="password">
<button class="linkbtn" type="submit">Log in another way</button></form>
<p class="fine" style="margin-top:16px">You'll sign in on {esc(sso.NAME)}'s own page, with Duo if your account uses it. NoleCareerShield never sees your {esc(sso.NAME)} password.</p>"""
    return _start_shell(inner, "Welcome")


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
    enforce_rate_limit(request, user_login_limiter, "sso_start")
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
    enforce_rate_limit(request, user_login_limiter, "sso_callback")
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
    ph = "you@fsu.edu" if role == "student" else "you@company.com"
    a_an = "a student" if role == "student" else "an employer"
    body = f"""{note}{err}{resend}
<form method="post" action="/login/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required maxlength="254" autocomplete="username" placeholder="{ph}" value="{esc(email)}"></div>
{_pw_field(forgot_role=role)}
{_turnstile_widget()}<button class="submit-btn wide" type="submit">Log in</button></form>
<div class="or"><span>Or</span></div><a class="outline-btn" href="/signup/{role}{"?next=" + esc(next_) if next_ else ""}">Create {a_an} account</a>{_other_side(role)}"""
    return _auth_page("Student log in" if role == "student" else "Employer log in", body, status=status)


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
        sub = '<p class="auth-sub">Use your @fsu.edu email. We send a link to confirm it.</p>'
        ph = "you@fsu.edu"
    else:
        sub = '<p class="auth-sub">Any email works. We send a link to confirm it before you can post.</p>'
        ph = "you@company.com"
    body = f"""{err}
<form method="post" action="/signup/{role}">{_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">
<div class="hp" aria-hidden="true"><label for="f-website">Leave this empty</label><input id="f-website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="form-field"><label for="f-email">Email</label><input id="f-email" type="email" name="email" required maxlength="254" autocomplete="username" placeholder="{ph}" value="{esc(email)}"></div>
{_pw_field(autocomplete="new-password", check=True)}{_RULES_LIST}
{_pw_field(fid="f-password2", name="password2", label="Confirm password", autocomplete="new-password")}
{_turnstile_widget()}<button class="submit-btn wide" type="submit">Create account</button></form>
<div class="or"><span>Or</span></div><a class="outline-btn" href="/login/{role}{"?next=" + esc(next_) if next_ else ""}">I already have an account</a>{_other_side(role)}"""
    return _auth_page("Create your student account" if role == "student" else "Create your employer account", body, sub=sub, status=status)


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
        msg = ("Your listing was sent for review. A person checks every listing before it appears. "
               "Next, tell students about your organization." if sent
               else "Next, set up your company profile. A reviewer approves it before you can message students or post to the feed.")
        cta = '<a class="apply-btn" href="/profile/setup">Set up company profile</a>'
    else:
        msg = "Next, set up your profile. It takes about two minutes and powers your job matches."
        cta = '<a class="apply-btn" href="/profile/setup">Set up my profile</a>'
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
