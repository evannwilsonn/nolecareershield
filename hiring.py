"""
Employer hiring tools, per listing:

  * Ranked matches: every student who is visible to employers, scored against the listing with
    the same whole-profile fit score students see (fit.py), with the evidence behind it.
  * Invite to apply: a prefilled first message about the listing (normal messaging rules apply:
    approved employers only, students who accept messages, every message scanned).
  * Candidates: a simple tracker. Students land in it when they message about the listing, when
    the employer invites them, or when the employer saves them from the matches. Stages and
    private notes are the employer's own and aren't shown to students.
  * Stats: unique students who viewed the listing, Apply clicks, students who messaged, and
    candidates by stage. Views and clicks are totals only; employers never see who clicked.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import fit
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

STAGES = [("new", "New"), ("reviewing", "Reviewing"), ("interviewing", "Interviewing"), ("offer", "Offer"),
          ("hired", "Hired"), ("declined", "Not moving forward")]
STAGE_NAME = dict(STAGES)
SOURCES = {"messaged": ("Messaged you", "accent"), "invited": ("You invited", "gold"), "saved": ("Saved from matches", "")}
MATCH_POOL = 400          # most recently updated visible students scored per listing
MATCH_SHOW = 40
NOTE_MAX = 300

# Tables: job_views, job_apply_clicks and candidates, created in store.SCHEMA.


# ---------- recording (called from the job page and messaging) ----------

def record_view(conn, job_id: int, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO job_views (job_id, user_id, day) VALUES (?,?,?)",
                  (job_id, user_id, time.strftime("%Y-%m-%d", time.gmtime())))


def record_apply_click(conn, job_id: int, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO job_apply_clicks (job_id, user_id, created_at) VALUES (?,?,?)", (job_id, user_id, time.time()))


def add_candidate(conn, job_id: int, student_id: int, employer_id: int, source: str) -> bool:
    """Adds the student to the listing's tracker if they aren't in it yet. Returns True if added."""
    if not job_id or source not in SOURCES:
        return False
    now = time.time()
    cur = conn.execute("INSERT OR IGNORE INTO candidates (job_id, student_id, employer_id, stage, source, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?)", (job_id, student_id, employer_id, "new", source, now, now))
    return cur.rowcount > 0


# ---------- queries ----------

def own_job(conn, user: dict, job_id: int) -> dict | None:
    return store.row(conn, "SELECT * FROM jobs WHERE id = ? AND employer_id = ?", (job_id, user["id"]))


def ranked_matches(conn, job: dict, limit: int = MATCH_SHOW) -> list[tuple[dict, dict]]:
    """(fit result, profile) for visible students, best first."""
    ids = conn.execute("SELECT s.user_id FROM student_profiles s JOIN users u ON u.id = s.user_id "
                       "WHERE s.visible_to_employers = 1 AND s.display_name != '' AND s.major != '' AND u.verified = 1 "
                       "ORDER BY s.updated_at DESC LIMIT ?", (MATCH_POOL,)).fetchall()
    out = []
    for (uid,) in ids:
        p = store.student_profile(conn, uid)
        if not p or not (p["skills"] or p["resume_text"] or p["items"]):
            continue
        out.append((fit.fit_score(job, p), p))
    out.sort(key=lambda x: (-x[0]["score"], x[1]["display_name"].lower()))
    return out[:limit]


def job_stats(conn, job: dict) -> dict:
    jid = job["id"]
    week = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    stages = {r["stage"]: r["n"] for r in store.rows(conn, "SELECT stage, COUNT(*) AS n FROM candidates WHERE job_id = ? GROUP BY stage", (jid,))}
    return {"views": one("SELECT COUNT(DISTINCT user_id) FROM job_views WHERE job_id = ?", jid),
            "views_week": one("SELECT COUNT(DISTINCT user_id) FROM job_views WHERE job_id = ? AND day >= ?", jid, week),
            "clicks": one("SELECT COUNT(*) FROM job_apply_clicks WHERE job_id = ?", jid),
            "messaged": one("SELECT COUNT(*) FROM conversations WHERE job_id = ? AND employer_id = ? AND started_by = student_id", jid, job["employer_id"] or 0),
            "candidates": sum(stages.values()), "stages": stages}


# ---------- pages ----------

STATUS_PILL = {"approved": ("ok", "Live"), "pending": ("warn", "In review"), "rejected": ("bad", "Not approved"), "removed": ("bad", "Removed")}


def _stat(n, label: str, sub: str = "") -> str:
    return f'<div class="stat"><div class="n">{n}</div><div class="l">{esc(label)}</div>{f"<div class=s>{esc(sub)}</div>" if sub else ""}</div>'


@router.get("/hiring", response_class=HTMLResponse)
def overview(request: Request):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "hiring")
    with store.db() as conn:
        jobs = store.rows(conn, "SELECT * FROM jobs WHERE employer_id = ? ORDER BY id DESC LIMIT 100", (user["id"],))
        stats = {j["id"]: job_stats(conn, j) for j in jobs}
    head = ui.page_head("Your listings", "Views, Apply clicks, ranked student matches and a candidate tracker for every listing you post.", num="Hiring")
    if not jobs:
        return web.page(head + '<div class="empty">No listings yet. <a href="/post">Post your first job</a> and it shows up here once it\'s submitted.</div>',
                        "Your listings", active="/hiring")
    rows_html = ""
    for j in jobs:
        s, (tone, label) = stats[j["id"]], STATUS_PILL.get(j["review_status"], ("", j["review_status"]))
        rows_html += (f'<a class="card lift hjob" href="/hiring/{int(j["id"])}"><div class="row between" style="align-items:flex-start">'
                      f'<div style="min-width:0"><div class="job-title">{esc(j["title"])}</div><div class="job-co">{esc(j["company"])} · {esc(j["work_type"].title())}'
                      f'{" · " + esc(j["location"]) if j["location"] else ""}</div></div><span class="pill {tone}">{esc(label)}</span></div>'
                      f'<div class="stats sm">{_stat(s["views"], "students viewed")}{_stat(s["clicks"], "clicked Apply")}'
                      f'{_stat(s["messaged"], "messaged you")}{_stat(s["candidates"], "candidates")}</div></a>')
    body = head + f'<div class="row" style="margin-bottom:14px"><a class="b" href="/post">{ui.icon("plus", 16)} Post a job</a></div>{rows_html}'
    return web.page(body, "Your listings", active="/hiring")


def _tabs(jid: int, tab: str, n_cand: int) -> str:
    items = [("matches", "Ranked matches"), ("candidates", f"Candidates ({n_cand})")]
    return ('<div class="seg" role="tablist" style="margin:18px 0">' + "".join(
        f'<a href="/hiring/{jid}?tab={k}"{" class=on aria-current=page" if k == tab else ""}>{esc(v)}</a>' for k, v in items) + "</div>")


def _evidence(f: dict) -> str:
    bits = []
    for m in f["matched"][:3]:
        where = m["where"][0].replace("Your skills list", "skills list").replace("Your resume", "resume").replace("Your headline and about", "about")
        bits.append(f"<b>{esc(m['skill'])}</b> <span class=faint>({esc(where)})</span>")
    met = sum(1 for c in f["checklist"] if c["status"] == "met")
    tail = f'<span class="faint">{met} of {len(f["checklist"])} requirements met</span>' if f["checklist"] else ""
    return " · ".join(bits + ([tail] if tail else []))


def _match_card(conn, jid: int, f: dict, p: dict, can_invite: bool, saved: bool) -> str:
    uid = int(p["user_id"])
    sub = " · ".join(x for x in (p["major"], p["grad_term"] and "Graduating " + p["grad_term"]) if x)
    tone = "ok" if f["score"] >= 65 else "warn" if f["score"] < 45 else ""
    parts = "".join(f'<span class="chip" title="{esc(x["detail"])}">{esc(x["name"])} {x["score"]}</span>' for x in f["parts"])
    csrf = ui.user_csrf_input()
    save = ('<span class="pill ok">In candidates</span>' if saved else
            f'<form method="post" action="/hiring/{jid}/save" class="navform">{csrf}<input type="hidden" name="student" value="{uid}">'
            '<button class="b sm sec" type="submit">Save to candidates</button></form>')
    headline = f'<p style="margin-top:8px">{esc(p["headline"])}</p>' if p["headline"] else ""
    invite = (f'<a class="b sm" href="/messages/new?to={uid}&amp;job={jid}&amp;invite=1">{ui.icon("chat", 14)} Invite to apply</a>'
              if can_invite and p["allow_messages"] else "")
    return (f'<div class="card mcard"><div class="row between" style="align-items:flex-start;gap:12px">'
            f'<div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:{f["score"]}"><b>{f["score"]}</b></div>'
            f'<div style="min-width:0">{web.person(p["display_name"], sub, "stu", f"/u/{uid}")}</div></div>'
            f'<span class="pill {tone}">{esc(f["label"])}</span></div>'
            f'{headline}'
            f'<p class="small" style="margin-top:8px">{_evidence(f)}</p><div class="chips" style="margin-top:8px">{parts}</div>'
            f'<div class="row" style="margin-top:12px">{invite}{save}<a class="b sm ghost" href="/u/{uid}">View profile</a></div></div>')


@router.get("/hiring/{job_id}", response_class=HTMLResponse)
def listing(job_id: int, request: Request, tab: str = "matches"):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "hiring_listing")
    tab = tab if tab in ("matches", "candidates") else "matches"
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        if not j:
            return web.page(ui.page_head("Listing not found") + '<a class="b sec" href="/hiring">Your listings</a>', "Not found", active="/hiring", status=404)
        approved_emp = store.employer_approved(conn, user["id"])
        s = job_stats(conn, j)
        cands = store.rows(conn, "SELECT * FROM candidates WHERE job_id = ? ORDER BY updated_at DESC", (job_id,))
        if tab == "matches" and approved_emp:
            matches = ranked_matches(conn, j)
            content = _matches_html(conn, j, matches, {c["student_id"] for c in cands})
        elif tab == "candidates" and approved_emp:
            content = _candidates_html(conn, j, cands)
        else:
            content = ui.banner("info", "Ranked matches and student profiles open once a reviewer approves your organization. "
                                        "Your listing's stats are already counting.")
    tone, label = STATUS_PILL.get(j["review_status"], ("", j["review_status"]))
    rate = f'{round(100 * s["clicks"] / s["views"])}% of viewers' if s["views"] else ""
    stage_bits = " · ".join(f'{n} {STAGE_NAME.get(k, k).lower()}' for k, n in sorted(s["stages"].items(), key=lambda kv: [x[0] for x in STAGES].index(kv[0]) if kv[0] in STAGE_NAME else 99))
    week_note = f"{s['views_week']} this week"
    view_link = f'<a class="b sm sec" href="/job/{int(j["id"])}">View listing</a>' if j["review_status"] == "approved" else ""
    body = (f'<a class="back" href="/hiring">← Your listings</a><div class="row between" style="align-items:flex-start;margin-top:6px">'
            f'<div><h2 class="page" style="margin:0">{esc(j["title"])}</h2><p class="job-co">{esc(j["company"])} · {esc(j["work_type"].title())}'
            f'{" · " + esc(j["location"]) if j["location"] else ""}</p></div><div class="row"><span class="pill {tone}">{esc(label)}</span>{view_link}</div></div>'
            f'<div class="stats">{_stat(s["views"], "students viewed", week_note)}{_stat(s["clicks"], "clicked Apply", rate)}'
            f'{_stat(s["messaged"], "messaged you")}{_stat(s["candidates"], "candidates", stage_bits)}</div>'
            f'<p class="small faint">Views and Apply clicks are totals. You see who a student is only when they message you, you invite them, or you save them from matches.</p>'
            + _tabs(job_id, tab, len(cands)) + content)
    return web.page(body, j["title"], active="/hiring")


def _matches_html(conn, j: dict, matches: list, saved: set[int]) -> str:
    live = j["review_status"] == "approved"
    note = ("" if live else ui.banner("info", "Invites open once this listing is approved. You can already see who fits and save them."))
    if not matches:
        return note + '<div class="empty">No students match yet. Matches come from students who made their profile visible to approved employers.</div>'
    strong = sum(1 for f, _ in matches if f["score"] >= 65)
    intro = (f'<p class="small muted" style="margin-bottom:12px"><b>{strong}</b> good or strong fit{"s" if strong != 1 else ""} among {len(matches)} students ranked. '
             'Each score uses the student\'s whole profile: skills, experience, projects, education, certifications and what they\'re looking for.</p>')
    return note + intro + "".join(_match_card(conn, j["id"], f, p, live, int(p["user_id"]) in saved) for f, p in matches)


def _candidates_html(conn, j: dict, cands: list[dict]) -> str:
    if not cands:
        return ('<div class="empty">No candidates yet. Students appear here when they message you about this listing, '
                'when you invite them, or when you save them from the ranked matches.</div>')
    csrf = ui.user_csrf_input()
    out = []
    for c in cands:
        p = store.student_profile(conn, c["student_id"])
        if not p:
            continue
        f = fit.fit_score(j, p)
        convo = store.row(conn, "SELECT id FROM conversations WHERE student_id = ? AND employer_id = ? ORDER BY last_at DESC LIMIT 1",
                          (c["student_id"], j["employer_id"]))
        src, src_tone = SOURCES.get(c["source"], (c["source"], ""))
        opts = "".join(f'<option value="{k}"{" selected" if k == c["stage"] else ""}>{esc(v)}</option>' for k, v in STAGES)
        sub = " · ".join(x for x in (p["major"], p["grad_term"] and "Graduating " + p["grad_term"]) if x)
        msg = (f'<a class="b sm ghost" href="/messages/{int(convo["id"])}">Open conversation</a>' if convo else
               (f'<a class="b sm ghost" href="/messages/new?to={int(c["student_id"])}&amp;job={int(j["id"])}&amp;invite=1">Invite to apply</a>'
                if j["review_status"] == "approved" and p["allow_messages"] else ""))
        out.append(f'<div class="card mcard" id="c{int(c["student_id"])}"><div class="row between" style="align-items:flex-start;gap:12px">'
                   f'<div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:{f["score"]}"><b>{f["score"]}</b></div>'
                   f'<div style="min-width:0">{web.person(p["display_name"], sub, "stu", "/u/" + str(int(c["student_id"])))}</div></div>'
                   f'<div class="row"><span class="pill {src_tone}">{esc(src)}</span><span class="small faint">{esc(web.ago(c["created_at"]))}</span></div></div>'
                   f'<p class="small" style="margin-top:8px">{_evidence(f)}</p>'
                   f'<form method="post" action="/hiring/{int(j["id"])}/stage" class="cform">{csrf}<input type="hidden" name="student" value="{int(c["student_id"])}">'
                   f'<div class="form-field"><label for="st{int(c["student_id"])}">Stage</label><select id="st{int(c["student_id"])}" name="stage">{opts}</select></div>'
                   f'<div class="form-field"><label for="nt{int(c["student_id"])}">Private note</label><input id="nt{int(c["student_id"])}" name="note" maxlength="{NOTE_MAX}" value="{esc(c["note"])}" placeholder="Only your team sees this"></div>'
                   f'<button class="b sm" type="submit">Update</button></form><div class="row" style="margin-top:8px">{msg}<a class="b sm ghost" href="/u/{int(c["student_id"])}">View profile</a></div></div>')
    counts = " · ".join(f"{sum(1 for c in cands if c['stage'] == k)} {v.lower()}" for k, v in STAGES if any(c["stage"] == k for c in cands))
    return f'<p class="small muted" style="margin-bottom:12px">{esc(counts)}. Stages and notes are private to your organization.</p>' + "".join(out)


@router.post("/hiring/{job_id}/save")
def save_match(job_id: int, request: Request, student: int = Form(0), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/hiring/{job_id}", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        p = store.row(conn, "SELECT visible_to_employers FROM student_profiles WHERE user_id = ?", (student,))
        if j and p and p["visible_to_employers"] and store.employer_approved(conn, user["id"]):
            add_candidate(conn, job_id, student, user["id"], "saved")
    return RedirectResponse(f"/hiring/{job_id}?tab=matches", status_code=303)


@router.post("/hiring/{job_id}/stage")
def set_stage(job_id: int, request: Request, student: int = Form(0), stage: str = Form(""), note: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/hiring/{job_id}?tab=candidates", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    note = security._CONTROL_CHARS_RE.sub("", note or "").strip()[:NOTE_MAX]
    if stage in STAGE_NAME:
        with store.db() as conn:
            if own_job(conn, user, job_id):
                conn.execute("UPDATE candidates SET stage = ?, note = ?, updated_at = ? WHERE job_id = ? AND student_id = ? AND employer_id = ?",
                             (stage, note, time.time(), job_id, student, user["id"]))
    return RedirectResponse(f"/hiring/{job_id}?tab=candidates#c{int(student)}", status_code=303)


def invite_text(conn, employer_id: int, student: dict, job: dict) -> str:
    e = store.employer_profile(conn, employer_id) or {}
    first = (student.get("display_name") or "").split(" ")[0]
    me = f"I'm {e['contact_name']}, {e['contact_title']} at {e['company']}. " if e.get("contact_name") and e.get("company") else ""
    return (f"Hi {first}! {me}Your profile looks like a strong fit for our {job['title']} role, and we'd love for you to apply. "
            "You'll find the listing and the Apply link on NoleCareerShield. Happy to answer any questions here.")
