"""
NoleCareerShield — a curated job board for FSU students.

TWO LAYERS OF PROTECTION:
  1. Every submission is SCORED by the scam detector (scam_detector.scorer).
  2. Every submission then waits in a REVIEW QUEUE until an admin approves it.
     Nothing is public until a human approves. This gives "vetted employers
     only" without authenticating anyone or storing student identity data.

Anyone may BROWSE (no login, no data collected). Only an admin can approve
postings. Posting is open-submission but approval-gated, not open-publish.

PRIVACY BY DESIGN:
  No student accounts, no logins for job seekers, no resumes, no job-seeker
  data of any kind. Storage holds only what an employer types into the post
  form plus the scam score and review status. No analytics, no trackers, no
  cookies, no third-party scripts. The only outbound network call is optional
  RDAP/DNS enrichment, OFF by default on submission. The `contact` field is
  shown publicly and is optional; the form warns the poster.

  Admin auth is a single shared password read from the ADMIN_PASSWORD
  environment variable (default 'changeme' for local dev — CHANGE IT before
  deploying). It gates the review queue only. This is intentionally simple;
  it stores no personal data.

TRADEMARK NOTE:
  Original emblem and the garnet/gold color family only. No FSU seal or logos.
  "Nole" is evocative, not an official-affiliation claim, and "CareerShield" signals the safety focus without using FSU-protected terms like "Seminole." The footer states the
  project is independent and unaffiliated. Swap in official marks only with
  university permission.

Run:
  export ADMIN_PASSWORD=your-secret     # (Windows: set ADMIN_PASSWORD=...)
  uvicorn app:app --reload
Then open http://127.0.0.1:8000  (admin queue at /admin)
"""

from __future__ import annotations

import os
import json
import secrets
import sqlite3
import datetime as dt
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Form, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from scam_detector.scorer import score_posting

DB_PATH = Path("jobs.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
app = FastAPI(title="NoleCareerShield")

# In-memory admin session tokens. Fine for a single-admin app; resets on restart.
_ADMIN_SESSIONS: set[str] = set()

CATEGORIES = [
    "Data & Analytics", "Admin & Office", "Customer Service",
    "Marketing", "Finance & Accounting", "Operations & Warehouse", "Other",
]
WORK_TYPES = ["remote", "hybrid", "on-site"]


# ---------- database ----------

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
        db.commit()


def add_job(data: dict) -> dict:
    result = score_posting(
        title=data["title"], description=data["description"], company=data["company"],
        run_network=False,
        url_chain=[data["apply_url"]] if data.get("apply_url") else None,
    )
    # The scorer's band is advisory to the admin; it does NOT auto-publish.
    scam_status = {"block": "held", "review": "flagged"}.get(result.band, "clear")

    with closing(sqlite3.connect(DB_PATH)) as db:
        cur = db.execute("""
            INSERT INTO jobs (title, company, category, work_type, location,
                              description, apply_url, contact, score, band,
                              scam_status, review_status, findings_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["title"], data["company"], data.get("category","Other"),
            data["work_type"], data.get("location",""), data["description"],
            data.get("apply_url",""), data.get("contact",""),
            result.score, result.band, scam_status, "pending",
            json.dumps(result.findings), dt.datetime.utcnow().isoformat(),
        ))
        db.commit()
        job_id = cur.lastrowid
    return {"id": job_id, "scam_status": scam_status, "score": result.score,
            "band": result.band, "findings": result.findings}


def query_public(search="", category="", work_type="") -> list:
    """Only APPROVED listings are ever shown publicly."""
    q = "SELECT * FROM jobs WHERE review_status = 'approved' "
    params = []
    if search.strip():
        q += "AND (title LIKE ? OR company LIKE ? OR description LIKE ?) "
        like = f"%{search.strip()}%"; params += [like, like, like]
    if category in CATEGORIES:
        q += "AND category = ? "; params.append(category)
    if work_type in WORK_TYPES:
        q += "AND work_type = ? "; params.append(work_type)
    q += "ORDER BY created_at DESC"
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(q, params).fetchall()]


def query_pending() -> list:
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT * FROM jobs WHERE review_status = 'pending' ORDER BY created_at DESC"
        ).fetchall()]


def get_job(job_id: int) -> dict | None:
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def set_review(job_id: int, status: str):
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("UPDATE jobs SET review_status = ? WHERE id = ?", (status, job_id))
        db.commit()


def public_count() -> int:
    with closing(sqlite3.connect(DB_PATH)) as db:
        return db.execute("SELECT COUNT(*) FROM jobs WHERE review_status='approved'").fetchone()[0]


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
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap');
:root{--bg:#FAF8F4;--ink:#1C1A18;--soft:#6E6862;--line:#E6E1D8;--card:#FFF;
--garnet:#782F40;--garnet-dk:#5E2432;--gold:#CEB888;--gold-dk:#B79F6B;
--green:#2F7D5B;--amber:#B0721A;--red:#B23A2E;--green-bg:#EAF4EF;--amber-bg:#FBF2E2;--red-bg:#F8ECEA;}
*{box-sizing:border-box;margin:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
a{color:inherit}
.wrap{max-width:900px;margin:0 auto;padding:0 20px}
header{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.nav{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;max-width:900px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none}
.brand-name{font-family:'Fraunces',serif;font-weight:700;font-size:20px;color:var(--garnet);letter-spacing:-.01em}
.brand-name b{color:var(--gold-dk)}
.nav-actions{display:flex;gap:8px;align-items:center}
.nav a.ghost{text-decoration:none;color:var(--soft);font-size:14px;font-weight:600;padding:9px 12px}
.nav a.btn{background:var(--garnet);color:#fff;text-decoration:none;padding:9px 16px;border-radius:7px;font-size:14px;font-weight:600}
.nav a.btn:hover{background:var(--garnet-dk)}
.hero{background:linear-gradient(160deg,var(--garnet) 0%,var(--garnet-dk) 100%);color:#fff;padding:56px 20px 60px;text-align:center;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 80% 20%,rgba(206,184,136,.18),transparent 55%);pointer-events:none}
.hero h1{font-family:'Fraunces',serif;font-weight:700;font-size:38px;line-height:1.15;letter-spacing:-.02em;max-width:16ch;margin:0 auto 14px}
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
h2.page{font-family:'Fraunces',serif;font-weight:700;font-size:28px;letter-spacing:-.02em;margin:28px 0 6px;color:var(--garnet)}
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
"""

def shell(body: str, title: str = "NoleCareerShield", hero: str = "", admin: bool = False) -> str:
    nav_extra = '<a class="ghost" href="/admin">Review queue</a>' if admin else ''
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{BASE_CSS}</style></head><body>
<header><div class="nav">
<a class="brand" href="/">{EMBLEM}<span class="brand-name">Nole<b>CareerShield</b></span></a>
<div class="nav-actions">{nav_extra}<a class="ghost" href="/jobs">Browse jobs</a><a class="btn" href="/post">Post a job</a></div>
</div></header>
{hero}
<div class="wrap">{body}</div>
<footer>Every listing is scanned for scam signals and reviewed by a human before it appears. A verified badge is not a guarantee — always confirm an employer through their own website before sharing personal information.
<span class="tm">An independent student project. Not affiliated with, sponsored by, or endorsed by Florida State University; uses no university trademarks or logos.</span></footer>
</body></html>"""


def _job_card(j: dict) -> str:
    badge = ('<span class="badge verified">✓ Verified</span>' if j["scam_status"]=="clear"
             else '<span class="badge warning">⚠ Check carefully</span>')
    loc = esc(j["location"]) if j["location"] else j["work_type"].title()
    return f"""<a class="job" href="/job/{j['id']}">
<div class="job-top"><div><div class="job-title">{esc(j['title'])}</div>
<div class="job-co">{esc(j['company'])}</div></div>{badge}</div>
<div class="job-meta"><span class="chip">{esc(j['category'])}</span>
<span class="chip">{esc(j['work_type'].title())}</span><span class="chip">{loc}</span></div></a>"""


# ---------- public routes ----------

@app.on_event("startup")
def _startup():
    init_db()


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
def jobs_feed(search: str = "", category: str = "", work_type: str = ""):
    jobs = query_public(search=search, category=category, work_type=work_type)

    def chip(name, val, cur, param):
        qs = []
        if search: qs.append(f"search={esc(search)}")
        if param != "category" and category: qs.append(f"category={esc(category)}")
        if param != "work_type" and work_type: qs.append(f"work_type={esc(work_type)}")
        if val: qs.append(f"{param}={val}")
        href = "/jobs" + ("?" + "&".join(qs) if qs else "")
        return f'<a class="chipf {"active" if cur==val else ""}" href="{href}">{esc(name)}</a>'

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
def job_detail(job_id: int):
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
    if j["apply_url"]:
        apply = f'<a class="apply-btn" href="{esc(j["apply_url"])}" target="_blank" rel="noopener nofollow">Apply →</a>'
    elif j["contact"]:
        apply = f'<p style="font-size:14px;color:var(--soft)">Contact: {esc(j["contact"])}</p>'

    loc = esc(j["location"]) if j["location"] else j["work_type"].title()
    body = f"""<a class="back" href="/jobs">← All jobs</a>
{banner}
<h2 class="page" style="margin-top:8px">{esc(j['title'])}</h2>
<p class="job-co" style="font-size:16px">{esc(j['company'])}</p>
<div class="job-meta" style="margin:14px 0"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span><span class="chip">{loc}</span></div>
{findings_html}<div class="detail-desc">{esc(j['description'])}</div>{apply}"""
    return shell(body, title=esc(j["title"]) + " — NoleCareerShield")


@app.get("/post", response_class=HTMLResponse)
def post_form():
    cat_opts = "".join(f'<option value="{c}">{c}</option>' for c in CATEGORIES)
    wt_opts = "".join(f'<option value="{w}">{w.title()}</option>' for w in WORK_TYPES)
    body = f"""<a class="back" href="/">← Home</a>
<h2 class="page">Submit a job</h2>
<p class="lead">Submitting isn't publishing. Every listing is scam-scanned and then reviewed by a human before it appears — only vetted postings go live.</p>
<form method="post" action="/post">
<div class="form-field"><label>Job title</label><input name="title" required placeholder="e.g. Marketing Data Analyst"></div>
<div class="form-field"><label>Company</label><input name="company" required placeholder="e.g. Leaf Home"></div>
<div class="form-field"><label>Category</label><select name="category">{cat_opts}</select></div>
<div class="form-field"><label>Work type</label><select name="work_type">{wt_opts}</select></div>
<div class="form-field"><label>Location</label><p class="hint">City/state, or leave blank if fully remote.</p><input name="location" placeholder="e.g. Tallahassee, FL"></div>
<div class="form-field"><label>Description</label><p class="hint">The full posting — responsibilities, requirements, and pay if you can share it.</p><textarea name="description" required></textarea></div>
<div class="form-field"><label>Apply URL</label><p class="hint">Where applicants should go. The scanner checks this link too.</p><input name="apply_url" placeholder="https://..."></div>
<div class="form-field"><label>Contact (optional)</label><p class="hint">Shown publicly if approved. Use a role or company address, not a personal one.</p><input name="contact" placeholder="careers@company.com"></div>
<button class="submit-btn" type="submit">Submit for review</button></form>"""
    return shell(body, title="Submit a job — NoleCareerShield")


@app.post("/post", response_class=HTMLResponse)
def post_submit(
    title: str = Form(...), company: str = Form(...), category: str = Form("Other"),
    work_type: str = Form(...), location: str = Form(""), description: str = Form(...),
    apply_url: str = Form(""), contact: str = Form(""),
):
    add_job({"title": title, "company": company, "category": category,
             "work_type": work_type, "location": location, "description": description,
             "apply_url": apply_url, "contact": contact})
    # Same confirmation regardless of scam score — we don't tell the submitter
    # the internal verdict (that's for the reviewer), only that it's in review.
    body = """<h2 class="page">Submitted for review</h2>
<div class="banner info">Thanks — your listing has been submitted. It's been scanned and is now waiting for a human reviewer to approve it before it appears on the board. Nothing is published automatically.</div>
<a class="apply-btn" href="/">Back to home</a>"""
    return HTMLResponse(shell(body))


# ---------- admin (review queue) ----------

def _is_admin(session: str | None) -> bool:
    return bool(session) and session in _ADMIN_SESSIONS


@app.get("/admin", response_class=HTMLResponse)
def admin_home(session: str | None = Cookie(default=None)):
    if not _is_admin(session):
        body = """<h2 class="page">Reviewer sign-in</h2>
<p class="lead">The review queue is restricted. Enter the admin password.</p>
<form method="post" action="/admin/login">
<div class="form-field"><label>Password</label><input type="password" name="password" required></div>
<button class="submit-btn" type="submit">Sign in</button></form>"""
        return shell(body, title="Reviewer sign-in")

    pending = query_pending()
    if not pending:
        inner = '<div class="empty">Nothing waiting for review. New submissions will appear here.</div>'
    else:
        inner = ""
        for j in pending:
            findings = json.loads(j["findings_json"] or "[]")
            fl = "".join(
                f'<div class="finding {f["severity"]}"><b>{esc(f["title"])}</b><br>{esc(f["why"])}</div>'
                for f in findings if f["severity"] in ("critical","warning"))
            fl_block = f'<div style="margin:12px 0">{fl}</div>' if fl else '<p style="font-size:13px;color:var(--soft);margin:10px 0">No scam signals fired.</p>'
            loc = esc(j["location"]) if j["location"] else j["work_type"].title()
            url_line = f'<p style="font-size:13px;color:var(--soft);margin-top:8px;word-break:break-all">Apply: {esc(j["apply_url"])}</p>' if j["apply_url"] else ''
            inner += f"""<div class="rev-card">
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
<div><div class="job-title">{esc(j['title'])}</div><div class="job-co">{esc(j['company'])}</div></div>
<span class="rev-score {j['scam_status']}">Score {j['score']} · {j['scam_status']}</span></div>
<div class="job-meta" style="margin-top:10px"><span class="chip">{esc(j['category'])}</span><span class="chip">{esc(j['work_type'].title())}</span><span class="chip">{loc}</span></div>
{fl_block}
<div class="detail-desc" style="font-size:14px;max-height:140px;overflow:auto;background:var(--bg);padding:10px 12px;border-radius:6px">{esc(j['description'])}</div>
{url_line}
<div class="rev-actions">
<form method="post" action="/admin/approve/{j['id']}"><button class="btn-approve" type="submit">Approve &amp; publish</button></form>
<form method="post" action="/admin/reject/{j['id']}"><button class="btn-reject" type="submit">Reject</button></form>
</div></div>"""
    body = f'<h2 class="page">Review queue</h2><p class="lead">{len(pending)} submission{"s" if len(pending)!=1 else ""} waiting. The scam score is advisory — you decide what publishes.</p>{inner}'
    return shell(body, title="Review queue", admin=True)


@app.post("/admin/login")
def admin_login(response: Response, password: str = Form(...)):
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        token = secrets.token_urlsafe(24)
        _ADMIN_SESSIONS.add(token)
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400)
        return resp
    return HTMLResponse(shell(
        '<h2 class="page">Incorrect password</h2><p class="lead">Try again.</p><a class="back" href="/admin">← Back</a>'
    ), status_code=401)


@app.post("/admin/approve/{job_id}")
def admin_approve(job_id: int, session: str | None = Cookie(default=None)):
    if not _is_admin(session):
        return RedirectResponse("/admin", status_code=303)
    set_review(job_id, "approved")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reject/{job_id}")
def admin_reject(job_id: int, session: str | None = Cookie(default=None)):
    if not _is_admin(session):
        return RedirectResponse("/admin", status_code=303)
    set_review(job_id, "rejected")
    return RedirectResponse("/admin", status_code=303)
