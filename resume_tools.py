"""
Resume studio: review, edit and tailor a resume.

  * Review  - a 0-100 score in six categories, specific findings, and a suggested rewrite for
              every weak bullet. "AI review" adds a written critique and rewrites from Claude.
  * Edit    - the resume text, bullet-by-bullet improvement, download as .docx or .txt.
  * Tailor  - pick a listing from the board (or paste a job description): match score, skills
              and keywords present and missing, which bullets to lead with, and a tailored
              summary. "AI tailor" rewrites bullets toward the job. Save it as a version.

Honesty rule for every suggestion: rephrase what the student wrote, never add experience.
Unknown numbers stay as [placeholders]; missing skills come with "only add this if true".
"""

from __future__ import annotations

import json
import re
import time

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import ai
import matching
import profiles
import resume_engine
import security
import store
import ui
import web
from ui import esc

router = APIRouter()
MAX_VERSIONS = 10


def _profile(conn, user) -> dict:
    return profiles.ensure_student(conn, user["id"])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _grounded(rewrites: list, resume: str, key: str = "original") -> list:
    """Keep only rewrites whose 'original' really appears in the resume, so the model can't slip in new lines."""
    have = _norm(resume)
    out = []
    for r in rewrites or []:
        if isinstance(r, dict) and isinstance(r.get(key), str) and len(r[key]) > 8 and _norm(r[key])[:60] in have:
            out.append(r)
    return out


# ---------- AI helpers ----------

def ai_review(text: str) -> dict | None:
    schema = {"type": "object", "properties": {
        "summary": {"type": "string", "description": "Two or three sentences: overall impression for a student resume"},
        "strengths": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        "priorities": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "detail": {"type": "string"}}, "required": ["title", "detail"]}},
        "rewrites": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "original": {"type": "string", "description": "The exact bullet from the resume"},
            "improved": {"type": "string"}, "why": {"type": "string"}}, "required": ["original", "improved", "why"]}}},
        "required": ["summary", "strengths", "priorities", "rewrites"]}
    system = ("You are an expert university career coach reviewing an FSU student's resume for internships and entry-level roles, "
              "the way a recruiter at a top employer would skim it in 30 seconds. Be specific and kind. Prioritize: impact with numbers, "
              "strong verbs, relevance, one page, ATS-readable sections. Rewrites must keep every fact the same; where a number is missing "
              "use a [placeholder]. Quote bullets exactly in 'original'.")
    try:
        return ai.structured(system, ai.tag("resume", text, 14000) + "\n\nReview this resume.", "resume_review", schema, max_tokens=1800)
    except ai.AIUnavailable:
        return None


def ai_bullet(bullet: str, context: str = "") -> dict | None:
    schema = {"type": "object", "properties": {
        "options": {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "string"}},
        "tip": {"type": "string"}}, "required": ["options", "tip"]}
    system = ("Rewrite one resume bullet for a college student three ways: concise, results-first, and with a clear action verb. "
              "Keep every fact; never add tools, numbers or outcomes that aren't there. Put [number] where a figure would help. "
              "Each option under 30 words. The tip is one sentence on what detail would make it stronger.")
    try:
        return ai.structured(system, ai.tag("resume", bullet, 600) + (("\nContext: " + ai.tag("job", context, 400)) if context else ""),
                             "bullet_options", schema, max_tokens=600)
    except ai.AIUnavailable:
        return None


def ai_tailor(resume: str, title: str, job_text: str, profile: dict) -> dict | None:
    schema = {"type": "object", "properties": {
        "summary": {"type": "string", "description": "A 2-sentence resume summary for this job, true to the resume"},
        "rewrites": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "original": {"type": "string"}, "tailored": {"type": "string"}, "why": {"type": "string"}},
            "required": ["original", "tailored", "why"]}},
        "emphasize": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
        "gaps": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
            "skill": {"type": "string"}, "advice": {"type": "string"}}, "required": ["skill", "advice"]}},
        "cover_note": {"type": "string", "description": "A short, specific note (under 110 words) the student could send with an application"}},
        "required": ["summary", "rewrites", "emphasize", "gaps", "cover_note"]}
    system = ("You tailor an FSU student's resume to one job posting, like LinkedIn's and Handshake's resume assistants. Reword existing bullets "
              "to mirror the job's language where it is true, reorder emphasis, and write a summary. Never invent experience, tools, numbers "
              "or results; if the job wants something the resume doesn't show, list it under gaps with honest advice (a class project, a "
              "certification, or leave it off). Quote original bullets exactly.")
    about = json.dumps({k: profile.get(k) for k in ("major", "minor", "grad_term", "skills") if profile.get(k)})
    content = (ai.tag("resume", resume, 12000) + "\n" + ai.tag("job", f"{title}\n\n{job_text}", 6000) +
               f"\nStudent profile: {ai.tag('profile', about, 800)}\nTailor the resume to this job.")
    try:
        return ai.structured(system, content, "tailored_resume", schema, max_tokens=2200)
    except ai.AIUnavailable:
        return None


def _take_ai(conn, user) -> bool:
    return ai.enabled() and store.ai_take(conn, user["id"], ai.daily_limit())


# ---------- page pieces ----------

def _tabs(active: str) -> str:
    tabs = [("review", "Review"), ("edit", "Edit"), ("tailor", "Tailor to a job"), ("versions", "Versions")]
    return '<div class="seg" role="tablist" style="margin-bottom:18px">' + "".join(
        f'<a href="/resume?tab={k}"{" class=on aria-current=page" if k == active else ""}>{v}</a>' for k, v in tabs) + "</div>"


def _upload_card(first: bool) -> str:
    title = "Add your resume" if first else "Replace your resume"
    return f"""<div class="card"><h3 class="sec" style="margin-top:0">{title}</h3>
<form method="post" action="/resume/upload" enctype="multipart/form-data">{ui.user_csrf_input()}
<div class="form-field"><label for="r-file">Upload a file</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. We keep the text only.</p>
<input id="r-file" type="file" name="resume" accept=".pdf,.docx,.txt"></div>
<div class="form-field"><label for="r-paste">Or paste it</label><textarea id="r-paste" name="paste" maxlength="20000" placeholder="Paste your resume text"></textarea></div>
<button class="submit-btn" type="submit">{"Review my resume" if first else "Replace"}</button></form></div>"""


def _review_html(rv: dict) -> str:
    cats = "".join(f'<div class="cat"><span>{esc(c["name"])}</span><div class="meter{" ok" if c["score"] >= 0.8 * c["max"] else " warn" if c["score"] < 0.5 * c["max"] else ""}">'
                   f'<i style="width:{round(100 * c["score"] / c["max"])}%"></i></div><span>{c["score"]}/{c["max"]}</span></div>' for c in rv["categories"])
    sev = {"bad": ("bad", "Fix"), "warn": ("warn", "Improve"), "info": ("info", "Tip")}
    finds = "".join(f'<li><span class="pill {sev[f["severity"]][0]}">{sev[f["severity"]][1]}</span> {esc(f["message"])}</li>' for f in rv["findings"]) \
        or "<li>No issues found. Nice work.</li>"
    bullets = ""
    for b in rv["bullets"]:
        bullets += (f'<div class="sugg-item"><div class="was">{esc(b["text"])}</div><div class="now">{esc(b["rewrite"])}</div>'
                    f'<div class="iss">{esc(" · ".join(b["issues"]))}</div>'
                    f'<form method="post" action="/resume/apply" style="margin-top:8px">{ui.user_csrf_input()}'
                    f'<input type="hidden" name="old" value="{esc(b["text"])}"><input type="hidden" name="new" value="{esc(b["rewrite"])}">'
                    '<button class="b sm sec" type="submit">Use this rewrite</button> <span class="small faint">Fill in any [placeholder] after.</span></form></div>')
    stats = rv["stats"]
    return f"""<div class="split"><div class="card"><div class="score"><div class="ring" style="--p:{rv['score']}"><b>{rv['score']}</b></div>
<div><div class="eyebrow">Resume score</div><h2 style="font-family:var(--serif);font-weight:500;font-size:24px">{esc(rv['grade'])}</h2>
<p class="small muted">{stats['words']} words · {stats['bullets']} bullets · {stats['quantified']} with numbers</p></div></div>
<div style="margin-top:14px">{cats}</div></div>
<div class="card"><h3 class="sec" style="margin-top:0">What to fix first</h3><ul style="list-style:none;padding:0" class="stack">{finds}</ul></div></div>
<h3 class="sec">Bullet rewrites <small>{len(rv['bullets'])} to improve</small></h3>{bullets or '<p class="muted">Every bullet already starts strong and has a number.</p>'}"""


def _ai_review_html(o: dict, resume: str) -> str:
    strengths = "".join(f'<li>{esc(s)}</li>' for s in o.get("strengths", [])[:4])
    pri = "".join(f'<li><b>{esc(p.get("title", ""))}</b><span class="ev">{esc(p.get("detail", ""))}</span></li>' for p in o.get("priorities", [])[:5])
    rw = ""
    for r in _grounded(o.get("rewrites", []), resume)[:6]:
        rw += (f'<div class="sugg-item"><div class="was">{esc(r["original"])}</div><div class="now">{esc(r["improved"])}</div>'
               f'<div class="iss" style="color:var(--muted)">{esc(r.get("why", ""))}</div>'
               f'<form method="post" action="/resume/apply" style="margin-top:8px">{ui.user_csrf_input()}'
               f'<input type="hidden" name="old" value="{esc(r["original"])}"><input type="hidden" name="new" value="{esc(r["improved"])}">'
               '<button class="b sm sec" type="submit">Use this rewrite</button></form></div>')
    return f"""<h3 class="sec">AI review <small>by Claude</small></h3><div class="card"><p>{esc(o.get('summary', ''))}</p>
{f'<h4 style="margin:12px 0 4px">Working well</h4><ul style="margin-left:18px">{strengths}</ul>' if strengths else ''}
{f'<ul class="reasons">{pri}</ul>' if pri else ''}</div>{rw}"""


def _studio(conn, user, tab: str = "review", extra: str = "", notice: str = "", status: int = 200, job: int = 0) -> HTMLResponse:
    p = _profile(conn, user)
    head = ui.page_head("Resume studio", "Score it, fix it line by line, and tailor it to any job on the board. Suggestions rephrase what you wrote; they never make things up.",
                        num="Resume")
    note = ui.banner("verified", notice) if notice else ""
    if not p.get("resume_text"):
        return web.page(head + note + extra + _upload_card(True), "Resume studio", active="/resume", js=True, status=status)
    text = p["resume_text"]
    body = head + note + _tabs(tab)
    ai_line = ('<p class="aimode" style="margin:6px 0 0">AI features use Claude (Anthropic). Your resume text is sent only when you press an AI button.</p>'
               if ai.enabled() else '<p class="aimode" style="margin:6px 0 0">Using the built-in reviewer. AI rewrites turn on when the site admin adds an AI key.</p>')
    if tab == "review":
        rv = resume_engine.review(text)
        ai_btn = (f'<form method="post" action="/resume/ai-review" class="navform">{ui.user_csrf_input()}<button class="b" type="submit">{ui.icon("spark", 16)} Get an AI review</button></form>'
                  if ai.enabled() else "")
        body += extra + _review_html(rv) + f'<div class="row" style="margin-top:18px">{ai_btn}<a class="b sec" href="/resume?tab=edit">Edit resume</a></div>{ai_line}'
    elif tab == "edit":
        body += f"""{extra}<div class="split"><form method="post" action="/resume/save" class="card">{ui.user_csrf_input()}
<div class="row between" style="margin-bottom:8px"><label for="r-text" style="margin:0">Your resume</label><span class="small faint">{esc(p.get('resume_name') or '')}</span></div>
<textarea id="r-text" class="resume" name="text" maxlength="20000" data-count>{esc(text)}</textarea>
<div class="row" style="margin-top:10px"><button class="b" type="submit">Save</button>
<a class="b sec" href="/resume/download.docx">Download .docx</a><a class="b ghost" href="/resume/download.txt">.txt</a></div></form>
<div><div class="card"><h3 class="sec" style="margin-top:0">Improve a bullet</h3><p class="small muted">Paste one bullet. You'll get stronger versions that keep your facts.</p>
<form method="post" action="/resume/bullet" data-bullet>{ui.user_csrf_input()}<label for="b-text" class="hp">Bullet</label>
<textarea id="b-text" name="bullet" maxlength="400" required style="min-height:80px" placeholder="Responsible for posting on the club Instagram"></textarea>
<button class="b sm" type="submit" style="margin-top:8px">{ui.icon("spark", 14)} Improve</button></form><div id="bullet-out"></div></div>
<div class="card" style="margin-top:12px">{_upload_card(False).replace('class="card"', 'class=""', 1)}</div></div></div>{ai_line}"""
    elif tab == "tailor":
        with_jobs = store.live_jobs(conn, security.LISTING_TTL_DAYS)
        ranked = matching.rank_jobs(with_jobs, p, limit=40) if with_jobs else []
        opts = "".join(f'<option value="{int(r["job"]["id"])}"{" selected" if int(r["job"]["id"]) == job else ""}>{esc(r["job"]["title"])} · {esc(r["job"]["company"])} ({r["score"]}% match)</option>' for r in ranked)
        body += f"""{extra}<form method="post" action="/resume/tailor" class="card">{ui.user_csrf_input()}
<div class="form-field"><label for="t-job">A job on the board</label><select id="t-job" name="job_id"><option value="">Choose a listing...</option>{opts}</select></div>
<div class="or"><span>Or paste a job description</span></div>
<div class="form-field"><label for="t-title">Job title</label><input id="t-title" name="title" maxlength="200" placeholder="Marketing Intern"></div>
<div class="form-field"><label for="t-desc">Job description</label><textarea id="t-desc" name="description" maxlength="8000" placeholder="Paste the posting"></textarea></div>
<div class="row"><button class="b" type="submit" name="mode" value="builtin">Compare</button>
{f'<button class="b ghost" type="submit" name="mode" value="ai">{ui.icon("spark", 14)} AI tailor</button>' if ai.enabled() else ''}</div></form>{ai_line}"""
    else:
        vs = store.rows(conn, "SELECT id, name, job_id, created_at, length(body) AS n FROM resume_versions WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
        rows = "".join(f"""<tr><td><b>{esc(v['name'])}</b><div class="small faint">{esc(web.ago(v['created_at']))}</div></td>
<td class="row"><a class="b sm sec" href="/resume/versions/{int(v['id'])}.docx">.docx</a>
<form method="post" action="/resume/versions/{int(v['id'])}/use" class="navform">{ui.user_csrf_input()}<button class="b sm ghost" type="submit">Make main</button></form>
<form method="post" action="/resume/versions/{int(v['id'])}/delete" class="navform">{ui.user_csrf_input()}<button class="b sm danger" type="submit">Delete</button></form></td></tr>""" for v in vs)
        body += extra + (f'<div class="card"><table class="t"><tr><th>Version</th><th>Actions</th></tr>{rows}</table></div>' if rows else
                         '<div class="empty">No saved versions yet. Tailor your resume to a job and save it as a version.</div>') + \
            f'<p class="small faint" style="margin-top:8px">Up to {MAX_VERSIONS} versions.</p>'
    return web.page(body, "Resume studio", active="/resume", js=True, status=status)


# ---------- routes ----------

@router.get("/resume", response_class=HTMLResponse)
def studio(request: Request, tab: str = "review", job: int = 0):
    user = web.require_user(request, "student")
    tab = tab if tab in ("review", "edit", "tailor", "versions") else "review"
    with store.db() as conn:
        return _studio(conn, user, tab, job=job)


@router.post("/resume/upload", response_class=HTMLResponse)
async def upload(request: Request):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.upload_limiter, f"u{user['id']}", "resume uploads")
    form = await request.form()
    if not web.csrf_ok(request, form.get("csrf")):
        return RedirectResponse("/resume", status_code=303)
    f = form.get("resume")
    paste = str(form.get("paste") or "").strip()
    try:
        if f is not None and hasattr(f, "read") and getattr(f, "filename", ""):
            data = await f.read(resume_engine.MAX_UPLOAD + 1)
            text, name = resume_engine.extract_text(f.filename, data), f.filename[:120]
        elif paste:
            if len(paste) > resume_engine.MAX_TEXT:
                raise resume_engine.ResumeError("That's longer than 20,000 characters.")
            text, name = resume_engine.clean(paste), "Pasted text"
            if len(text) < 80:
                raise resume_engine.ResumeError("That's too short to be a resume. Paste the whole thing.")
        else:
            raise resume_engine.ResumeError("Choose a file or paste your resume.")
    except resume_engine.ResumeError as e:
        with store.db() as conn:
            return _studio(conn, user, "review", extra=ui.banner("warning", str(e)), status=400)
    with store.db() as conn:
        p = _profile(conn, user)
        fields = dict(resume_text=text, resume_name=name, resume_updated=time.time())
        if not p.get("skills"):
            fields["skills"] = matching.extract_skills(text)[:20]
        profiles.save_student(conn, user["id"], **fields)
    return RedirectResponse("/resume?tab=review", status_code=303)


@router.post("/resume/save", response_class=HTMLResponse)
def save(request: Request, text: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "saving")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/resume?tab=edit", status_code=303)
    with store.db() as conn:
        if len(text) > resume_engine.MAX_TEXT or len(text.strip()) < 80:
            return _studio(conn, user, "edit", extra=ui.banner("warning", "A resume needs 80 to 20,000 characters."), status=400)
        profiles.save_student(conn, user["id"], resume_text=resume_engine.clean(text), resume_updated=time.time())
        return _studio(conn, user, "edit", notice="Saved.")


@router.post("/resume/apply")
def apply(request: Request, old: str = Form(""), new: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf) or not old.strip() or len(new) > 600:
        return RedirectResponse("/resume", status_code=303)
    with store.db() as conn:
        p = _profile(conn, user)
        text = p.get("resume_text") or ""
        if old in text:
            text = text.replace(old, security._CONTROL_CHARS_RE.sub("", new.replace("\n", " ")).strip(), 1)
            profiles.save_student(conn, user["id"], resume_text=text, resume_updated=time.time())
    return RedirectResponse("/resume?tab=review", status_code=303)


@router.post("/resume/ai-review", response_class=HTMLResponse)
def ai_review_route(request: Request, csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    with store.db() as conn:
        p = _profile(conn, user)
        if not web.csrf_ok(request, csrf) or not p.get("resume_text"):
            return RedirectResponse("/resume", status_code=303)
        if not _take_ai(conn, user):
            return _studio(conn, user, "review", extra=ui.banner("info", "AI review isn't available right now (or you've used today's AI allowance). The built-in review is below."))
    o = ai_review(p["resume_text"])
    with store.db() as conn:
        if not o:
            return _studio(conn, user, "review", extra=ui.banner("info", "The AI review couldn't run just now. The built-in review is below."))
        return _studio(conn, user, "review", extra=_ai_review_html(o, p["resume_text"]))


def _bullet_result(bullet: str, user, conn) -> dict:
    base = resume_engine.improve_bullet(bullet)
    options = [base["rewrite"]]
    tip = " ".join(base["tips"][:1])
    mode = "builtin"
    if _take_ai(conn, user):
        o = ai_bullet(bullet)
        if o and o.get("options"):
            options = [s for s in o["options"] if isinstance(s, str)][:3] or options
            tip = o.get("tip") or tip
            mode = "ai"
    return {"original": base["original"], "options": options, "tip": tip, "mode": mode}


def _bullet_html(r: dict) -> str:
    opts = "".join(f'<div class="sugg-item"><div class="now">{esc(o)}</div>'
                   f'<button class="b sm sec" type="button" data-copy="{esc(o)}" style="margin-top:8px">Copy</button></div>' for o in r["options"])
    return f'<div style="margin-top:12px">{opts}<p class="small muted" style="margin-top:8px">{esc(r["tip"])}</p></div>'


@router.post("/resume/bullet", response_class=HTMLResponse)
def bullet_form(request: Request, bullet: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    with store.db() as conn:
        if not web.csrf_ok(request, csrf) or not (3 <= len(bullet.strip()) <= 400):
            return _studio(conn, user, "edit", extra=ui.banner("warning", "Paste one bullet (up to 400 characters)."), status=400)
        r = _bullet_result(bullet, user, conn)
        return _studio(conn, user, "edit", extra=f'<div class="card" style="margin-bottom:14px"><b>Suggestions for:</b> <span class="muted">{esc(r["original"])}</span>{_bullet_html(r)}</div>')


@router.post("/api/resume/bullet")
async def bullet_api(request: Request):
    user = web.current_user(request)
    if not user or user["role"] != "student":
        return JSONResponse({"error": "Log in first."}, status_code=401)
    if not web.csrf_ok(request, request.headers.get("x-csrf-token", "")):
        return JSONResponse({"error": "Refresh the page and try again."}, status_code=400)
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    try:
        data = await request.json()
        bullet = str(data.get("bullet", ""))
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Bad request."}, status_code=400)
    if not (3 <= len(bullet.strip()) <= 400):
        return JSONResponse({"error": "Paste one bullet (up to 400 characters)."}, status_code=400)
    with store.db() as conn:
        r = _bullet_result(bullet, user, conn)
    return JSONResponse({**r, "html": _bullet_html(r)})


def _tailor_html(t: dict, o: dict | None, resume: str, title: str, job_id: int, version_text: str) -> str:
    pills = lambda xs, cls: "".join(f'<span class="pill {cls}">{esc(x)}</span>' for x in xs) or '<span class="faint small">None</span>'
    lead = "".join(f'<li><b>{esc(b["text"])}</b><span class="ev">{esc(b["why"])}</span></li>' for b in t["lead_bullets"])
    gaps = "".join(f'<li><b>{esc(g["skill"])}</b><span class="ev">{esc(g["advice"])}</span></li>' for g in (o or {}).get("gaps", t["gaps"])[:6])
    summary = (o or {}).get("summary") or t["summary"]
    rw = ""
    if o:
        for r in _grounded(o.get("rewrites", []), resume)[:6]:
            rw += (f'<div class="sugg-item"><div class="was">{esc(r["original"])}</div><div class="now">{esc(r["tailored"])}</div>'
                   f'<div class="iss" style="color:var(--muted)">{esc(r.get("why", ""))}</div></div>')
    cover = (f'<h3 class="sec">A short note to send with it</h3><div class="card"><p style="white-space:pre-wrap">{esc(o["cover_note"])}</p>'
             f'<button class="b sm sec" type="button" data-copy="{esc(o["cover_note"])}" style="margin-top:8px">Copy</button></div>') if o and o.get("cover_note") else ""
    return f"""<div class="card" style="margin-bottom:16px"><div class="score"><div class="ring" style="--p:{t['match']}"><b>{t['match']}</b></div>
<div><div class="eyebrow">Match with</div><h2 style="font-family:var(--serif);font-weight:500;font-size:22px">{esc(title or 'this job')}</h2>
<p class="small muted">Based on the skills and keywords the job asks for.</p></div></div>
<div class="split" style="margin-top:14px"><div><b class="small">Skills you show</b><div class="kw" style="margin-top:6px">{pills(t['skills_present'], 'ok')}</div></div>
<div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">{pills(t['skills_missing'], 'warn')}</div></div></div>
<div style="margin-top:12px"><b class="small">Keywords to use where true</b><div class="kw" style="margin-top:6px">{pills(t['keywords_missing'], '')}</div></div></div>
<h3 class="sec">Suggested summary</h3><div class="card"><p>{esc(summary)}</p><button class="b sm sec" type="button" data-copy="{esc(summary)}" style="margin-top:8px">Copy</button></div>
{f'<h3 class="sec">Tailored bullets</h3>{rw}' if rw else ''}
{f'<h3 class="sec">Lead with these bullets</h3><ul class="reasons">{lead}</ul>' if lead else ''}
{f'<h3 class="sec">Gaps, honestly</h3><ul class="reasons">{gaps}</ul>' if gaps else ''}{cover}
<form method="post" action="/resume/versions" class="card" style="margin-top:16px">{ui.user_csrf_input()}
<input type="hidden" name="job_id" value="{int(job_id)}">
<div class="form-field"><label for="v-name">Save a tailored copy</label><p class="hint">Adds the summary{' and tailored bullets' if rw else ''} to a copy. Your main resume doesn't change.</p>
<input id="v-name" name="name" maxlength="80" value="{esc(('For ' + title)[:80])}"></div>
<details style="margin:-4px 0 14px"><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the copy before saving</summary>
<textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">
{esc(version_text)}</textarea></details>
<button class="b" type="submit">Save version</button></form>"""


def _versioned(resume: str, summary: str, rewrites: list) -> str:
    text = resume
    for r in rewrites:
        if r["original"] in text:
            text = text.replace(r["original"], r["tailored"].replace("\n", " "), 1)
    lines = text.splitlines()
    insert_at = next((i for i, ln in enumerate(lines) if resume_engine._heading(ln)), min(3, len(lines)))
    return "\n".join(lines[:insert_at] + ["SUMMARY", summary, ""] + lines[insert_at:])


@router.post("/resume/tailor", response_class=HTMLResponse)
def tailor_route(request: Request, job_id: str = Form(""), title: str = Form(""), description: str = Form(""),
                 mode: str = Form("builtin"), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "tailoring requests")
    with store.db() as conn:
        p = _profile(conn, user)
        if not web.csrf_ok(request, csrf) or not p.get("resume_text"):
            return RedirectResponse("/resume?tab=tailor", status_code=303)
        jid = int(job_id) if job_id.isdigit() else 0
        if jid:
            j = store.row(conn, "SELECT * FROM jobs WHERE id = ? AND review_status = 'approved'", (jid,))
            if not j:
                return _studio(conn, user, "tailor", extra=ui.banner("warning", "That listing isn't available anymore."), status=404)
            title, description = j["title"], j["description"]
        else:
            title = security._CONTROL_CHARS_RE.sub("", title).strip()[:200]
            description = security._CONTROL_CHARS_RE.sub("", description).strip()[:8000]
            if len(description) < 60:
                return _studio(conn, user, "tailor", extra=ui.banner("warning", "Pick a listing, or paste a job description (at least a few sentences)."), status=400)
        t = resume_engine.tailor(p["resume_text"], title, description, p)
        use_ai = mode == "ai" and _take_ai(conn, user)
    o = ai_tailor(p["resume_text"], title, description, p) if use_ai else None
    rewrites = _grounded((o or {}).get("rewrites", []), p["resume_text"])
    version_text = _versioned(p["resume_text"], (o or {}).get("summary") or t["summary"], rewrites)
    note = ui.banner("info", "The AI tailor couldn't run just now, so this is the built-in comparison.") if mode == "ai" and not o else ""
    with store.db() as conn:
        return _studio(conn, user, "tailor", extra=note + _tailor_html(t, o, p["resume_text"], title, jid, version_text))


@router.post("/resume/versions")
def save_version(request: Request, name: str = Form(""), body: str = Form(""), job_id: int = Form(0), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf) or not (80 <= len(body) <= resume_engine.MAX_TEXT + 2000):
        return RedirectResponse("/resume?tab=versions", status_code=303)
    name = re.sub(r"\s+", " ", security._CONTROL_CHARS_RE.sub("", name)).strip()[:80] or "Tailored version"
    with store.db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM resume_versions WHERE user_id = ?", (user["id"],)).fetchone()[0]
        if n >= MAX_VERSIONS:
            conn.execute("DELETE FROM resume_versions WHERE id = (SELECT id FROM resume_versions WHERE user_id = ? ORDER BY created_at LIMIT 1)", (user["id"],))
        conn.execute("INSERT INTO resume_versions (user_id, name, body, job_id, created_at) VALUES (?,?,?,?,?)",
                     (user["id"], name, resume_engine.clean(body), job_id or None, time.time()))
    return RedirectResponse("/resume?tab=versions", status_code=303)


def _version(conn, user, vid: int) -> dict | None:
    return store.row(conn, "SELECT * FROM resume_versions WHERE id = ? AND user_id = ?", (vid, user["id"]))


@router.post("/resume/versions/{vid}/use")
def use_version(vid: int, request: Request, csrf: str = Form("")):
    user = web.require_user(request, "student")
    with store.db() as conn:
        v = _version(conn, user, vid)
        if v and web.csrf_ok(request, csrf):
            profiles.save_student(conn, user["id"], resume_text=v["body"], resume_name=v["name"], resume_updated=time.time())
    return RedirectResponse("/resume?tab=review", status_code=303)


@router.post("/resume/versions/{vid}/delete")
def delete_version(vid: int, request: Request, csrf: str = Form("")):
    user = web.require_user(request, "student")
    with store.db() as conn:
        if web.csrf_ok(request, csrf):
            conn.execute("DELETE FROM resume_versions WHERE id = ? AND user_id = ?", (vid, user["id"]))
    return RedirectResponse("/resume?tab=versions", status_code=303)


def _download(text: str, name: str, docx: bool) -> Response:
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip().replace(" ", "_")[:60] or "resume"
    if docx:
        return Response(resume_engine.to_docx(text), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.docx"', "Cache-Control": "no-store"})
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.txt"', "Cache-Control": "no-store"})


@router.get("/resume/download.{ext}")
def download(ext: str, request: Request):
    user = web.require_user(request, "student")
    if ext not in ("docx", "txt"):
        return RedirectResponse("/resume", status_code=303)
    with store.db() as conn:
        p = _profile(conn, user)
    if not p.get("resume_text"):
        return RedirectResponse("/resume", status_code=303)
    return _download(p["resume_text"], (p.get("display_name") or "resume") + " resume", ext == "docx")


@router.get("/resume/versions/{vid}.docx")
def download_version(vid: int, request: Request):
    user = web.require_user(request, "student")
    with store.db() as conn:
        v = _version(conn, user, vid)
    if not v:
        return web.page('<p class="empty" style="margin:40px 0">That version isn\'t available.</p>', "Resume studio", active="/resume", status=404)
    return _download(v["body"], v["name"], True)
