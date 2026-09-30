"""
The student profile page, a mix of LinkedIn and Handshake:

  * LinkedIn: a banner header (photo initials, name, headline, school, location, links, an
    "Open to" line) and stacked section cards for About, Experience, Education, Projects,
    Skills, Certifications, Organizations, Courses and Languages, each with add and edit.
  * Handshake: a side column with what the student is Looking for (job types, roles,
    locations, work settings), profile strength, and privacy.

Also the routes that add, edit, delete and import (from the resume) profile sections.
Other people see the same page without the edit controls, and only what the privacy
settings allow (profiles.can_view_student decides).
"""

from __future__ import annotations

import json
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import resume_parse
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

SECTIONS = [  # kind, heading, add label, empty prompt
    ("experience", "Experience", "Add experience", "Jobs, internships, research and volunteer work."),
    ("education", "Education", "Add education", "Your degree, major, GPA and coursework."),
    ("project", "Projects", "Add project", "Class, club or personal projects. These count toward your job fit."),
    ("certification", "Certifications", "Add certification", "Licenses and certifications, finished or in progress."),
    ("organization", "Organizations", "Add organization", "Clubs, societies, teams and leadership roles."),
    ("course", "Courses", "Add course", "Courses that show what you know."),
    ("language", "Languages", "Add language", "Languages you speak."),
]
HEADINGS = {k: h for k, h, _, _ in SECTIONS}
EMPLOYMENT = ["Internship", "Part-time", "Full-time", "On-campus job", "Research", "Volunteer", "Freelance", "Seasonal"]
PROFICIENCY = ["Elementary", "Limited working", "Professional working", "Full professional", "Native or bilingual"]
_DATE = re.compile(r"^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+|(?:spring|summer|fall|winter)\s+)?(?:19|20)\d{2}$", re.I)
MAX_ITEMS = 60


class ItemError(ValueError):
    pass


# ---------- storage ----------

def add_item(conn, uid: int, it: dict) -> int:
    n = conn.execute("SELECT COUNT(*) FROM profile_items WHERE user_id = ?", (uid,)).fetchone()[0]
    if n >= MAX_ITEMS:
        raise ItemError(f"A profile can hold up to {MAX_ITEMS} entries.")
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM profile_items WHERE user_id = ? AND kind = ?", (uid, it["kind"])).fetchone()[0]
    cur = conn.execute("INSERT INTO profile_items (user_id, kind, title, org, location, start, end, current, description, url, extra, position, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (uid, it["kind"], it.get("title", ""), it.get("org", ""), it.get("location", ""), it.get("start", ""), it.get("end", ""),
                        1 if it.get("current") else 0, it.get("description", ""), it.get("url", ""), json.dumps(it.get("extra") or {}), pos, time.time()))
    return cur.lastrowid


def import_resume(conn, uid: int, text: str) -> int:
    """Add what the resume shows that the profile doesn't have yet. Returns how many entries were added."""
    parsed = resume_parse.to_profile(text)
    have = {(i["kind"], i["title"].lower(), i["org"].lower()) for i in store.profile_items(conn, uid)}
    added = 0
    for it in parsed["items"]:
        key = (it["kind"], it["title"].lower(), it["org"].lower())
        if key in have:
            continue
        try:
            clean = _clean_item(it)
        except ItemError:
            try:                                  # a date the form wouldn't accept ("Expected 2027"): keep the entry, drop the date
                clean = _clean_item(dict(it, start="", end=""))
            except ItemError:
                continue                          # one odd line shouldn't stop the rest of the import
        try:
            add_item(conn, uid, clean)
        except ItemError:
            break                                 # the profile is full
        have.add(key)
        added += 1
    p = store.student_profile(conn, uid) or {}
    skills = list(p.get("skills") or [])
    for s in parsed["skills"]:
        if s.lower() not in {x.lower() for x in skills} and len(skills) < 40:
            skills.append(s)
    conn.execute("UPDATE student_profiles SET skills = ?, updated_at = ? WHERE user_id = ?", (json.dumps(skills), time.time(), uid))
    return added


def _t(v, limit: int, label: str, required: bool = False, multiline: bool = False) -> str:
    v = security._CONTROL_CHARS_RE.sub("", str(v or "")).strip()
    if not multiline:
        v = re.sub(r"\s+", " ", v)
    if len(v) > limit:
        raise ItemError(f"{label} is too long (max {limit} characters).")
    if required and not v:
        raise ItemError(f"{label} is required.")
    return v


def _date(v, label: str) -> str:
    v = _t(v, 20, label)
    if v and not _DATE.match(v):
        raise ItemError(f"{label}: use a month and year like May 2025, or just a year.")
    return v


def _link(v) -> str:
    v = _t(v, 300, "Link")
    if not v:
        return ""
    if not v.lower().startswith(("http://", "https://")):
        v = "https://" + v
    if not re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?$", v):
        raise ItemError("That link doesn't look like a web address.")
    return v


def _clean_item(f: dict) -> dict:
    kind = f.get("kind")
    if kind not in store.ITEM_KINDS:
        raise ItemError("Pick a section.")
    ex = f.get("extra") or {}
    it = {"kind": kind, "title": _t(f.get("title"), 120, "Title", required=kind != "education"), "org": _t(f.get("org"), 120, "Organization"),
          "location": _t(f.get("location"), 80, "Location"), "start": _date(f.get("start"), "Start"), "end": _date(f.get("end"), "End"),
          "current": bool(f.get("current")), "description": _t(f.get("description"), 2000, "Description", multiline=True), "url": _link(f.get("url")),
          "extra": {}}
    if kind == "education":
        if not it["org"]:
            raise ItemError("School is required.")
        gpa = _t(ex.get("gpa"), 5, "GPA")
        if gpa and not re.fullmatch(r"[0-4](?:\.\d{1,2})?", gpa):
            raise ItemError("GPA should look like 3.4 (on a 4.0 scale).")
        cw = ex.get("coursework")
        cw = cw if isinstance(cw, list) else [c for c in re.split(r"[,;]", str(cw or ""))]
        it["extra"] = {k: v for k, v in {"major": _t(ex.get("major"), 80, "Major"), "minor": _t(ex.get("minor"), 80, "Minor"), "gpa": gpa,
                                         "coursework": [c for c in (_t(x, 80, "Course") for x in cw) if c][:20]}.items() if v}
    elif kind == "experience":
        t = ex.get("type") or ""
        it["extra"] = {"type": t} if t in EMPLOYMENT else {}
    elif kind == "project":
        sk = ex.get("skills")
        sk = ", ".join(sk) if isinstance(sk, list) else str(sk or "")
        it["extra"] = {"skills": _t(sk, 200, "Skills used")} if sk.strip() else {}
    elif kind == "language":
        pr = ex.get("proficiency") or ""
        it["extra"] = {"proficiency": pr} if pr in PROFICIENCY else {}
    if it["current"]:
        it["end"] = ""
    return it


# ---------- rendering ----------

def _dates(it: dict) -> str:
    a, b = it.get("start") or "", "Present" if it.get("current") else (it.get("end") or "")
    return f"{a} – {b}" if a and b else (a or b)


def _logo(text: str, kind: str) -> str:
    return f'<span class="logo{" edu" if kind == "education" else ""}" aria-hidden="true">{ui.initials(text or "?")}</span>'


def entry_html(it: dict, owner: bool) -> str:
    k, ex = it["kind"], it.get("extra") or {}
    edit = f'<a class="b sm ghost" href="/profile/items/{int(it["id"])}">Edit</a>' if owner and it.get("id") else ""
    if k == "education":
        head = esc(it["org"])
        sub = " · ".join(esc(x) for x in (it.get("title"), ex.get("major") and f"Major: {ex['major']}", ex.get("minor") and f"Minor: {ex['minor']}") if x)
        meta = " · ".join(x for x in (esc(_dates(it)), ex.get("gpa") and f"GPA {esc(ex['gpa'])}") if x)
        more = ('<div class="chips">' + "".join(f'<span class="chip">{esc(c)}</span>' for c in ex.get("coursework") or []) + "</div>") if ex.get("coursework") else ""
        logo = _logo(it["org"], k)
    elif k in ("language", "course"):
        note = ex.get("proficiency") if k == "language" else it.get("org")
        note_html = f' <span class="faint">· {esc(note)}</span>' if note else ""
        return f'<div class="entry slim"><div><b>{esc(it["title"])}</b>{note_html}</div>{edit}</div>'
    else:
        head = esc(it["title"])
        typ = ex.get("type")
        sub = " · ".join(esc(x) for x in (it.get("org"), typ) if x)
        meta = " · ".join(esc(x) for x in (_dates(it), it.get("location")) if x)
        more = ""
        if k == "project" and ex.get("skills"):
            more = '<div class="chips">' + "".join(f'<span class="chip">{esc(s.strip())}</span>' for s in ex["skills"].split(",") if s.strip()) + "</div>"
        logo = _logo(it.get("org") or it["title"], k)
    desc = f'<div class="desc">{esc(it["description"])}</div>' if it.get("description") else ""
    link = (f'<a class="small" href="{esc(it["url"])}" target="_blank" rel="noopener noreferrer nofollow ugc">{esc(re.sub(r"^https?://", "", it["url"])[:60])} ↗</a>'
            if it.get("url") else "")
    return (f'<div class="entry">{logo}<div class="body"><div class="row between" style="align-items:flex-start;flex-wrap:nowrap"><div style="min-width:0">'
            f'<div class="t">{head}</div>{f"<div class=s>{sub}</div>" if sub else ""}{f"<div class=m>{meta}</div>" if meta else ""}</div>{edit}</div>'
            f'{desc}{link}{more}</div></div>')


def _section(kind: str, items: list[dict], owner: bool) -> str:
    title = HEADINGS[kind]
    add, prompt = next((a, p) for k, _, a, p in SECTIONS if k == kind)
    mine = [i for i in items if i["kind"] == kind]
    if not mine and not owner:
        return ""
    plus = f'<a class="iconbtn" href="/profile/items/new?kind={kind}" aria-label="{esc(add)}" title="{esc(add)}">{ui.icon("plus", 18)}</a>' if owner else ""
    body = "".join(entry_html(i, owner) for i in mine) if mine else f'<p class="muted small">{esc(prompt)} <a href="/profile/items/new?kind={kind}">{esc(add)}</a></p>'
    slim = " slimlist" if kind in ("course", "language") else ""
    return f'<section class="card pcard" id="{kind}"><div class="phead"><h2>{esc(title)}</h2>{plus}</div><div class="entries{slim}">{body}</div></section>'


def _school_line(p: dict) -> str:
    edu = [i for i in p.get("items") or [] if i["kind"] == "education"]
    school = edu[0]["org"] if edu else "Florida State University"
    yr = re.search(r"(?:19|20)(\d{2})", p.get("grad_term") or "")
    return f"{school}" + (f" '{yr.group(1)}" if yr else "") + (f" · {p['major']}" if p.get("major") else "")


def profile_html(p: dict, *, owner: bool, show_links: bool = True, show_resume: bool = False, message_btn: str = "",
                 notice: str = "", completion: tuple[int, list[str]] | None = None, show_sections: bool = True) -> str:
    """show_sections=False is what other students get: the basics, never experience or education entries."""
    items = (p.get("items") or []) if (owner or show_sections) else []
    name = p.get("display_name") or "FSU student"
    pron = f' <span class="pron">({esc(p["pronouns"])})</span>' if p.get("pronouns") else ""
    links = ""
    if show_links:
        for key, label in (("linkedin", "LinkedIn"), ("website", "Website")):
            if (p.get("links") or {}).get(key):
                links += f'<a href="{esc(p["links"][key])}" target="_blank" rel="noopener noreferrer nofollow ugc">{label} ↗</a>'
    kinds = {"internship": "Internships", "part-time": "Part-time", "full-time": "Full-time", "on-campus": "On-campus jobs"}
    open_to = [kinds.get(k, k) for k in p.get("job_kinds") or []] + [w.title() for w in p.get("work_types") or []]
    opento = (f'<div class="opento"><b>Open to</b> {esc(" · ".join(open_to))}' +
              (f' <a href="/profile/setup/2">Edit</a>' if owner else "") + "</div>") if open_to else (
        '<div class="opento muted"><b>Open to</b> <a href="/profile/setup/2">Add what you\'re looking for</a></div>' if owner else "")
    actions = ('<div class="row"><a class="b sm sec" href="/profile/setup/1">Edit intro</a>'
               + (f'<form method="post" action="/profile/import" class="navform">{ui.user_csrf_input()}<button class="b sm ghost" type="submit">Fill from resume</button></form>'
                  if p.get("resume_text") else '<a class="b sm ghost" href="/resume">Add resume</a>') + "</div>") if owner else message_btn
    hero = f"""<section class="card phero"><div class="pbanner ph" aria-hidden="true" style="--ph:url({ui.media_url('arch-074.webp')})"></div><div class="pinfo">
<span class="avatar xl">{ui.initials(name)}</span>
<div class="row between" style="align-items:flex-end;gap:14px"><div style="min-width:0">
<h1>{esc(name)}{pron}</h1>{f'<p class="headline">{esc(p["headline"])}</p>' if p.get("headline") else ""}
<p class="school">{esc(_school_line(p))}</p>
<p class="where">{esc(p.get("location") or "Tallahassee, FL")}{" · " if links else ""}<span class="plinks">{links}</span></p></div>{actions}</div>
{opento}</div></section>"""

    roles, locs = p.get("looking_roles") or [], p.get("pref_locations") or []
    look = [("Job types", [kinds.get(k, k) for k in p.get("job_kinds") or []]), ("Roles", roles), ("Industries", p.get("interests") or []),
            ("Locations", locs), ("Work setting", [w.title() for w in p.get("work_types") or []])]
    look_html = "".join(f'<div class="lf"><div class="lfl">{esc(lbl)}</div><div class="chips">' + "".join(f'<span class="pill accent">{esc(v)}</span>' for v in vals[:8]) + "</div></div>"
                        for lbl, vals in look if vals)
    edit_look = f'<a class="iconbtn" href="/profile/setup/2" aria-label="Edit what you\'re looking for">{ui.icon("file", 16)}</a>' if owner else ""
    empty_look = ('<p class="small muted">Tell employers and the job assistant what you want. <a href="/profile/setup/2">Add it</a></p>' if owner
                  else '<p class="small muted">Not shared yet.</p>')
    side = f'<section class="card"><div class="phead"><h2>Looking for</h2>{edit_look}</div>{look_html or empty_look}</section>'
    if owner and completion:
        pct, missing = completion
        side += (f'<section class="card"><div class="phead"><h2>Profile strength</h2><span class="small faint">{pct}%</span></div><div class="meter"><i style="width:{pct}%"></i></div>'
                 + (f'<p class="small muted" style="margin-top:8px">Next: add {esc(", ".join(missing[:2]))}. A fuller profile makes your job fit scores more accurate.</p>' if missing else
                    '<p class="small muted" style="margin-top:8px">Complete. Your fit scores use all of it.</p>') + "</section>")
        vis = [p.get("visible_to_employers") and "Approved employers can find you" or "Hidden from the employer directory",
               "resume shared with them" if p.get("share_resume") else "resume private",
               "messages on" if p.get("allow_messages") else "employer messages off"]
        side += (f'<section class="card"><div class="phead"><h2>Privacy</h2><a class="small" href="/profile/setup/3">Change</a></div>'
                 f'<p class="small muted">{esc("; ".join(vis)).capitalize()}.</p></section>')

    about = p.get("bio") or ""
    about_html = ""
    if about or owner:
        edit_about = f'<a class="iconbtn" href="/profile/setup/1" aria-label="Edit about">{ui.icon("file", 16)}</a>' if owner else ""
        about_html = (f'<section class="card pcard"><div class="phead"><h2>About</h2>{edit_about}</div>'
                      + (f'<p class="desc">{esc(about)}</p>' if about else '<p class="small muted">A few sentences about you and what you want next. <a href="/profile/setup/1">Write it</a></p>')
                      + "</section>")
    skills = p.get("skills") or []
    edit_skills = f'<a class="iconbtn" href="/profile/setup/2" aria-label="Edit skills">{ui.icon("plus", 18)}</a>' if owner else ""
    skills_html = (f'<section class="card pcard" id="skills"><div class="phead"><h2>Skills</h2>{edit_skills}</div>'
                   + ('<div class="chips">' + "".join(f'<span class="pill">{esc(s)}</span>' for s in skills) + "</div>" if skills else '<p class="small muted">No skills added yet.</p>')
                   + "</section>") if skills or owner else ""
    order = ["experience", "education", "project"]
    main = about_html + "".join(_section(k, items, owner) for k in order) + skills_html + "".join(_section(k, items, owner) for k in ("certification", "organization", "course", "language"))
    if not owner and not show_sections:
        main += '<p class="small faint">Experience, education and projects are shared with approved employers only.</p>'
    if show_resume and p.get("resume_text"):
        main += f'<section class="card pcard"><div class="phead"><h2>Resume</h2></div><div class="desc" style="font-family:var(--serif);font-size:14px">{esc(p["resume_text"])}</div></section>'
    elif owner:
        main += (f'<section class="card pcard"><div class="phead"><h2>Resume</h2><a class="small" href="/resume">Open resume studio</a></div>'
                 + (f'<p class="small muted">{esc(p.get("resume_name") or "Resume")} on file. '
                    f'{"Shared with approved employers who can see your profile." if p.get("share_resume") else "Only you can see it."}</p>' if p.get("resume_text")
                    else '<p class="small muted">Add your resume to fill your profile in one step and get fit scores on every job.</p>') + "</section>")
    return notice + hero + f'<div class="pgrid"><aside class="pside">{side}</aside><div class="pmain">{main}</div></div>'


# ---------- routes ----------

def _form_page(kind: str, it: dict | None, error: str = "", status: int = 200) -> HTMLResponse:
    it = it or {}
    ex = it.get("extra") or {}
    v = lambda k: esc(it.get(k) or "")
    x = lambda k: esc(ex.get(k) if not isinstance(ex.get(k), list) else ", ".join(ex.get(k)))
    field = lambda fid, name, label, val, hint="", req=False, ml=120, ph="": (
        f'<div class="form-field"><label for="{fid}">{label}</label>{f"<p class=hint>{hint}</p>" if hint else ""}'
        f'<input id="{fid}" name="{name}" maxlength="{ml}" value="{val}"{" required" if req else ""} placeholder="{esc(ph)}"></div>')
    dates = (f'<div class="grid2">{field("i-start", "start", "Start", v("start"), ph="Aug 2025", ml=20)}'
             f'{field("i-end", "end", "End", v("end"), ph="May 2026", ml=20)}</div>'
             f'<label class="toggle"><input type="checkbox" name="current" value="1"{" checked" if it.get("current") else ""}><span>I\'m currently doing this</span></label>')
    desc = (f'<div class="form-field"><label for="i-desc">Description</label><p class="hint">What you did and what came of it. One point per line works well.</p>'
            f'<textarea id="i-desc" name="description" maxlength="2000">{v("description")}</textarea></div>')
    if kind == "experience":
        opts = "".join(f'<option{" selected" if ex.get("type") == t else ""}>{t}</option>' for t in EMPLOYMENT)
        body = (field("i-title", "title", "Title", v("title"), req=True, ph="Data Analyst Intern") + field("i-org", "org", "Company or organization", v("org"), ph="Leon County Health Department")
                + f'<div class="grid2"><div class="form-field"><label for="i-type">Type</label><select id="i-type" name="x_type"><option value="">Choose...</option>{opts}</select></div>'
                + field("i-loc", "location", "Location", v("location"), ph="Tallahassee, FL or Remote", ml=80) + "</div>" + dates + desc)
    elif kind == "education":
        body = (field("i-org", "org", "School", v("org"), req=True, ph="Florida State University") + field("i-title", "title", "Degree", v("title"), ph="Bachelor of Science")
                + f'<div class="grid2">{field("i-major", "x_major", "Major", x("major"), ml=80, ph="Statistics")}{field("i-minor", "x_minor", "Minor", x("minor"), ml=80)}</div>'
                + f'<div class="grid2">{field("i-start", "start", "Start", v("start"), ph="Aug 2025", ml=20)}{field("i-end", "end", "Graduation (or expected)", v("end"), ph="May 2027", ml=20)}</div>'
                + field("i-gpa", "x_gpa", "GPA (optional)", x("gpa"), hint="Only add it if you're comfortable sharing it. Jobs that ask for a minimum GPA use it.", ml=5, ph="3.4")
                + field("i-cw", "x_coursework", "Relevant coursework", x("coursework"), hint="Separate with commas.", ml=600, ph="Business Analytics, Statistics I")
                + desc.replace("What you did and what came of it. One point per line works well.", "Honors, activities or a thesis."))
    elif kind == "project":
        body = (field("i-title", "title", "Project name", v("title"), req=True, ph="Personal budget dashboard")
                + field("i-org", "org", "Associated with (optional)", v("org"), hint="A class, club, hackathon or company.", ph="ISM 3011")
                + field("i-url", "url", "Link (optional)", v("url"), hint="GitHub, a live site or a file.", ml=300, ph="github.com/you/project")
                + field("i-skills", "x_skills", "Skills used", x("skills"), hint="Separate with commas. These count toward your fit score.", ml=200, ph="Python, SQL, Excel")
                + dates + desc)
    elif kind == "certification":
        body = (field("i-title", "title", "Name", v("title"), req=True, ph="Microsoft Office Specialist: Excel Expert") + field("i-org", "org", "Issuing organization", v("org"), ph="Microsoft")
                + f'<div class="grid2">{field("i-start", "start", "Issued", v("start"), ph="Mar 2026", ml=20)}{field("i-end", "end", "Expires (optional)", v("end"), ml=20)}</div>'
                + field("i-url", "url", "Credential link (optional)", v("url"), ml=300))
    elif kind == "organization":
        body = (field("i-org", "org", "Organization", v("org"), req=True, ph="The Finance Society") + field("i-title", "title", "Role", v("title"), req=True, ph="Member")
                + dates + desc)
    elif kind == "course":
        body = field("i-title", "title", "Course name", v("title"), req=True, ph="Business Analytics") + field("i-org", "org", "Course code (optional)", v("org"), ph="QMB 3200")
    else:
        opts = "".join(f'<option{" selected" if ex.get("proficiency") == t else ""}>{t}</option>' for t in PROFICIENCY)
        body = (field("i-title", "title", "Language", v("title"), req=True, ph="Spanish", ml=60)
                + f'<div class="form-field"><label for="i-prof">Proficiency</label><select id="i-prof" name="x_proficiency"><option value="">Choose...</option>{opts}</select></div>')
    heading = ("Edit " if it.get("id") else "Add ") + HEADINGS[kind].lower().rstrip("s").replace("educatio", "education")
    delete = (f'<form method="post" action="/profile/items/{int(it["id"])}/delete" style="margin-top:12px">{ui.user_csrf_input()}'
              f'<button class="b danger sm" type="submit">Delete this entry</button></form>') if it.get("id") else ""
    err = ui.banner("warning", error) if error else ""
    page = (f'<a class="back" href="/profile#{kind}">← Profile</a>{ui.page_head(heading)}{err}<form method="post" action="/profile/items" class="card" style="max-width:680px">'
            f'{ui.user_csrf_input()}<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="id" value="{int(it.get("id") or 0)}">{body}'
            f'<div class="row"><button class="submit-btn" type="submit">Save</button><a class="b sec" href="/profile#{kind}">Cancel</a></div></form>{delete}')
    return web.page(page, heading, active="/profile", js=True, status=status)


@router.get("/profile/items/new", response_class=HTMLResponse)
def new_item(request: Request, kind: str = "experience"):
    web.require_user(request, "student")
    return _form_page(kind if kind in store.ITEM_KINDS else "experience", None)


@router.get("/profile/items/{iid}", response_class=HTMLResponse)
def edit_item(iid: int, request: Request):
    user = web.require_user(request, "student")
    with store.db() as conn:
        it = next((i for i in store.profile_items(conn, user["id"]) if i["id"] == iid), None)
    if not it:
        return RedirectResponse("/profile", status_code=303)
    return _form_page(it["kind"], it)


@router.post("/profile/items", response_class=HTMLResponse)
async def save_item(request: Request):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "profile updates")
    form = await request.form()
    if not web.csrf_ok(request, form.get("csrf")):
        return RedirectResponse("/profile", status_code=303)
    raw = {k: str(form.get(k) or "") for k in ("kind", "title", "org", "location", "start", "end", "description", "url")}
    raw["current"] = bool(form.get("current"))
    raw["extra"] = {k[2:]: str(form.get(k) or "") for k in form.keys() if k.startswith("x_")}
    iid = int(str(form.get("id") or "0")) if str(form.get("id") or "0").isdigit() else 0
    try:
        it = _clean_item(raw)
    except ItemError as e:
        shown = dict(raw, id=iid, extra={k: v for k, v in raw["extra"].items()})
        return _form_page(raw["kind"] if raw["kind"] in store.ITEM_KINDS else "experience", shown, str(e), 400)
    with store.db() as conn:
        if iid:
            conn.execute("UPDATE profile_items SET title=?, org=?, location=?, start=?, end=?, current=?, description=?, url=?, extra=? "
                         "WHERE id = ? AND user_id = ?", (it["title"], it["org"], it["location"], it["start"], it["end"], 1 if it["current"] else 0,
                                                           it["description"], it["url"], json.dumps(it["extra"]), iid, user["id"]))
        else:
            try:
                add_item(conn, user["id"], it)
            except ItemError as e:
                return _form_page(it["kind"], raw, str(e), 400)
        conn.execute("UPDATE student_profiles SET updated_at = ? WHERE user_id = ?", (time.time(), user["id"]))
    return RedirectResponse(f"/profile#{it['kind']}", status_code=303)


@router.post("/profile/items/{iid}/delete")
async def delete_item(iid: int, request: Request):
    user = web.require_user(request, "student")
    form = await request.form()
    if web.csrf_ok(request, form.get("csrf")):
        with store.db() as conn:
            conn.execute("DELETE FROM profile_items WHERE id = ? AND user_id = ?", (iid, user["id"]))
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/import")
async def import_route(request: Request):
    user = web.require_user(request, "student")
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "profile updates")
    form = await request.form()
    if not web.csrf_ok(request, form.get("csrf")):
        return RedirectResponse("/profile", status_code=303)
    with store.db() as conn:
        p = store.student_profile(conn, user["id"]) or {}
        n = import_resume(conn, user["id"], p.get("resume_text") or "") if p.get("resume_text") else 0
    return RedirectResponse(f"/profile?imported={n}", status_code=303)
