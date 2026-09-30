"""The two panels every listing shows a signed-in student: how well they fit it (fit.py) and
a built-in tailoring kit for it (resume_engine.tailor), so nobody has to go looking for them."""

from __future__ import annotations

import ai
import fit
import resume_engine
import ui
from ui import esc

STATUS_MARK = {"met": "✓", "missing": "!", "unknown": "?"}
NO_REQS = '<li class="unknown"><span class="st">?</span><div>The posting doesn\'t list specific requirements.</div></li>'
NO_FOUND = '<li class="unknown"><span class="st">?</span><div>Nothing in your profile matches the skills they list yet.</div></li>'


def fit_panel(job: dict, profile: dict | None) -> str:
    if not profile or not (profile.get("skills") or profile.get("resume_text") or profile.get("items")):
        return ('<section class="card" style="margin:16px 0"><h3 class="sec" style="margin-top:0">How well you fit</h3>'
                '<p class="muted small">Add your skills, experience or resume and every listing shows a fit score built from your whole profile.</p>'
                '<div class="row" style="margin-top:10px"><a class="b sm" href="/profile">Build my profile</a><a class="b sm sec" href="/resume">Add my resume</a></div></section>')
    f = fit.fit_score(job, profile)
    tone = "ok" if f["score"] >= 65 else "warn" if f["score"] < 45 else ""
    parts = "".join(f'<div class="cat"><span>{esc(p["name"])}</span><div class="meter{" ok" if p["score"] >= 75 else " warn" if p["score"] < 40 else ""}">'
                    f'<i style="width:{p["score"]}%"></i></div><span>{p["score"]}</span><div class="why2">{esc(p["detail"])}</div></div>' for p in f["parts"])
    found = "".join(f'<li class="met"><span class="st">✓</span><div><b>{esc(m["skill"])}</b><span class="ev">Found in {esc(", ".join(w.replace("Your ", "your ", 1) for w in m["where"][:2]))}</span></div></li>'
                    for m in f["matched"][:8])
    checks = "".join(f'<li class="{c["status"]}"><span class="st">{STATUS_MARK[c["status"]]}</span><div>{esc(c["text"])}'
                     + (f'<span class="ev">{esc(c["evidence"])}</span>' if c.get("evidence") else "") + "</div></li>" for c in f["checklist"])
    relevant = "".join(f'<li class="met"><span class="st">✓</span><div><b>{esc(r["where"])}</b><span class="ev">Mentions {esc(", ".join(r["hits"][:3]))}</span></div></li>'
                       for r in f["relevant"][:4])
    conf = {"low": "Your profile is thin, so this is a rough estimate. Add experience, projects and a resume to sharpen it.",
            "medium": "Based on part of your profile. Adding more sections makes it more accurate.",
            "high": "Based on your whole profile: skills, resume, experience, projects, education and what you're looking for."}[f["confidence"]]
    return f"""<section class="card" style="margin:16px 0" id="fit"><div class="fit"><div class="ring" style="--p:{f['score']}"><b>{f['score']}</b></div>
<div><div class="eyebrow">Your fit for this job</div><div class="fitlabel">{esc(f['label'])} <span class="pill {tone}">{f['score']}/100</span></div>
<p class="small muted" style="margin-top:4px">{esc(conf)}</p></div></div>
<div class="fitparts">{parts}</div>
<div class="split" style="margin-top:14px"><div><h4 class="small" style="margin-bottom:8px">What they ask for</h4><ul class="checklist">{checks or NO_REQS}</ul></div>
<div><h4 class="small" style="margin-bottom:8px">Where your profile backs it up</h4><ul class="checklist">{relevant}{found or NO_FOUND}</ul></div></div></section>"""


def tailor_panel(job: dict, profile: dict | None) -> str:
    if not profile or not profile.get("resume_text"):
        return ('<section class="card" style="margin:16px 0" id="tailor"><h3 class="sec" style="margin-top:0">Tailor your resume to this job</h3>'
                '<p class="muted small">Add your resume and you\'ll get a summary written for this role, the bullets to lead with, and the keywords to use where they\'re true.</p>'
                '<a class="b sm" href="/resume" style="margin-top:10px">Add my resume</a></section>')
    t = resume_engine.tailor(profile["resume_text"], job["title"], job["description"], profile)
    pills = lambda xs, cls: "".join(f'<span class="pill {cls}">{esc(x)}</span>' for x in xs) or '<span class="faint small">None</span>'
    lead = "".join(f'<li><b>{esc(b["text"])}</b><span class="ev">{esc(b["why"])}</span></li>' for b in t["lead_bullets"])
    version = resume_engine.versioned(profile["resume_text"], t["summary"])
    ai_btn = (f'<form method="post" action="/resume/tailor" class="navform">{ui.user_csrf_input()}<input type="hidden" name="job_id" value="{int(job["id"])}">'
              f'<button class="b sm ghost" type="submit" name="mode" value="ai">{ui.icon("spark", 14)} AI tailor</button></form>') if ai.enabled() else ""
    return f"""<section class="card" style="margin:16px 0" id="tailor"><div class="row between"><h3 class="sec" style="margin:0">Tailor your resume to this job</h3>
<div class="row">{ai_btn}<a class="b sm sec" href="/resume?tab=tailor&amp;job={int(job['id'])}">Open in resume studio</a></div></div>
<div class="split" style="margin-top:12px"><div><b class="small">Skills your resume shows</b><div class="kw" style="margin-top:6px">{pills(t['skills_present'], 'ok')}</div></div>
<div><b class="small">Skills they want that your resume doesn't show</b><div class="kw" style="margin-top:6px">{pills(t['skills_missing'], 'warn')}</div></div></div>
<div style="margin-top:12px"><b class="small">Words from the posting to use where true</b><div class="kw" style="margin-top:6px">{pills(t['keywords_missing'], '')}</div></div>
<h4 class="small" style="margin:16px 0 6px">Suggested summary for this job</h4><div class="sugg-item" style="margin-top:0"><div class="now" style="margin-top:0">{esc(t['summary'])}</div>
<button class="b sm sec" type="button" data-copy="{esc(t['summary'])}" style="margin-top:8px">Copy</button></div>
{f'<h4 class="small" style="margin:16px 0 6px">Lead with these bullets</h4><ul class="reasons" style="margin-top:0">{lead}</ul>' if lead else ''}
<form method="post" action="/resume/versions" style="margin-top:16px">{ui.user_csrf_input()}<input type="hidden" name="job_id" value="{int(job['id'])}">
<input type="hidden" name="name" value="{esc(('For ' + job['title'] + ' at ' + job['company'])[:80])}">
<details><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Preview and edit the tailored copy</summary>
<textarea class="resume" name="body" maxlength="20000" style="margin-top:8px" aria-label="Tailored copy">\n{esc(version)}</textarea></details>
<button class="b sm" type="submit" style="margin-top:10px">Save a tailored copy</button> <span class="small faint">Your main resume doesn't change.</span></form></section>"""
