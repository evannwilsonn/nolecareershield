"""
Resume studio: review, edit and tailor a resume.

  * Review  - a 0-100 score in six categories, specific findings, and a suggested rewrite for
              every weak bullet. "AI review" adds a written critique and rewrites from Claude.
  * Edit    - the resume text, bullet-by-bullet improvement, download as .docx or .txt.
  * Tailor  - pick a listing from the board (or paste a job description): which of the job's listed
              qualifications the resume covers, edits to accept or dismiss, which bullets to lead with,
              and a tailored summary. "AI tailor" rewrites bullets toward the job. Save it as a version.
  * Optimize - the front door (layout like Handshake's resume optimizer): pick a saved resume or upload
              one, get an ATS readiness score in four sections, and every suggestion as a card the student
              accepts or dismisses. Nothing is applied without a click ("You approve every change").

  * New resume - /job/{id}/tailor (a full resume built for one listing, with match before -> after, every change
              with Keep/Undo, gaps as advice, PDF/Word/.txt downloads, save as version, open in editor),
              /job/{id}/standout (job-specific tips + a cover note), /job/{id}/tailor?mode=note (a note to the
              poster, sent through Messages once the student applied) and /resume/optimized (step 3 of the studio).

Honesty rule for every suggestion: rephrase what the student wrote, never add experience.
Unknown numbers stay as [placeholders]; missing skills come with "only add this if true".
"""

from __future__ import annotations

import json
import re
import time

from fastapi import Depends, APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import ai
import fit
import matching
import profile_page
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
    tabs = [("optimize", "Optimize"), ("review", "Score details"), ("edit", "Edit"), ("tailor", "Tailor to a job"), ("versions", "Versions")]
    return '<div class="seg rs-tabs" role="tablist">' + "".join(
        f'<a href="/resume{"" if k == "optimize" else "?tab=" + k}"{" class=on aria-current=page" if k == active else ""}>{v}</a>' for k, v in tabs) + "</div>"


def _upload_card(first: bool) -> str:
    title = "Add your resume" if first else "Replace your resume"
    return f"""<div class="card"><h3 class="sec" style="margin-top:0">{title}</h3>
<form method="post" action="/resume/upload" enctype="multipart/form-data">{ui.user_csrf_input()}
<div class="form-field"><label for="r-file">Upload a file</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. We keep the text only.</p>
<input id="r-file" type="file" name="resume" accept=".pdf,.docx,.txt"></div>
<div class="form-field"><label for="r-paste">Or paste it</label><textarea id="r-paste" name="paste" maxlength="20000" placeholder="Paste your resume text"></textarea></div>
<button class="submit-btn" type="submit">{"Review my resume" if first else "Replace"}</button></form></div>"""


# ---------- optimizer: landing, sources, report ----------

def _sources(conn, user, p: dict) -> list[dict]:
    """Every resume the student can optimize: the main one first, then saved tailored copies."""
    out = []
    if p.get("resume_text"):
        out.append({"key": "main", "name": p.get("resume_name") or "My resume", "kind": "Main resume", "at": p.get("resume_updated"), "text": p["resume_text"]})
    for v in store.rows(conn, "SELECT id, name, body, created_at FROM resume_versions WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)):
        out.append({"key": f"v{int(v['id'])}", "name": v["name"], "kind": "Tailored copy", "at": v["created_at"], "text": v["body"]})
    return out


def _upload_form(button: str) -> str:
    return f"""<form method="post" action="/resume/upload" enctype="multipart/form-data">{ui.user_csrf_input()}
<div class="form-field"><label for="r-file">Upload a file</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. We keep the text only.</p>
<input id="r-file" type="file" name="resume" accept=".pdf,.docx,.txt"></div>
<div class="form-field"><label for="r-paste">Or paste it</label><textarea id="r-paste" name="paste" maxlength="20000" placeholder="Paste your resume text"></textarea></div>
<button class="b" type="submit">{button}</button></form>"""


def _check_list(items: list[str]) -> str:
    return '<ul class="rs-checks">' + "".join(f'<li><span class="tick">{ui.icon("check", 14)}</span><span>{i}</span></li>' for i in items) + "</ul>"


def _landing(conn, user, p: dict, extra: str = "", status: int = 200) -> HTMLResponse:
    srcs = _sources(conn, user, p)
    if srcs:
        opts = "".join(f'<option value="{esc(x["key"])}">{esc(x["name"])} ({esc(x["kind"].lower())})</option>' for x in srcs)
        first = srcs[0]
        card = f"""<h2>Add your resume</h2><p class="sub">Select a saved resume or upload a new one.</p>
<form method="get" action="/resume/optimize"><label class="hp" for="rs-src">Saved resume</label><select id="rs-src" name="src">{opts}</select>
<p class="rs-pickmeta">{esc(first['name'])}{" · updated " + esc(web.ago(first['at'])) if first.get('at') else ""}</p>
<button class="b rs-go" type="submit">Optimize my resume</button></form>
<div class="or"><span>or</span></div>
<details class="rs-up"><summary>{ui.icon("plus", 16)} Upload resume</summary><div class="inner">{_upload_form("Upload and optimize")}</div></details>"""
    else:
        card = f"""<h2>Add your resume</h2><p class="sub">Upload a file or paste it, and we'll check it for ATS readiness.</p>{_upload_form("Optimize my resume")}"""
    ai_line = ("Optional AI features use Claude (Anthropic) and send your resume text only when you press an AI button."
               if ai.enabled() else "Runs on the built-in reviewer. Your resume text stays on this site.")
    fine = f'<p class="rs-fine">{ai_line} Review every suggestion so it accurately reflects your own experience.</p>'
    tools = f"""<div class="rs-tools">
<a class="card rs-tool" href="/resume?tab=tailor">{ui.icon("jobs", 20)}<b>Tailor to a job</b><span>Pick a listing and get a new resume made for it, ready to download.</span></a>
<a class="card rs-tool" href="/resume/optimize?src=main#rs-stand">{ui.icon("spark", 20)}<b>Help me stand out</b><span>A few tips drawn from what your resume already says.</span></a>
<a class="card rs-tool" href="/resume?tab=edit">{ui.icon("file", 20)}<b>Edit and versions</b><span>Edit the text, download a copy, or reopen a saved version.</span></a></div>"""
    body = f"""{_tabs("optimize") if srcs else ""}{extra}{_steps(1)}<section class="rs-start"><div>
<h1 class="rs-h1">Land more interviews with an ATS-ready resume</h1>
<p class="rs-lede">Most employers screen resumes with software first. Choose a resume, we scan it, and you review every change before you download the new one.</p>
{_check_list(["Scored on formatting, keywords, impact and contact details", "<b>You approve every change.</b> Nothing is applied until you click Accept", "Suggestions rephrase what you wrote. They never make things up"])}</div>
<div class="card rs-add">{card}{fine}</div></section>{tools if srcs else ""}"""
    return web.page(body, "Resume studio", active="/resume", js=True, status=status)


def _steps(n: int, src: str = "main") -> str:
    """The studio's three steps across the top: 1 Choose resume, 2 Scan, 3 Review changes."""
    names = [("Choose resume", "/resume"), ("Scan", f"/resume/optimize?src={src}"), ("Review changes", f"/resume/optimized?src={src}")]
    out = ""
    for i, (t, h) in enumerate(names, 1):
        inner = f'<span class="n">{ui.icon("check", 14) if i < n else i}</span><span class="t">{t}</span>'
        link = n > 1 and i != n
        out += (f'<li class="{"on" if i == n else "done" if i < n else ""}"{" aria-current=step" if i == n else ""}>'
                + (f'<a href="{esc(h)}">{inner}</a>' if link else inner) + "</li>")
    return f'<ol class="rs-steps" aria-label="Resume optimizer steps">{out}</ol>'


def _href(path: str, params: dict, frag: str = "") -> str:
    q = "&amp;".join(f"{k}={esc(str(v))}" for k, v in params.items() if v not in ("", None))
    return f"{path}?{q}{frag}"


def _sugg_card(sg: dict, ctx: str, dismiss_href: str | None, can_accept: bool = True) -> str:
    sev = {"bad": ("bad", "Fix"), "warn": ("warn", "Improve"), "info": ("info", "Tip")}[sg.get("severity", "info")]
    title = f'<h4><span class="pill {sev[0]}">{sev[1]}</span> {esc(sg["title"])}</h4>'
    why = f'<div class="why">{esc(sg["detail"])}</div>' if sg.get("detail") and sg["kind"] != "skills" else ""
    diff, accept = "", ""
    if sg["kind"] == "rewrite":
        diff = f'<div class="rs-diff"><div class="was"><span class="lbl">Now</span>{esc(sg["old"])}</div><div class="now"><span class="lbl">Suggested</span>{esc(sg["new"])}</div></div>'
    elif sg["kind"] == "skills":
        diff = f'<div class="rs-diff"><div class="now"><span class="lbl">Adds to your Skills</span>{esc(sg["new"])}</div></div>'
    elif sg["kind"] == "summary":
        diff = f'<div class="rs-diff"><div class="now"><span class="lbl">Adds a summary</span>{esc(sg["new"])}</div></div>'
    if sg["kind"] in ("rewrite", "skills", "summary") and can_accept:
        accept = (f'<form method="post" action="/resume/accept">{ui.user_csrf_input()}<input type="hidden" name="ctx" value="{esc(ctx)}">'
                  f'<input type="hidden" name="kind" value="{esc(sg["kind"])}"><input type="hidden" name="old" value="{esc(sg.get("old", ""))}">'
                  f'<input type="hidden" name="new" value="{esc(sg.get("new", ""))}"><button class="b sm" type="submit">Accept</button></form>')
    note = ""
    if sg["kind"] == "rewrite":
        note = '<span class="small">Fill in any [placeholder] after.</span>'
    elif sg["kind"] == "tip":
        note = '<a class="small" href="/resume?tab=edit">Edit my resume</a>'
    dis = f'<a class="b sm ghost" href="{dismiss_href}">{"Dismiss" if accept else "Got it"}</a>' if dismiss_href else ""
    return f'<div class="rs-card{" tip" if sg["kind"] == "tip" else ""}">{title}{why}{diff}<div class="rs-actions">{accept}{dis}{note}</div></div>'


def _report_page(conn, user, p: dict, src: str, x: str = "", ok: bool = False) -> HTMLResponse:
    srcs = _sources(conn, user, p)
    cur = next((c for c in srcs if c["key"] == src), None)
    if not cur:
        return _landing(conn, user, p, extra=ui.banner("info", "That resume isn't available. Pick another."), status=404)
    rp = resume_engine.report(cur["text"], p.get("skills"))
    dismissed = set(re.findall(r"s\d{1,3}", x or ""))
    base = {"src": cur["key"]}
    names = {k: n for k, n, _ in resume_engine.REPORT_SECTIONS}
    by = {k: [] for k, _, _ in resume_engine.REPORT_SECTIONS}
    for sg in rp["suggestions"]:
        by[sg["section"]].append(sg)
    open_n = {k: sum(1 for sg in v if sg["id"] not in dismissed) for k, v in by.items()}
    tone = {"ok": " ok", "warn": " warn", "": ""}
    nav = "".join(f'<a href="#rs-{sc["key"]}"><span>{esc(sc["name"])}</span><span class="pc">{sc["percent"]}%</span>'
                  f'<div class="meter{tone[sc["tone"]]}"><i style="width:{sc["percent"]}%"></i></div>'
                  f'<span class="open">{open_n[sc["key"]]} suggestion{"" if open_n[sc["key"]] == 1 else "s"} open</span></a>' for sc in rp["sections"])
    # Pin each suggestion to the resume line it's about (a doc comment in the margin); the rest are overall notes.
    lines = cur["text"].splitlines()
    skills_at = resume_engine.parse(cur["text"])["sections"].get("skills")
    at_line: dict[int, list] = {}
    general: list = []
    for sg in rp["suggestions"]:
        i = next((k for k, ln in enumerate(lines) if sg["old"] and sg["old"] in ln), None) if sg["kind"] == "rewrite" else \
            (skills_at if sg["kind"] == "skills" else None)
        (at_line.setdefault(i, []) if i is not None else general).append(sg)
    anchored: set = set()

    def cards_for(sgs: list, frag: str) -> str:
        out = ""
        for sg in sgs:
            if sg["id"] in dismissed:
                continue
            anchor = ""
            if sg["section"] not in anchored:
                anchored.add(sg["section"])
                anchor = f'<span class="rs-anchor" id="rs-{sg["section"]}"></span>'
            nxt = ",".join(sorted(dismissed | {sg["id"]}))
            card = _sugg_card(sg, cur["key"], _href("/resume/optimize", {**base, "x": nxt}, frag))
            out += anchor + card.replace("<h4>", f'<div class="rs-sect">{esc(names[sg["section"]])}</div><h4>', 1)
        return out
    notes = cards_for(general, "#rs-notes")
    rows, n_notes = "", 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            rows += '<div class="rs-ln sp" aria-hidden="true"></div>'
            continue
        kind = " lh" if resume_engine._heading(s) else " lb" if resume_engine._BULLET.match(ln) else " ln" if i == 0 else ""
        shown = "• " + resume_engine._BULLET.sub("", s) if kind == " lb" else s
        margin = cards_for(at_line.get(i, []), f"#rs-l{i}")
        n_notes += margin.count('class="rs-card')
        rows += (f'<div class="rs-ln{kind}{" hl" if margin else ""}" id="rs-l{i}"><div class="rs-txt">{esc(shown)}</div>'
                 f'<div class="rs-margin">{margin}</div></div>')
    gone = len(dismissed & {sg["id"] for sg in rp["suggestions"]})
    restore = f'<p class="rs-dis">{gone} dismissed. <a href="{_href("/resume/optimize", base, "#rs-doc")}">Show all again</a></p>' if gone else ""
    secs = ((f'<section id="rs-notes"><div class="rs-sech"><h3>Overall</h3></div>{notes}</section>' if notes else "") +
            f'<section class="rs-sheet" id="rs-doc"><div class="rs-sech"><h3>Your resume, line by line</h3><span class="pill info">{n_notes} note{"" if n_notes == 1 else "s"}</span></div>'
            f'<p class="small muted">Highlighted lines have a suggestion beside them. Accept one and the line changes; nothing else does.</p>'
            f'<div class="rs-lines">{rows}</div>{restore}</section>')
    tips = "".join(f'<div class="rs-card tip"><h4>{ui.icon("spark", 15)} {esc(t["title"])}</h4><div class="why">{esc(t["detail"])}</div></div>' for t in resume_engine.stand_out(cur["text"]))
    jobs = store.live_jobs(conn, security.LISTING_TTL_DAYS)
    ranked = matching.rank_jobs(jobs, p, limit=40) if jobs else []
    jopts = "".join(f'<option value="{int(r["job"]["id"])}">{esc(r["job"]["title"])} · {esc(r["job"]["company"])}</option>' for r in ranked)
    tailor = (f'<section id="rs-tailor"><div class="rs-sech"><h3>Tailor to a job</h3></div><div class="card" style="margin-top:10px">'
              f'<p class="small muted" style="margin-bottom:10px">Pick a listing from the approved board. You\'ll get a new resume made for it, with a preview and downloads.</p>'
              f'<form method="get" action="/resume/tailor-go" class="rs-pick"><div><label class="hp" for="rs-job">Job</label>'
              f'<select id="rs-job" name="job"><option value="">Choose a listing...</option>{jopts}</select></div>'
              f'<button class="b" type="submit">Tailor my resume</button></form></div></section>') if ranked else ""
    ai_btn = (f'<form method="post" action="/resume/ai-review" class="navform">{ui.user_csrf_input()}<button class="b ghost" type="submit">{ui.icon("spark", 16)} Get an AI review</button></form>'
              if ai.enabled() and cur["key"] == "main" else "")
    flash = ui.banner("verified", "Applied. Your other suggestions are still here, and the score is updated.") if ok else ""
    st = rp["stats"]
    side = f"""<aside class="rs-side"><div class="card rs-score"><div class="eyebrow">ATS readiness</div>
<div class="ring" style="--p:{rp['percent']}"><b>{rp['percent']}<small>%</small></b></div><h2>{esc(rp['label'])}</h2>
<p>{esc(cur['name'])} · {st['words']} words · {st['bullets']} bullets</p><nav class="rs-nav" aria-label="Report sections">{nav}</nav>
<a class="b rs-next" href="/resume/optimized?src={esc(cur['key'])}">See your optimized resume &rarr;</a></div></aside>"""
    body = f"""{_tabs("optimize")}{_steps(2, cur["key"])}{flash}
<div class="rs-report">{side}<div class="rs-main">
<div class="rs-approve">{ui.icon("shield", 18)}<span><b>You approve every change.</b> Nothing on your resume changes until you press Accept, and you can dismiss anything.</span></div>
{secs}<section id="rs-stand"><div class="rs-sech"><h3>Help me stand out</h3></div><div class="rs-stand">{tips or '<div class="rs-clear">Nothing to add right now.</div>'}</div></section>
{tailor}<div class="row" style="margin-top:8px"><a class="b" href="/resume/optimized?src={esc(cur['key'])}">See your optimized resume</a>{ai_btn}<a class="b sec" href="/resume?tab=edit">Edit resume</a><a class="b ghost" href="/resume/download.docx">Download .docx</a></div></div></div>"""
    return web.page(body, "Resume studio", active="/resume", js=True)


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
<div><div class="eyebrow">Resume score</div><h2 style="font-family:var(--serif);font-variation-settings:var(--dx);font-weight:500;font-size:24px">{esc(rv['grade'])}</h2>
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


def _studio(conn, user, tab: str = "optimize", extra: str = "", notice: str = "", status: int = 200, job: int = 0, auto: bool = True, x: str = "",
            ok: bool = False, draft: str = "") -> HTMLResponse:
    p = _profile(conn, user)
    head = ui.page_head("Resume studio", "Score it, fix it line by line, and tailor it to any job on the board. Suggestions rephrase what you wrote; they never make things up.",
                        num="Resume")
    note = ui.banner("verified", notice) if notice else ""
    if not p.get("resume_text") or tab == "optimize":
        return _landing(conn, user, p, extra=note + extra, status=status)
    text = p["resume_text"]
    body = head + note + _tabs(tab)
    ai_line = ('<p class="aimode" style="margin:6px 0 0">AI features use Claude (Anthropic). Your resume text is sent only when you press an AI button.</p>'
               if ai.enabled() else '<p class="aimode" style="margin:6px 0 0">Using the built-in reviewer. AI rewrites turn on when the site admin adds an AI key.</p>')
    if tab == "review":
        rv = resume_engine.review(text)
        ai_btn = (f'<form method="post" action="/resume/ai-review" class="navform">{ui.user_csrf_input()}<button class="b" type="submit">{ui.icon("spark", 16)} Get an AI review</button></form>'
                  if ai.enabled() else "")
        body += extra + _review_html(rv) + f'<div class="row" style="margin-top:18px">{ai_btn}<a class="b sec" href="/resume?tab=edit">Edit resume</a></div>{ai_line}'
    elif tab == "edit" and draft:
        body += extra + draft + ai_line
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
        opts = "".join(f'<option value="{int(r["job"]["id"])}"{" selected" if int(r["job"]["id"]) == job else ""}>{esc(r["job"]["title"])} · {esc(r["job"]["company"])} (fit {r.get("fit", {}).get("score", r["score"])})</option>' for r in ranked)
        if job and auto:
            jrow = store.row(conn, f"SELECT * FROM jobs WHERE id = ? AND {store.live_where()}", (job,))
            extra += _tailor_html(conn, user, p, job, jrow["title"], jrow["description"], None, x, ok) if jrow else ui.banner("warning", "That listing isn't available anymore.")
        body += f"""<form method="get" action="/resume/tailor-go" class="card rs-tpick"><div class="form-field"><label for="t-job">A job on the board</label>
<p class="hint">You'll get a new resume made for that listing: a preview, every change listed with Undo, and PDF or Word downloads.</p>
<select id="t-job" name="job"><option value="">Choose a listing...</option>{opts}</select></div>
<button class="b" type="submit">{ui.icon("file", 16)} Tailor my resume</button></form>
<form method="post" action="/resume/tailor" class="card" style="margin-top:14px">{ui.user_csrf_input()}
<div class="or"><span>Or paste a job description</span></div>
<div class="form-field"><label for="t-title">Job title</label><input id="t-title" name="title" maxlength="200" placeholder="Marketing Intern"></div>
<div class="form-field"><label for="t-desc">Job description</label><textarea id="t-desc" name="description" maxlength="8000" placeholder="Paste the posting"></textarea></div>
<div class="row"><button class="b" type="submit" name="mode" value="builtin">Show match details</button>
{f'<button class="b ghost" type="submit" name="mode" value="ai">{ui.icon("spark", 14)} AI tailor</button>' if ai.enabled() else ''}</div></form><div style="margin-top:18px">{extra}</div>{ai_line}"""
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
def studio(request: Request, tab: str = "optimize", job: int = 0, x: str = "", ok: int = 0, undo: str = "", ai: int = 0, src: str = ""):
    user = web.require_user(request, "student")
    tab = tab if tab in ("optimize", "review", "edit", "tailor", "versions") else "optimize"
    if tab == "tailor" and job > 0:              # "Tailor my resume" on a listing lands on that job's new resume
        return RedirectResponse(f"/job/{int(job)}/tailor", status_code=303)
    frm = request.query_params.get("from", "")
    with store.db() as conn:
        draft = ""
        if tab == "edit" and re.fullmatch(r"main|v\d{1,9}|job\d{1,9}", frm or ""):
            draft = _editor_draft(conn, user, _profile(conn, user), frm, _undo(undo), bool(ai))
        return _studio(conn, user, tab, job=job, x=x, ok=bool(ok), draft=draft)


@router.get("/resume/optimize", response_class=HTMLResponse)
def optimize(request: Request, src: str = "main", x: str = "", ok: int = 0):
    user = web.require_user(request, "student")
    with store.db() as conn:
        p = _profile(conn, user)
        if not _sources(conn, user, p):
            return _landing(conn, user, p)
        return _report_page(conn, user, p, src if re.fullmatch(r"main|v\d{1,9}", src) else "main", x, bool(ok))


@router.post("/resume/upload", response_class=HTMLResponse)
def upload(request: Request, form=Depends(web.form_data)):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.upload_limiter, f"u{user['id']}", "resume uploads")
    if not web.csrf_ok(request, form.get("csrf")):
        return RedirectResponse("/resume", status_code=303)
    f = form.get("resume")
    paste = str(form.get("paste") or "").strip()
    try:
        if f is not None and hasattr(f, "read") and getattr(f, "filename", ""):
            data = f.file.read(resume_engine.MAX_UPLOAD + 1)
            text, name = resume_engine.extract_text_safely(f.filename, data), f.filename[:120]
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
            return _studio(conn, user, "optimize", extra=ui.banner("warning", str(e)), status=400)
    with store.db() as conn:
        p = _profile(conn, user)
        fields = dict(resume_text=text, resume_name=name, resume_updated=time.time())
        if not p.get("skills"):
            fields["skills"] = matching.extract_skills(text)[:20]
        profiles.save_student(conn, user["id"], **fields)
        if not store.profile_items(conn, user["id"]):
            profile_page.import_resume(conn, user["id"], text)
    return RedirectResponse("/resume/optimize?src=main", status_code=303)


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


@router.post("/resume/accept")
def accept(request: Request, ctx: str = Form(""), kind: str = Form(""), old: str = Form(""), new: str = Form(""), csrf: str = Form("")):
    """Apply one suggestion the student accepted. Suggestions are only ever applied here, one per click."""
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "saving")
    m = re.fullmatch(r"(main|v(\d{1,9})|job(\d{1,9}))", ctx or "")
    if not m or not web.csrf_ok(request, csrf) or kind not in ("rewrite", "skills", "summary"):
        return RedirectResponse("/resume", status_code=303)
    new = re.sub(r"\s+", " ", security._CONTROL_CHARS_RE.sub("", new or "")).strip()
    with store.db() as conn:
        p = _profile(conn, user)
        vid = int(m.group(2)) if m.group(2) else 0
        jid = int(m.group(3)) if m.group(3) else 0
        if jid:
            j = store.row(conn, f"SELECT * FROM jobs WHERE id = ? AND {store.live_where()}", (jid,))
            if not j or not p.get("resume_text"):
                return RedirectResponse("/resume?tab=tailor", status_code=303)
            text, v = _working(conn, user, p, jid)
            if not v:
                n = conn.execute("SELECT COUNT(*) FROM resume_versions WHERE user_id = ?", (user["id"],)).fetchone()[0]
                if n >= MAX_VERSIONS:
                    conn.execute("DELETE FROM resume_versions WHERE id = (SELECT id FROM resume_versions WHERE user_id = ? ORDER BY created_at LIMIT 1)", (user["id"],))
                cur = conn.execute("INSERT INTO resume_versions (user_id, name, body, job_id, created_at) VALUES (?,?,?,?,?)",
                                   (user["id"], ("For " + j["title"] + " at " + j["company"])[:80], text, jid, time.time()))
                vid = cur.lastrowid
            else:
                vid = int(v["id"])
            back = f"/resume?tab=tailor&job={jid}&ok=1"
        elif vid:
            v = _version(conn, user, vid)
            if not v:
                return RedirectResponse("/resume", status_code=303)
            text, back = v["body"], f"/resume/optimize?src=v{vid}&ok=1"
        else:
            text, back = p.get("resume_text") or "", "/resume/optimize?src=main&ok=1"
        if not text:
            return RedirectResponse("/resume", status_code=303)
        after = text
        if kind == "rewrite" and old in text and 0 < len(new) <= 600:
            after = text.replace(old, new, 1)
        elif kind == "skills":
            after = resume_engine.add_skills(text, p.get("skills") or [])
        elif kind == "summary" and jid and 0 < len(new) <= 600:
            after = resume_engine.set_summary(text, new)
        if after != text:
            after = resume_engine.clean(after)
            if jid or m.group(2):
                conn.execute("UPDATE resume_versions SET body = ? WHERE id = ? AND user_id = ?", (after, vid, user["id"]))
            else:
                profiles.save_student(conn, user["id"], resume_text=after, resume_updated=time.time())
        else:
            back = back.replace("&ok=1", "")
    return RedirectResponse(back, status_code=303)


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
def bullet_api(request: Request, body: bytes = Depends(web.body_bytes)):
    user = web.current_user(request)
    if not user or user["role"] != "student":
        return JSONResponse({"error": "Log in first."}, status_code=401)
    if not web.csrf_ok(request, request.headers.get("x-csrf-token", "")):
        return JSONResponse({"error": "Refresh the page and try again."}, status_code=400)
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    try:
        data = json.loads(body or b"null")
        bullet = str(data.get("bullet", ""))
    except (ValueError, AttributeError):
        return JSONResponse({"error": "Bad request."}, status_code=400)
    if not (3 <= len(bullet.strip()) <= 400):
        return JSONResponse({"error": "Paste one bullet (up to 400 characters)."}, status_code=400)
    with store.db() as conn:
        r = _bullet_result(bullet, user, conn)
    return JSONResponse({**r, "html": _bullet_html(r)})


def _working(conn, user, p: dict, jid: int) -> tuple[str, dict | None]:
    """The text tailoring works on: this job's tailored copy if there is one, otherwise the main resume."""
    if jid:
        v = store.row(conn, "SELECT * FROM resume_versions WHERE user_id = ? AND job_id = ? ORDER BY created_at DESC LIMIT 1", (user["id"], jid))
        if v:
            return v["body"], v
    return p.get("resume_text") or "", None


def _coverage(job: dict, p: dict, text: str) -> dict:
    """Which of the job's listed qualifications the resume text covers (fit.fit_score's checklist, resume evidence only)."""
    prof = dict(p, skills=[], items=[], headline="", bio="", resume_text=text)
    f = fit.fit_score(job, prof)
    counted = [c for c in f["checklist"] if c["status"] in ("met", "missing")]
    met = sum(1 for c in counted if c["status"] == "met")
    pct = f.get("percent")
    if pct is None:
        pct = round(100 * met / len(counted)) if counted else f["score"]
    return {"checklist": f["checklist"], "percent": pct, "met": met, "total": len(counted), "fit": f}


def _tailor_html(conn, user, p: dict, jid: int, title: str, description: str, o: dict | None = None, x: str = "", ok: bool = False) -> str:
    text, wv = _working(conn, user, p, jid)
    job = store.row(conn, "SELECT * FROM jobs WHERE id = ?", (jid,)) if jid else None
    job = job or {"title": title, "description": description}
    t = resume_engine.tailor(text, title, description, p)
    cov = _coverage(job, p, text)
    mark = {"met": "✓", "missing": "!", "unknown": "?"}

    def li(c: dict) -> str:
        ev = f'<span class="ev">{esc(c["evidence"])}</span>' if c.get("evidence") else ""
        return f'<li class="{c["status"]}"><span class="st">{mark[c["status"]]}</span><div>{esc(c["text"])}{ev}</div></li>'
    covered = "".join(li(c) for c in cov["checklist"] if c["status"] == "met")
    notyet = "".join(li(c) for c in cov["checklist"] if c["status"] != "met")
    if cov["total"]:
        headline = f'Your resume covers {cov["met"]} of {cov["total"]} listed qualifications.'
        ring = cov["percent"]
    else:
        headline = "This posting doesn't list specific qualifications, so this uses the skills and keywords in its text."
        ring = t["match"]
    company = f' · <a href="/job/{jid}">{esc(job.get("company", ""))}</a>' if jid and job.get("company") else ""
    working = (f'<p class="rs-note">You\'re working on your tailored copy “{esc(wv["name"])}”. Your main resume isn\'t changed. '
               f'<a href="/resume/versions/{int(wv["id"])}.docx">Download .docx</a></p>') if wv else ""
    head = f"""<div class="card"><div class="rs-job"><div class="ring" style="--p:{ring}"><b>{ring}<small>%</small></b></div>
<div><div class="eyebrow">Match details</div><h2>{esc(title or 'This job')}</h2><p class="small muted">{esc(headline)}{company}</p></div></div>
<div class="rs-cover"><div><h4>Covered by your resume</h4><ul class="checklist">{covered or '<li class="unknown"><span class="st">?</span><div>Nothing listed is covered yet.</div></li>'}</ul></div>
<div><h4>Not shown yet</h4><ul class="checklist">{notyet or '<li class="met"><span class="st">✓</span><div>Every listed qualification is covered.</div></li>'}</ul></div></div>{working}</div>"""

    # Suggested edits, each accepted or dismissed by the student. Accepting edits this job's tailored copy, never the main resume.
    sugg: list[dict] = []
    summary = (o or {}).get("summary") or t["summary"]
    if _norm(summary)[:60] not in _norm(text):
        sugg.append({"kind": "summary", "severity": "info", "title": "Add a summary written for this role", "detail": "", "old": "", "new": summary})
    job_sk = matching.extract_skills(f"{title}\n{description}")
    miss = resume_engine.missing_profile_skills(text, [s for s in (p.get("skills") or []) if s in job_sk])
    if miss:
        sugg.append({"kind": "skills", "severity": "warn", "title": "Add skills this job lists that you already have on your profile",
                     "detail": "", "old": "", "new": ", ".join(miss)})
    for r in _grounded((o or {}).get("rewrites", []), text)[:6]:
        sugg.append({"kind": "rewrite", "severity": "warn", "title": "Reword to mirror the posting", "detail": r.get("why", ""),
                     "old": r["original"], "new": r["tailored"]})
    for b in t["lead_bullets"][:3]:
        sugg.append({"kind": "tip", "severity": "info", "title": "Lead with: " + b["text"][:110], "detail": b["why"], "old": "", "new": ""})
    for i, sg in enumerate(sugg):
        sg["id"] = f"s{i}"
    gone = set(re.findall(r"s\d{1,3}", x or ""))
    cards = ""
    for sg in sugg:
        if sg["id"] in gone:
            continue
        dis = _href("/resume", {"tab": "tailor", "job": jid, "x": ",".join(sorted(gone | {sg["id"]}))}) if jid else None
        cards += _sugg_card(sg, f"job{jid}", dis, can_accept=bool(jid))
    if not cards:
        cards = '<div class="rs-clear">No edits to suggest right now.</div>'
    restore = f'<p class="rs-dis">{len(gone & {s["id"] for s in sugg})} dismissed. <a href="{_href("/resume", {"tab": "tailor", "job": jid})}">Show all again</a></p>' if jid and gone & {s["id"] for s in sugg} else ""
    keep = "" if jid else '<p class="rs-note">To accept edits, choose a listing from the board. For a pasted description, save a tailored copy below and edit it there.</p>'
    edits = f'<section style="margin-top:22px"><div class="rs-sech"><h3>Suggested edits</h3></div><div class="rs-approve" style="margin-top:8px">{ui.icon("shield", 18)}<span><b>You approve every change.</b> Nothing is applied until you press Accept.</span></div>{cards}{restore}{keep}</section>'

    pills = lambda xs, cls: "".join(f'<span class="pill {cls}">{esc(v)}</span>' for v in xs) or '<span class="faint small">None</span>'
    gaps = "".join(f'<li><b>{esc(g["skill"])}</b><span class="ev">{esc(g["advice"])}</span></li>' for g in (o or {}).get("gaps", t["gaps"])[:6])
    detail = f"""<details class="card" style="margin-top:16px"><summary class="small" style="cursor:pointer;font-weight:600;color:var(--accent-ink)">Skills and keywords in this posting</summary>
<div class="split" style="margin-top:12px"><div><b class="small">Skills you show</b><div class="kw" style="margin-top:6px">{pills(t['skills_present'], 'ok')}</div></div>
<div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">{pills(t['skills_missing'], 'warn')}</div></div></div>
<div style="margin-top:12px"><b class="small">Keywords to use where true</b><div class="kw" style="margin-top:6px">{pills(t['keywords_missing'], '')}</div></div></details>"""
    cover = (f'<h3 class="sec">A short note to send with it</h3><div class="card"><p style="white-space:pre-wrap">{esc(o["cover_note"])}</p>'
             f'<button class="b sm sec" type="button" data-copy="{esc(o["cover_note"])}" style="margin-top:8px">Copy</button></div>') if o and o.get("cover_note") else ""
    ai_btn = (f'<form method="post" action="/resume/tailor" class="navform">{ui.user_csrf_input()}<input type="hidden" name="job_id" value="{int(jid)}">'
              f'<input type="hidden" name="title" value="{esc(title)}"><button class="b ghost" type="submit" name="mode" value="ai">{ui.icon("spark", 14)} AI tailor</button></form>') \
        if ai.enabled() and jid else ""
    save = ""
    if not wv:
        rewrites = _grounded((o or {}).get("rewrites", []), text)
        version_text = _versioned(text, summary, rewrites)
        save = f"""<form method="post" action="/resume/versions" class="card" style="margin-top:16px">{ui.user_csrf_input()}
<input type="hidden" name="job_id" value="{int(jid)}">
<div class="form-field"><label for="v-name">Save a tailored copy</label><p class="hint">Adds the summary{' and tailored bullets' if rewrites else ''} to a copy. Your main resume doesn't change.</p>
<input id="v-name" name="name" maxlength="80" value="{esc(('For ' + title)[:80])}"></div>
<details style="margin:-4px 0 14px"><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the copy before saving</summary>
<textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">
{esc(version_text)}</textarea></details>
<button class="b" type="submit">Save version</button></form>"""
    flash = ui.banner("verified", "Applied to your tailored copy. Your main resume is unchanged.") if ok else ""
    return f'{flash}{head}{edits}{detail}{cover}<div class="row" style="margin-top:14px">{ai_btn}</div>{save}'


def _versioned(resume: str, summary: str, rewrites: list) -> str:
    text = resume
    for r in rewrites:
        if r["original"] in text:
            text = text.replace(r["original"], r["tailored"].replace("\n", " "), 1)
    return resume_engine.set_summary(text, summary)


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
            j = store.row(conn, f"SELECT * FROM jobs WHERE id = ? AND {store.live_where()}", (jid,))
            if not j:
                return _studio(conn, user, "tailor", extra=ui.banner("warning", "That listing isn't available anymore."), status=404)
            title, description = j["title"], j["description"]
        else:
            title = security._CONTROL_CHARS_RE.sub("", title).strip()[:200]
            description = security._CONTROL_CHARS_RE.sub("", description).strip()[:8000]
            if len(description) < 60:
                return _studio(conn, user, "tailor", extra=ui.banner("warning", "Pick a listing, or paste a job description (at least a few sentences)."), status=400)
        text, _ = _working(conn, user, p, jid)
        use_ai = mode == "ai" and _take_ai(conn, user)
    o = ai_tailor(text, title, description, p) if use_ai else None
    note = ui.banner("info", "The AI tailor couldn't run just now, so this is the built-in comparison.") if mode == "ai" and not o else ""
    with store.db() as conn:
        return _studio(conn, user, "tailor", job=jid, extra=note + _tailor_html(conn, user, p, jid, title, description, o), auto=False)


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


# ---------- the new resume: tailored to a job, or optimized in general ----------
#
# Both pages show the full new resume (resume_engine.build_resume) with a panel of every change, each with
# Keep / Undo links. The choice travels in the URL (?undo=c2,c5), so the preview, the downloads, "Save as
# version" and "Open in editor" all use the same resume. No JavaScript needed; Ctrl+P prints just the page.

_AI_CACHE: dict = {}          # (user, key, text hash) -> checked AI wording, so previews and downloads match
_AI_CACHE_MAX = 300


def _undo(s: str) -> list[str]:
    return sorted(set(re.findall(r"c\d{1,3}", s or "")), key=lambda c: int(c[1:]))


def _q(params: dict) -> str:
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in params.items() if v not in ("", None, 0)})
    return "?" + q if q else ""


def _live_job(conn, jid: int) -> dict | None:
    return store.row(conn, f"SELECT * FROM jobs WHERE id = ? AND {store.live_where()}", (jid,))


def _me(conn, user, p: dict) -> dict:
    """The profile plus the account email and profile sections, as build_resume reads it."""
    r = conn.execute("SELECT email FROM users WHERE id = ?", (user["id"],)).fetchone()
    return dict(p, email=r[0] if r else "", items=p.get("items") or store.profile_items(conn, user["id"]))


def _ai_key(user, key: str, text: str) -> tuple:
    import hashlib
    return (int(user["id"]), key, hashlib.sha256(text.encode()).hexdigest()[:24])


def ai_polish(profile: dict, text: str, job: dict | None) -> dict | None:
    """Ask Claude to reword bullets and the summary. Every line is checked with resume_engine.fact_safe:
    anything with a new number, skill, name, link or placeholder is thrown away."""
    doc = resume_engine._doc_parse(text)
    bullets = [b["text"] for s in doc["sections"] for e in s["entries"] for b in e["bullets"]][:24]
    if not bullets:
        return None
    schema = {"type": "object", "properties": {
        "summary": {"type": "string", "description": "Two sentences, true to the resume"},
        "bullets": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
            "original": {"type": "string", "description": "The bullet exactly as given"}, "improved": {"type": "string"},
            "why": {"type": "string"}}, "required": ["original", "improved", "why"]}}},
        "required": ["summary", "bullets"]}
    system = ("You polish the wording of an FSU student's resume" + (" for one job posting" if job else "") + ". Reword bullets to lead with a strong "
              "verb and, where true, mirror the posting's language. Keep every fact exactly: never add numbers, tools, employers, places, "
              "results or skills that aren't in that bullet. Don't use placeholders. Under 30 words each. Quote originals exactly.")
    content = ai.tag("resume", "\n".join("- " + b for b in bullets), 8000)
    if job:
        content += "\n" + ai.tag("job", f"{job.get('title', '')}\n\n{job.get('description', '')}", 5000)
    about = json.dumps({k: profile.get(k) for k in ("major", "grad_term", "skills") if profile.get(k)})
    content += f"\nStudent profile: {ai.tag('profile', about, 800)}"
    try:
        o = ai.structured(system, content, "resume_wording", schema, max_tokens=1800)
    except ai.AIUnavailable:
        return None
    skills = [str(s) for s in profile.get("skills") or []]
    out: dict = {"bullets": {}}
    for r in o.get("bullets") or []:
        if isinstance(r, dict) and r.get("original") in bullets and resume_engine.fact_safe(r.get("improved"), r["original"], skills):
            out["bullets"][r["original"]] = {"text": str(r["improved"]).strip(), "why": str(r.get("why") or "")[:200]}
    s = str(o.get("summary") or "").strip()
    facts = text + " " + " ".join(str(profile.get(k) or "") for k in ("major", "grad_term")) + " Florida State University FSU"
    if resume_engine.fact_safe(s, facts, skills):
        out["summary"] = s
    return out if out["bullets"] or out.get("summary") else None


def _build(conn, user, p: dict, text: str, job: dict | None, undo: list, ai_key: str = "") -> dict:
    me = _me(conn, user, p)
    edits = _AI_CACHE.get(_ai_key(user, ai_key, text)) if ai_key else None
    return resume_engine.build_resume(me, text, job, undo=undo, ai_edits=edits)


def _no_resume_page(title: str) -> HTMLResponse:
    body = (ui.page_head(title) + f'<div class="card rs-need"><h2>Add your resume first</h2><p class="muted">We build the new resume from yours, '
            f'so upload it once (PDF, Word or text). It takes a few seconds, and you approve every change after.</p>{_upload_form("Upload my resume")}</div>')
    return web.page(body, title, active="/resume", js=True)


def _changes_html(doc: dict, href) -> str:
    kinds = {"summary": "Summary", "profile": "From your profile", "order": "Order", "trim": "Left out", "rewrite": "Wording", "skills": "Skills"}
    items = ""
    for c in doc["changes"]:
        diff = ""
        if c["before"] and c["after"] and c["kind"] in ("rewrite", "summary"):
            diff = f'<div class="rs-diff"><div class="was"><span class="lbl">Was</span>{esc(c["before"])}</div><div class="now"><span class="lbl">Now</span>{esc(c["after"])}</div></div>'
        elif c["kind"] in ("summary", "skills", "profile"):
            diff = f'<div class="rs-diff"><div class="now"><span class="lbl">Adds</span>{esc(c["after"])}</div></div>'
        elif c["kind"] == "trim":
            diff = f'<div class="rs-diff"><div class="was"><span class="lbl">Leaves out</span>{esc(c["before"])}</div></div>'
        elif c["kind"] == "order":
            diff = f'<div class="rs-diff"><div class="now"><span class="lbl">Now first</span>{esc(c["after"])}</div></div>'
        if c["on"]:
            acts = (f'<span class="rs-kept">{ui.icon("check", 14)} Kept</span>'
                    f'<a class="b sm ghost" href="{href(add=c["id"])}#ch-{c["id"]}">Undo</a>')
        else:
            acts = (f'<span class="rs-kept off">Undone</span>'
                    f'<a class="b sm sec" href="{href(drop=c["id"])}#ch-{c["id"]}">Keep</a>')
        items += (f'<li class="rs-ch{"" if c["on"] else " off"}" id="ch-{c["id"]}"><div class="rs-cht"><span class="pill info">{kinds.get(c["kind"], "Edit")}</span>'
                  f'<b>{esc(c["title"])}</b></div><p class="why">{esc(c["detail"])}</p>{diff}<div class="rs-actions">{acts}</div></li>')
    n_on = sum(1 for c in doc["changes"] if c["on"])
    head = f'<h3>Changes <small>{n_on} of {len(doc["changes"])} kept</small></h3>'
    if not items:
        return f'<section class="card rs-changes">{head}<p class="muted small">Your resume already reads well; nothing needed changing.</p></section>'
    return f'<section class="card rs-changes">{head}<ol>{items}</ol></section>'


def _gen_page(doc: dict, *, path: str, base: dict, undo: list, heading: str, sub: str, top: str, score: str, extra: str,
              save_action: str, edit_href: str, flash: str = "", title: str = "Resume studio") -> HTMLResponse:
    cur = set(undo)

    def href(add: str = "", drop: str = "") -> str:
        u = sorted((cur | {add}) - {drop, ""}, key=lambda c: int(c[1:]))
        return esc(path + _q({**base, "undo": ",".join(u)}))
    q = {**base, "undo": ",".join(undo)}
    dl = lambda ext: esc(path + "." + ext + _q(q))      # noqa: E731
    hidden = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(str(v))}">' for k, v in q.items() if v)
    actions = f"""<section class="card rs-dl"><h3>Download</h3><div class="rs-dlrow">
<a class="b" href="{dl('pdf')}" download>{ui.icon("file", 16)} PDF</a><a class="b sec" href="{dl('docx')}" download>Word</a><a class="b ghost" href="{dl('txt')}" download>.txt</a></div>
<form method="post" action="{esc(save_action)}" class="rs-save">{ui.user_csrf_input()}{hidden}<button class="b sec" type="submit">Save as version</button></form>
<a class="b ghost" href="{esc(edit_href)}">Open in editor</a>
<p class="small faint">Tip: printing this page (Ctrl+P) prints just the resume.</p></section>"""
    body = f"""{top}{flash}<div class="rs-gen-head"><div><h1 class="rs-t1">{heading}</h1><p class="muted">{sub}</p></div></div>
<div class="rs-gen"><div class="rs-paper">{resume_engine.doc_html(doc)}<p class="rs-legend"><span class="rs-chg">Highlighted</span> lines were reworded. Every fact is yours; check each line before you send it.</p></div>
<aside class="rs-panel">{score}{actions}{_changes_html(doc, href)}{extra}</aside></div>"""
    return web.page(body, title, active="/resume", js=True)


def _job_tabs(jid: int, active: str) -> str:
    tabs = [("tailor", f"/job/{jid}/tailor", "Tailor my resume"), ("standout", f"/job/{jid}/standout", "Help me stand out"),
            ("note", f"/job/{jid}/tailor?mode=note", "Message the poster")]
    return (f'<a class="rs-back" href="/jobs?job={jid}">&larr; Back to the listing</a><nav class="seg rs-jtabs" aria-label="Resume help for this job">'
            + "".join(f'<a href="{h}"{" class=on aria-current=page" if k == active else ""}>{v}</a>' for k, h, v in tabs) + "</nav>")


def _match_box(doc: dict) -> str:
    m = doc["match"] or {"before": 0, "after": 0, "met_before": 0, "met_after": 0, "total": 0}
    up = m["after"] - m["before"]
    quals = (f'<p class="small muted">Covers {m["met_before"]} → {m["met_after"]} of {m["total"]} listed qualifications.</p>' if m["total"] else
             '<p class="small muted">This posting doesn\'t list qualifications, so this uses its skills and keywords.</p>')
    return f"""<section class="card rs-match"><div class="eyebrow">Match with this job</div>
<div class="rs-mm"><div><span class="lbl">Your resume</span><b>{m['before']}%</b></div><span class="arr" aria-hidden="true">→</span><div class="new"><span class="lbl">Tailored</span><b>{m['after']}%</b></div></div>
<div class="meter"><i style="width:{m['before']}%"></i></div><div class="meter ok"><i style="width:{m['after']}%"></i></div>
{quals}<p class="small faint">{"+" + str(up) + " points, only from what you already have." if up > 0 else "Scored on resume text only."}</p></section>"""


def _gaps_box(doc: dict) -> str:
    if not doc["gaps"]:
        return ""
    req = ' <span class="pill warn">Required</span>'
    lis = "".join(f'<li><b>{esc(g["text"])}</b>{req if g["must"] else ""}<span class="ev">{esc(g["advice"])}</span></li>' for g in doc["gaps"])
    return (f'<section class="card rs-gaps"><h3>Not on your resume yet</h3><p class="small muted">We never add these for you. '
            f'They\'re here so you can decide what\'s true.</p><ul class="reasons">{lis}</ul></section>')


def _ai_form(action: str, hidden: dict) -> str:
    if not ai.enabled():
        return ""
    h = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(str(v))}">' for k, v in hidden.items() if v)
    return (f'<form method="post" action="{esc(action)}" class="card rs-aibox">{ui.user_csrf_input()}{h}<p class="small muted">Optional: Claude can polish the wording. '
            f'Anything that adds a number, skill or name that isn\'t yours is thrown away.</p><button class="b ghost sm" type="submit">{ui.icon("spark", 14)} Improve wording with AI</button></form>')


def _tailor_page(conn, user, p: dict, j: dict, undo: list, ai_on: bool, saved: bool = False, ai_note: str = "") -> HTMLResponse:
    jid = int(j["id"])
    doc = _build(conn, user, p, p["resume_text"], j, undo, f"job{jid}" if ai_on else "")
    base = {"ai": 1} if ai_on else {}
    flash = ui.banner("verified", f"Saved as “For {j['title']} at {j['company']}”. It's under Versions.") if saved else ""
    flash += ui.banner("info", ai_note) if ai_note else ""
    q = {**base, "undo": ",".join(undo)}
    return _gen_page(doc, path=f"/job/{jid}/tailor", base=base, undo=undo, top=_job_tabs(jid, "tailor"),
                     heading=f"Your resume for {esc(j['title'])}", sub=f"{esc(j['company'])} · built from your resume and profile, aimed at this posting. Nothing is made up.",
                     score=_match_box(doc), extra=_gaps_box(doc) + _ai_form(f"/job/{jid}/tailor/ai", q),
                     save_action=f"/job/{jid}/tailor/save", edit_href=f"/resume?tab=edit&from=job{jid}" + ("&" + _q(q)[1:] if _q(q) else ""),
                     flash=flash, title="Tailor my resume")


@router.get("/job/{jid}/tailor", response_class=HTMLResponse)
def tailor_job(jid: int, request: Request, undo: str = "", mode: str = "", ai: int = 0, saved: int = 0):
    user = web.require_user(request, "student")
    with store.db() as conn:
        j = _live_job(conn, jid)
        if not j:
            return web.page(ui.page_head("Tailor my resume") + ui.banner("info", "That listing isn't available anymore.") +
                            '<a class="b sec" href="/jobs">Browse jobs</a>', "Tailor my resume", active="/resume", status=404)
        p = _profile(conn, user)
        if not p.get("resume_text"):
            return _no_resume_page("Tailor my resume")
        if mode == "note":
            return _note_page(conn, user, p, j)
        return _tailor_page(conn, user, p, j, _undo(undo), bool(ai), bool(saved))


@router.get("/job/{jid}/tailor.{ext}")
def tailor_download(jid: int, ext: str, request: Request, undo: str = "", ai: int = 0):
    user = web.require_user(request, "student")
    if ext not in ("pdf", "docx", "txt"):
        return RedirectResponse(f"/job/{jid}/tailor", status_code=303)
    with store.db() as conn:
        j = _live_job(conn, jid)
        p = _profile(conn, user)
        if not j or not p.get("resume_text"):
            return RedirectResponse(f"/job/{jid}/tailor", status_code=303)
        doc = _build(conn, user, p, p["resume_text"], j, _undo(undo), f"job{jid}" if ai else "")
    return _send(doc, f"{doc['name']} resume {j['company']}", ext)


def _send(doc: dict, name: str, ext: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip().replace(" ", "_")[:70] or "resume"
    data, kind = {"pdf": (resume_engine.to_pdf, "application/pdf"),
                  "docx": (resume_engine.to_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                  "txt": (lambda d: d["text"].encode(), "text/plain; charset=utf-8")}[ext]
    return Response(data(doc), media_type=kind, headers={"Content-Disposition": f'attachment; filename="{safe}.{ext}"', "Cache-Control": "no-store"})


def _save_version(conn, user, name: str, body: str, job_id: int | None) -> None:
    n = conn.execute("SELECT COUNT(*) FROM resume_versions WHERE user_id = ?", (user["id"],)).fetchone()[0]
    if n >= MAX_VERSIONS:
        conn.execute("DELETE FROM resume_versions WHERE id = (SELECT id FROM resume_versions WHERE user_id = ? ORDER BY created_at LIMIT 1)", (user["id"],))
    conn.execute("INSERT INTO resume_versions (user_id, name, body, job_id, created_at) VALUES (?,?,?,?,?)",
                 (user["id"], name[:80], resume_engine.clean(body), job_id, time.time()))


@router.post("/job/{jid}/tailor/save")
def tailor_save(jid: int, request: Request, undo: str = Form(""), ai: int = Form(0), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "saving")
    with store.db() as conn:
        j = _live_job(conn, jid)
        p = _profile(conn, user)
        if not web.csrf_ok(request, csrf) or not j or not p.get("resume_text"):
            return RedirectResponse(f"/job/{jid}/tailor", status_code=303)
        doc = _build(conn, user, p, p["resume_text"], j, _undo(undo), f"job{jid}" if ai else "")
        _save_version(conn, user, "For " + j["title"] + " at " + j["company"], doc["text"], jid)
    return RedirectResponse(f"/job/{jid}/tailor" + _q({"ai": ai, "undo": ",".join(_undo(undo)), "saved": 1}), status_code=303)


@router.post("/job/{jid}/tailor/ai")
def tailor_ai(jid: int, request: Request, undo: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    with store.db() as conn:
        j = _live_job(conn, jid)
        p = _profile(conn, user)
        if not web.csrf_ok(request, csrf) or not j or not p.get("resume_text"):
            return RedirectResponse(f"/job/{jid}/tailor", status_code=303)
        ok = _take_ai(conn, user)
        me = _me(conn, user, p)
    o = ai_polish(me, p["resume_text"], j) if ok else None
    if not o:
        with store.db() as conn:
            return _tailor_page(conn, user, p, j, _undo(undo), False, ai_note="AI wording isn't available right now, so this is the built-in version.")
    if len(_AI_CACHE) >= _AI_CACHE_MAX:
        _AI_CACHE.pop(next(iter(_AI_CACHE)))
    _AI_CACHE[_ai_key(user, f"job{jid}", p["resume_text"])] = o
    return RedirectResponse(f"/job/{jid}/tailor?ai=1", status_code=303)


def _note_page(conn, user, p: dict, j: dict) -> HTMLResponse:
    import jobboard
    jid = int(j["id"])
    ep = store.employer_profile(conn, j["employer_id"]) if j.get("employer_id") else None
    poster = (j.get("poster_name") or (ep or {}).get("contact_name") or "").strip()
    me = _me(conn, user, p)
    note = resume_engine.cover_note(me, p["resume_text"], j, jobboard.short_name(poster) if poster else "")
    can_msg = bool(j.get("employer_id")) and store.employer_approved(conn, j["employer_id"])
    applied = can_msg and jobboard.applied(conn, jid, user["id"])
    who = esc(poster) if poster else "the hiring team"
    if applied:
        send = (f'<form method="get" action="/messages/new" class="rs-note-form"><input type="hidden" name="to" value="{int(j["employer_id"])}">'
                f'<input type="hidden" name="job" value="{jid}"><label for="n-note">Your note (edit it first)</label>'
                f'<textarea id="n-note" name="body" maxlength="4000" data-count>{esc(note)}</textarea>'
                f'<div class="row"><button class="b" type="submit">{ui.icon("chat", 16)} Continue in Messages</button>'
                f'<button class="b sec" type="button" data-copy="{esc(note)}">Copy</button></div></form>')
    else:
        why = (f"You can message {who} once you apply. Apply first, then come back here and send it."
               if can_msg else "This listing's poster can't be messaged on NoleCareerShield. Copy the note into your application instead.")
        send = (f'<label for="n-note">Your note</label><textarea id="n-note" maxlength="4000" data-count>{esc(note)}</textarea>'
                f'<div class="row"><button class="b sec" type="button" data-copy="{esc(note)}">Copy</button>'
                f'{f"<a class=b href=/job/{jid}>Go to the listing to apply</a>" if can_msg else ""}</div><p class="rs-note">{why}</p>')
    poster_line = f"To {who}" + (f", {esc(j.get('poster_title'))}" if j.get("poster_title") and poster else "") + f" · {esc(j['company'])}"
    body = (_job_tabs(jid, "note") + f'<div class="rs-gen-head"><div><h1 class="rs-t1">A short note to the poster</h1><p class="muted">{poster_line}</p></div></div>'
            f'<div class="rs-gen one"><div class="card rs-notecard">{send}</div><aside class="rs-panel"><section class="card"><h3>What makes it work</h3>'
            f'<ul class="reasons"><li><b>It\'s specific.</b><span class="ev">It names the role and one real thing you did that matches it.</span></li>'
            f'<li><b>It\'s short.</b><span class="ev">Under 120 words, so it gets read.</span></li>'
            f'<li><b>It\'s yours.</b><span class="ev">Every line comes from your resume and profile. Change anything that doesn\'t sound like you.</span></li>'
            f'<li><b>Stay safe.</b><span class="ev">Never send your SSN, bank details or ID in a first message. Real employers don\'t ask.</span></li></ul></section></aside></div>')
    return web.page(body, "Message the poster", active="/resume", js=True)


@router.get("/job/{jid}/standout", response_class=HTMLResponse)
def standout_job(jid: int, request: Request):
    user = web.require_user(request, "student")
    with store.db() as conn:
        j = _live_job(conn, jid)
        if not j:
            return web.page(ui.page_head("Help me stand out") + ui.banner("info", "That listing isn't available anymore.") +
                            '<a class="b sec" href="/jobs">Browse jobs</a>', "Help me stand out", active="/resume", status=404)
        p = _profile(conn, user)
        if not p.get("resume_text"):
            return _no_resume_page("Help me stand out")
        me = _me(conn, user, p)
        import jobboard
        ep = store.employer_profile(conn, j["employer_id"]) if j.get("employer_id") else None
        poster = (j.get("poster_name") or (ep or {}).get("contact_name") or "").strip()
    tips = resume_engine.stand_out_job(me, p["resume_text"], j)
    note = resume_engine.cover_note(me, p["resume_text"], j, jobboard.short_name(poster) if poster else "")
    cards = "".join(f'<li class="rs-tipc"><span class="n">{i}</span><div><b>{esc(t["title"])}</b><p>{esc(t["detail"])}</p></div></li>' for i, t in enumerate(tips, 1))
    body = (_job_tabs(jid, "standout") + f'<div class="rs-gen-head"><div><h1 class="rs-t1">Help me stand out</h1><p class="muted">For {esc(j["title"])} at {esc(j["company"])}. '
            f'Drawn from your own resume and profile.</p></div></div><div class="rs-gen one"><div><ol class="rs-tips">{cards}</ol></div>'
            f'<aside class="rs-panel"><section class="card"><h3>A short cover note</h3><p class="rs-cn">{esc(note)}</p><div class="row">'
            f'<button class="b sm sec" type="button" data-copy="{esc(note)}">Copy</button><a class="b sm ghost" href="/job/{jid}/tailor?mode=note">Send it to the poster</a></div></section>'
            f'<section class="card"><h3>Next</h3><p class="small muted">Put these into a resume made for this job.</p><a class="b" href="/job/{jid}/tailor">{ui.icon("file", 16)} Tailor my resume</a></section></aside></div>')
    return web.page(body, "Help me stand out", active="/resume", js=True)


# ---------- the general version: "Your optimized resume" (step 3 of the studio) ----------

def _src_text(conn, user, p: dict, src: str) -> tuple[str, str] | None:
    if src == "main":
        return (p.get("resume_text") or "", p.get("resume_name") or "My resume") if p.get("resume_text") else None
    m = re.fullmatch(r"v(\d{1,9})", src or "")
    v = _version(conn, user, int(m.group(1))) if m else None
    return (v["body"], v["name"]) if v else None


def _optimized_doc(conn, user, p: dict, src: str, undo: list, ai_on: bool) -> tuple[dict, str, str] | None:
    got = _src_text(conn, user, p, src)
    if not got:
        return None
    text, name = got
    return _build(conn, user, p, text, None, undo, "opt" + src if ai_on else ""), text, name


@router.get("/resume/optimized", response_class=HTMLResponse)
def optimized(request: Request, src: str = "main", undo: str = "", ai: int = 0, saved: int = 0):
    user = web.require_user(request, "student")
    with store.db() as conn:
        p = _profile(conn, user)
        got = _optimized_doc(conn, user, p, src, _undo(undo), bool(ai))
        if not got:
            if not p.get("resume_text"):
                return _no_resume_page("Your optimized resume")
            return RedirectResponse("/resume", status_code=303)
        doc, text, name = got
    base = {"src": src, "ai": 1 if ai else 0}
    before, after = resume_engine.report(text, p.get("skills"))["percent"], resume_engine.report(doc["text"], p.get("skills"))["percent"]
    score = (f'<section class="card rs-match"><div class="eyebrow">ATS readiness</div><div class="rs-mm"><div><span class="lbl">Before</span><b>{before}%</b></div>'
             f'<span class="arr" aria-hidden="true">→</span><div class="new"><span class="lbl">Optimized</span><b>{after}%</b></div></div>'
             f'<div class="meter"><i style="width:{before}%"></i></div><div class="meter ok"><i style="width:{after}%"></i></div>'
             f'<p class="small faint">Scored the same way as step 2. Fill in real numbers where a bullet has none to go higher.</p></section>')
    flash = ui.banner("verified", "Saved as a version. It's under Versions.") if saved else ""
    q = {**base, "undo": ",".join(_undo(undo))}
    jobs_card = (f'<section class="card"><h3>Aim it at a job</h3><p class="small muted">Tailor it to one listing and it picks the bullets and skills that job asks for.</p>'
                 f'<a class="b sec" href="/resume?tab=tailor">{ui.icon("jobs", 16)} Tailor to a job</a></section>')
    return _gen_page(doc, path="/resume/optimized", base=base, undo=_undo(undo), top=_tabs("optimize") + _steps(3, src),
                     heading="Your optimized resume", sub=f"From {esc(name)}. Same facts, clearer wording, a standard layout. Undo anything you don't want.",
                     score=score, extra=jobs_card + _ai_form("/resume/optimized/ai", {"src": src, "undo": q["undo"]}),
                     save_action="/resume/optimized/save", edit_href="/resume?tab=edit&from=" + src + ("&" + _q(q)[1:] if _q(q) else ""), flash=flash)


@router.get("/resume/optimized.{ext}")
def optimized_download(ext: str, request: Request, src: str = "main", undo: str = "", ai: int = 0):
    user = web.require_user(request, "student")
    if ext not in ("pdf", "docx", "txt"):
        return RedirectResponse("/resume/optimized", status_code=303)
    with store.db() as conn:
        p = _profile(conn, user)
        got = _optimized_doc(conn, user, p, src, _undo(undo), bool(ai))
    if not got:
        return RedirectResponse("/resume", status_code=303)
    return _send(got[0], got[0]["name"] + " resume", ext)


@router.post("/resume/optimized/save")
def optimized_save(request: Request, src: str = Form("main"), undo: str = Form(""), ai: int = Form(0), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "saving")
    with store.db() as conn:
        p = _profile(conn, user)
        got = _optimized_doc(conn, user, p, src, _undo(undo), bool(ai))
        if not web.csrf_ok(request, csrf) or not got:
            return RedirectResponse("/resume", status_code=303)
        _save_version(conn, user, "Optimized: " + got[2], got[0]["text"], None)
    return RedirectResponse("/resume/optimized" + _q({"src": src, "ai": ai, "undo": ",".join(_undo(undo)), "saved": 1}), status_code=303)


@router.post("/resume/optimized/ai")
def optimized_ai(request: Request, src: str = Form("main"), undo: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.ai_limiter, f"u{user['id']}", "AI requests")
    with store.db() as conn:
        p = _profile(conn, user)
        got = _src_text(conn, user, p, src)
        if not web.csrf_ok(request, csrf) or not got:
            return RedirectResponse("/resume", status_code=303)
        ok = _take_ai(conn, user)
        me = _me(conn, user, p)
    o = ai_polish(me, got[0], None) if ok else None
    if o:
        if len(_AI_CACHE) >= _AI_CACHE_MAX:
            _AI_CACHE.pop(next(iter(_AI_CACHE)))
        _AI_CACHE[_ai_key(user, "opt" + src, got[0])] = o
    return RedirectResponse("/resume/optimized" + _q({"src": src, "ai": 1 if o else 0, "undo": ",".join(_undo(undo))}), status_code=303)


@router.get("/resume/tailor-go")
def tailor_go(request: Request, job: str = ""):
    """The Tailor tab's job picker (a plain GET form) lands on that job's tailored resume."""
    web.require_user(request, "student")
    return RedirectResponse(f"/job/{int(job)}/tailor" if job.isdigit() else "/resume?tab=tailor", status_code=303)


def _editor_draft(conn, user, p: dict, src: str, undo: list, ai_on: bool) -> str:
    """'Open in editor': the generated resume in a text box, saved as a version (the main resume stays as it is)."""
    m = re.fullmatch(r"job(\d{1,9})", src or "")
    if m:
        j = _live_job(conn, int(m.group(1)))
        if not j or not p.get("resume_text"):
            return ""
        doc = _build(conn, user, p, p["resume_text"], j, undo, src if ai_on else "")
        name, jid, back = ("For " + j["title"] + " at " + j["company"])[:80], int(j["id"]), f"/job/{int(j['id'])}/tailor"
    else:
        got = _optimized_doc(conn, user, p, src, undo, ai_on)
        if not got:
            return ""
        doc, name, jid, back = got[0], ("Optimized: " + got[2])[:80], 0, "/resume/optimized?src=" + src
    return f"""<form method="post" action="/resume/versions" class="card rs-draft">{ui.user_csrf_input()}<input type="hidden" name="job_id" value="{jid}">
<div class="row between"><h3 class="sec" style="margin:0">Edit your new resume</h3><a class="small" href="{esc(back)}">&larr; Back to the preview</a></div>
<p class="small muted">Change anything, then save it as a version. Your main resume stays as it is.</p>
<div class="form-field"><label for="d-name">Version name</label><input id="d-name" name="name" maxlength="80" value="{esc(name)}"></div>
<label for="d-body" class="hp">Resume text</label><textarea id="d-body" class="resume" name="body" maxlength="22000" data-count>{esc(doc["text"])}</textarea>
<div class="row" style="margin-top:10px"><button class="b" type="submit">Save as version</button></div></form>"""
