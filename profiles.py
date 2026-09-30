"""
Profiles: the setup steps after sign-up, profile pages, the student directory for approved
employers, the signed-in home (bento dashboard), data export and account deletion.

Who sees what:
  * A student's own profile: everything.
  * Other signed-in students: name, major, class year, headline, bio and skills. Never the resume.
  * Approved employers: the same, plus links, only when the student turned on "let approved
    employers find me" or has a conversation with that employer. The resume only if the
    student also turned on "share my resume".
  * Visitors and unapproved employers: nothing.
Employer profiles are reviewed by a person before the employer can message students or post
to the feed (their job listings are reviewed one by one, as before).
"""

from __future__ import annotations

import json
import re
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import accounts
import ai
import matching
import resume_engine
import security
import store
import ui
import web
from matching import CATEGORIES, JOB_KINDS, POPULAR, WORK_TYPES
from ui import esc

router = APIRouter()

DEGREES = ["Bachelor's", "Master's", "PhD", "Professional (JD, MD...)", "Certificate", "Other"]
TERMS = [f"{s} {y}" for y in range(2025, 2033) for s in ("Spring", "Summer", "Fall")]
INDUSTRIES = ["Technology", "Finance & Banking", "Accounting", "Consulting", "Healthcare", "Education", "Government & Public Sector",
              "Nonprofit", "Retail", "Hospitality & Food", "Marketing & Media", "Real Estate", "Manufacturing & Logistics",
              "Research", "Legal", "Sports & Recreation", "Other"]
SIZES = ["1-10", "11-50", "51-200", "201-1,000", "1,000+"]
STUDENT_STEPS = ["About you", "Skills & goals", "Resume & privacy"]
EMPLOYER_STEPS = ["Company", "Contact & FSU connection"]

_NAME = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .'\-]{1,59}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ProfileError(ValueError):
    pass


def _t(value: str, limit: int, label: str, required: bool = False, multiline: bool = False) -> str:
    v = _CTRL.sub("", (value or "").strip())
    if not multiline:
        v = re.sub(r"\s+", " ", v)
    if len(v) > limit:
        raise ProfileError(f"{label} is too long (max {limit} characters).")
    if required and not v:
        raise ProfileError(f"{label} is required.")
    return v


def _url(value: str, label: str, host_must: str = "") -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if not v.lower().startswith(("http://", "https://")):
        v = "https://" + v
    if len(v) > 300 or not re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?$", v):
        raise ProfileError(f"{label} doesn't look like a web address.")
    host = re.match(r"^https?://([^/?#]+)", v).group(1).lower()
    if host_must and not (host == host_must or host.endswith("." + host_must)):
        raise ProfileError(f"{label} should be a {host_must} address.")
    return v


def _pick(values: list[str], allowed: list[str], cap: int = 20) -> list[str]:
    out = []
    for v in values:
        if v in allowed and v not in out:
            out.append(v)
    return out[:cap]


# ---------- storage ----------

def ensure_student(conn, uid: int) -> dict:
    now = time.time()
    conn.execute("INSERT OR IGNORE INTO student_profiles (user_id, created_at, updated_at) VALUES (?,?,?)", (uid, now, now))
    return store.student_profile(conn, uid)


def ensure_employer(conn, uid: int) -> dict:
    now = time.time()
    conn.execute("INSERT OR IGNORE INTO employer_profiles (user_id, created_at, updated_at) VALUES (?,?,?)", (uid, now, now))
    return store.employer_profile(conn, uid)


def save_student(conn, uid: int, **fields) -> None:
    ensure_student(conn, uid)
    for k in ("skills", "interests", "work_types", "job_kinds", "links"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE student_profiles SET {cols} WHERE user_id = ?", (*fields.values(), uid))


def save_employer(conn, uid: int, **fields) -> None:
    ensure_employer(conn, uid)
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE employer_profiles SET {cols} WHERE user_id = ?", (*fields.values(), uid))


def student_completion(p: dict | None) -> tuple[int, list[str]]:
    if not p:
        return 0, ["your name and major", "skills", "a resume"]
    checks = [
        (bool(p.get("display_name")), "your name"), (bool(p.get("major")), "your major"),
        (bool(p.get("grad_term")), "your graduation term"), (len(p.get("skills") or []) >= 3, "at least 3 skills"),
        (bool(p.get("interests")), "the kinds of jobs you want"), (bool(p.get("resume_text")), "a resume"),
        (bool(p.get("headline")), "a headline"),
    ]
    done = sum(1 for ok, _ in checks if ok)
    return round(100 * done / len(checks)), [label for ok, label in checks if not ok]


def student_ready(p: dict | None) -> bool:
    return bool(p and p.get("display_name") and p.get("major"))


# ---------- setup ----------

def _steps_bar(n: int, total: int, names: list[str]) -> str:
    bars = "".join(f'<span class="{"on" if i < n else ""}"></span>' for i in range(total))
    return f'<div class="stepname">Step {n} of {total} · {esc(names[n - 1])}</div><div class="steps" aria-hidden="true">{bars}</div>'


def _opts(values: list[str], current: str, blank: str = "Choose...") -> str:
    out = f'<option value="">{esc(blank)}</option>' if blank else ""
    return out + "".join(f'<option{" selected" if v == current else ""}>{esc(v)}</option>' for v in values)


def _checks(name: str, values: list[str], chosen: list[str], labels: dict | None = None) -> str:
    return '<div class="checks">' + "".join(
        f'<label class="chk"><input type="checkbox" name="{name}" value="{esc(v)}"{" checked" if v in chosen else ""}>'
        f'<span>{esc((labels or {}).get(v, v))}</span></label>' for v in values) + "</div>"


def _setup_page(body: str, title: str, error: str = "", status: int = 200) -> HTMLResponse:
    err = ui.banner("warning", error) if error else ""
    return web.page(f'<div style="max-width:680px">{err}{body}</div>', title, active="/profile", js=True, status=status)


def _student_step(p: dict, step: int, error: str = "", status: int = 200) -> HTMLResponse:
    csrf = ui.user_csrf_input()
    bar = _steps_bar(step, 3, STUDENT_STEPS)
    if step == 1:
        body = f"""{bar}{ui.page_head("Let's set up your profile", "Employers on NoleCareerShield see this, and the job assistant uses it to find matches. It takes about two minutes.")}
<form method="post" action="/profile/setup/1" class="card">{csrf}
<div class="grid2"><div class="form-field"><label for="p-name">Name to show</label><p class="hint">First name and last initial is fine.</p>
<input id="p-name" name="display_name" required maxlength="60" value="{esc(p.get('display_name'))}" placeholder="Jordan R."></div>
<div class="form-field"><label for="p-pro">Pronouns (optional)</label><p class="hint">Shown next to your name.</p>
<input id="p-pro" name="pronouns" maxlength="24" value="{esc(p.get('pronouns'))}" placeholder="she/her"></div></div>
<div class="grid2"><div class="form-field"><label for="p-major">Major</label><input id="p-major" name="major" required maxlength="80" value="{esc(p.get('major'))}" placeholder="Statistics"></div>
<div class="form-field"><label for="p-minor">Minor (optional)</label><input id="p-minor" name="minor" maxlength="80" value="{esc(p.get('minor'))}"></div></div>
<div class="grid2"><div class="form-field"><label for="p-deg">Degree</label><select id="p-deg" name="degree">{_opts(DEGREES, p.get('degree', ''))}</select></div>
<div class="form-field"><label for="p-grad">Graduating</label><select id="p-grad" name="grad_term">{_opts(TERMS, p.get('grad_term', ''))}</select></div></div>
<div class="form-field"><label for="p-head">Headline (optional)</label><p class="hint">One line about what you're looking for.</p>
<input id="p-head" name="headline" maxlength="120" value="{esc(p.get('headline'))}" placeholder="Stats + CS student looking for a data internship"></div>
<div class="form-field"><label for="p-bio">About (optional)</label><textarea id="p-bio" name="bio" maxlength="600" data-count style="min-height:90px">{esc(p.get('bio'))}</textarea></div>
<button class="submit-btn" type="submit">Continue</button></form>"""
        return _setup_page(body, "Set up your profile", error, status)
    if step == 2:
        chosen = p.get("skills") or []
        extra = [s for s in chosen if s not in POPULAR]
        kinds = {"internship": "Internship", "part-time": "Part-time", "full-time": "Full-time", "on-campus": "On campus"}
        body = f"""{bar}{ui.page_head("Skills and goals", "These drive your job matches. Pick what you've actually used, in class, at work or in a club.")}
<form method="post" action="/profile/setup/2" class="card">{csrf}
<div class="form-field"><label>Skills</label><p class="hint">Pick any that fit.</p>{_checks("skills", POPULAR, chosen)}</div>
<div class="form-field"><label for="p-more">Other skills (optional)</label><p class="hint">Separate with commas, e.g. SPSS, Canva, Premiere Pro.</p>
<input id="p-more" name="more_skills" maxlength="400" value="{esc(', '.join(extra))}"></div>
<div class="form-field"><label>Kinds of jobs you want</label>{_checks("interests", CATEGORIES[:-1], p.get('interests') or [])}</div>
<div class="grid2"><div class="form-field"><label>Work setting</label>{_checks("work_types", WORK_TYPES, p.get('work_types') or [], {w: w.title() for w in WORK_TYPES})}</div>
<div class="form-field"><label>Type</label>{_checks("job_kinds", JOB_KINDS, p.get('job_kinds') or [], kinds)}</div></div>
<div class="row"><a class="b sec" href="/profile/setup/1">Back</a><button class="submit-btn" type="submit">Continue</button></div></form>"""
        return _setup_page(body, "Skills and goals", error, status)
    links = p.get("links") or {}
    has = p.get("resume_text")
    resume_note = (f'<p class="small ok" style="color:var(--ok)">✓ Resume on file ({esc(p.get("resume_name") or "pasted")}). Upload a new one to replace it.</p>'
                   if has else "")
    body = f"""{bar}{ui.page_head("Resume and privacy", "Add your resume to get reviews, tailoring and better matches. You decide who can see it.")}
<form method="post" action="/profile/setup/3" class="card" enctype="multipart/form-data">{csrf}
<div class="form-field"><label for="p-file">Upload your resume (optional)</label><p class="hint">PDF, Word (.docx) or text, up to 2 MB. We keep the text only, not the file.</p>
{resume_note}<input id="p-file" type="file" name="resume" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"></div>
<details style="margin:-6px 0 16px"><summary class="small" style="cursor:pointer;color:var(--accent-ink);font-weight:600">Or paste the text</summary>
<textarea name="resume_paste" maxlength="20000" style="margin-top:8px" placeholder="Paste your resume here"></textarea></details>
<div class="grid2"><div class="form-field"><label for="p-li">LinkedIn (optional)</label><input id="p-li" name="linkedin" maxlength="300" value="{esc(links.get('linkedin', ''))}" placeholder="linkedin.com/in/you"></div>
<div class="form-field"><label for="p-web">GitHub or portfolio (optional)</label><input id="p-web" name="website" maxlength="300" value="{esc(links.get('website', ''))}" placeholder="github.com/you"></div></div>
<h3 class="sec" style="margin-top:6px">Privacy</h3>
<label class="toggle"><input type="checkbox" name="visible" value="1"{" checked" if p.get("visible_to_employers") else ""}><span><b>Let approved employers find me.</b> Your name, major, class year, headline and skills appear in the student directory. Only employers our reviewers approved can see it.</span></label>
<label class="toggle"><input type="checkbox" name="share_resume" value="1"{" checked" if p.get("share_resume") else ""}><span><b>Share my resume with approved employers</b> who can see my profile.</span></label>
<label class="toggle"><input type="checkbox" name="allow_messages" value="1"{" checked" if p.get("allow_messages", 1) else ""}><span><b>Allow approved employers to message me.</b> Every message is scanned for scam signs, and you can block anyone.</span></label>
<div class="row"><a class="b sec" href="/profile/setup/2">Back</a><button class="submit-btn" type="submit">Finish</button></div></form>"""
    return _setup_page(body, "Resume and privacy", error, status)


def _employer_step(p: dict, step: int, error: str = "", status: int = 200) -> HTMLResponse:
    csrf = ui.user_csrf_input()
    bar = _steps_bar(step, 2, EMPLOYER_STEPS)
    if step == 1:
        body = f"""{bar}{ui.page_head("Tell students who you are", "A person reviews every employer before they can message students or post to the FSU feed. Clear, checkable details get approved fastest.")}
<form method="post" action="/profile/setup/1" class="card">{csrf}
<div class="form-field"><label for="e-co">Organization name</label><input id="e-co" name="company" required maxlength="120" value="{esc(p.get('company'))}" placeholder="Acme Analytics"></div>
<div class="form-field"><label for="e-web">Website</label><p class="hint">We check that it matches the email you signed up with.</p>
<input id="e-web" name="website" required maxlength="300" value="{esc(p.get('website'))}" placeholder="https://acme.com"></div>
<div class="grid2"><div class="form-field"><label for="e-ind">Industry</label><select id="e-ind" name="industry">{_opts(INDUSTRIES, p.get('industry', ''))}</select></div>
<div class="form-field"><label for="e-size">Size</label><select id="e-size" name="size">{_opts(SIZES, p.get('size', ''))}</select></div></div>
<div class="form-field"><label for="e-loc">Location</label><input id="e-loc" name="location" maxlength="120" value="{esc(p.get('location'))}" placeholder="Tallahassee, FL"></div>
<div class="form-field"><label for="e-about">About</label><p class="hint">What you do, in plain words. At least a couple of sentences.</p>
<textarea id="e-about" name="about" required maxlength="1500" data-count>{esc(p.get('about'))}</textarea></div>
<button class="submit-btn" type="submit">Continue</button></form>"""
        return _setup_page(body, "Company profile", error, status)
    body = f"""{bar}{ui.page_head("Contact and FSU connection", "Students see who they're talking to. Reviewers use your FSU connection to approve feed access.")}
<form method="post" action="/profile/setup/2" class="card">{csrf}
<div class="grid2"><div class="form-field"><label for="e-cn">Your name</label><input id="e-cn" name="contact_name" required maxlength="80" value="{esc(p.get('contact_name'))}"></div>
<div class="form-field"><label for="e-ct">Your title</label><input id="e-ct" name="contact_title" required maxlength="80" value="{esc(p.get('contact_title'))}" placeholder="Campus Recruiter"></div></div>
<div class="form-field"><label for="e-fsu">How do you work with FSU students?</label><p class="hint">Internships, part-time roles, career fair, alumni, Tallahassee office... Your feed posts must be opportunities or advice for FSU students.</p>
<textarea id="e-fsu" name="fsu_connection" required maxlength="800" data-count style="min-height:100px">{esc(p.get('fsu_connection'))}</textarea></div>
<div class="row"><a class="b sec" href="/profile/setup/1">Back</a><button class="submit-btn" type="submit">{"Save" if p.get("status") in ("pending", "approved") else "Send for review"}</button></div></form>"""
    return _setup_page(body, "Contact and FSU connection", error, status)


@router.get("/profile/setup", response_class=HTMLResponse)
def setup_start(request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        if user["role"] == "student":
            p = ensure_student(conn, user["id"])
            step = min(max(1, p["setup_step"] + 1), 3)
        else:
            p = ensure_employer(conn, user["id"])
            step = 1 if not p.get("company") else 2
    return RedirectResponse(f"/profile/setup/{step}", status_code=303)


@router.get("/profile/setup/{step}", response_class=HTMLResponse)
def setup_step(step: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        if user["role"] == "student":
            if step not in (1, 2, 3):
                return RedirectResponse("/profile/setup", status_code=303)
            return _student_step(ensure_student(conn, user["id"]), step)
        if step not in (1, 2):
            return RedirectResponse("/profile/setup", status_code=303)
        return _employer_step(ensure_employer(conn, user["id"]), step)


async def _read_upload(upload: UploadFile | None) -> tuple[str, bytes]:
    if not upload or not upload.filename:
        return "", b""
    data = await upload.read(resume_engine.MAX_UPLOAD + 1)
    return upload.filename[:120], data


@router.post("/profile/setup/{step}", response_class=HTMLResponse)
async def setup_save(step: int, request: Request):
    user = web.require_user(request)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "profile updates")
    form = await request.form()
    if not web.csrf_ok(request, form.get("csrf")):
        return RedirectResponse(f"/profile/setup/{step}", status_code=303)
    g = lambda k: str(form.get(k) or "")
    many = lambda k: [str(v) for v in form.getlist(k)][:40]
    with store.db() as conn:
        if user["role"] == "student":
            p = ensure_student(conn, user["id"])
            try:
                if step == 1:
                    name = _t(g("display_name"), 60, "Name", True)
                    if not _NAME.match(name) or "@" in name:
                        raise ProfileError("Use letters for your name (no emails or links).")
                    save_student(conn, user["id"], display_name=name, pronouns=_t(g("pronouns"), 24, "Pronouns"),
                                 major=_t(g("major"), 80, "Major", True), minor=_t(g("minor"), 80, "Minor"),
                                 degree=g("degree") if g("degree") in DEGREES else "",
                                 grad_term=g("grad_term") if g("grad_term") in TERMS else "",
                                 headline=_t(g("headline"), 120, "Headline"), bio=_t(g("bio"), 600, "About", multiline=True),
                                 setup_step=max(p["setup_step"], 1))
                    return RedirectResponse("/profile/setup/2", status_code=303)
                if step == 2:
                    skills = _pick(many("skills"), POPULAR)
                    for raw in _t(g("more_skills"), 400, "Other skills").split(","):
                        s = matching.normalize_skill(raw)
                        if s and s not in skills and not re.search(r"[<>{}]|https?:", s):
                            skills.append(s)
                    save_student(conn, user["id"], skills=skills[:30], interests=_pick(many("interests"), CATEGORIES),
                                 work_types=_pick(many("work_types"), WORK_TYPES), job_kinds=_pick(many("job_kinds"), JOB_KINDS),
                                 setup_step=max(p["setup_step"], 2))
                    return RedirectResponse("/profile/setup/3", status_code=303)
                if step == 3:
                    links = {"linkedin": _url(g("linkedin"), "LinkedIn", "linkedin.com"), "website": _url(g("website"), "Website")}
                    fields = dict(links=links, visible_to_employers=1 if g("visible") else 0,
                                  share_resume=1 if g("share_resume") else 0, allow_messages=1 if g("allow_messages") else 0,
                                  setup_step=3)
                    upload = form.get("resume")
                    fname, data = await _read_upload(upload if hasattr(upload, "read") else None)
                    paste = g("resume_paste").strip()
                    if data:
                        security.enforce_key_limit(security.upload_limiter, f"u{user['id']}", "resume uploads")
                        try:
                            fields.update(resume_text=resume_engine.extract_text(fname, data), resume_name=fname, resume_updated=time.time())
                        except resume_engine.ResumeError as e:
                            raise ProfileError(str(e))
                    elif paste:
                        if len(paste) > resume_engine.MAX_TEXT:
                            raise ProfileError("That resume text is too long (max 20,000 characters).")
                        fields.update(resume_text=resume_engine.clean(paste), resume_name="Pasted text", resume_updated=time.time())
                    if not fields.get("resume_text") and not p.get("resume_text"):
                        fields["resume_text"] = ""
                    if fields.get("resume_text") and not p.get("skills"):
                        fields["skills"] = matching.extract_skills(fields["resume_text"])[:20]
                    save_student(conn, user["id"], **fields)
                    return RedirectResponse("/profile?welcome=1", status_code=303)
            except ProfileError as e:
                merged = {**p, **{k: g(k) for k in ("display_name", "pronouns", "major", "minor", "headline", "bio") if k in form}}
                return _student_step(merged, step, str(e), 400)
            return RedirectResponse("/profile/setup", status_code=303)

        p = ensure_employer(conn, user["id"])
        try:
            if step == 1:
                website = _url(g("website"), "Website")
                if not website:
                    raise ProfileError("Website is required.")
                about = _t(g("about"), 1500, "About", True, multiline=True)
                if len(about) < 40:
                    raise ProfileError("Write at least a couple of sentences about the organization.")
                save_employer(conn, user["id"], company=_t(g("company"), 120, "Organization name", True), website=website,
                              industry=g("industry") if g("industry") in INDUSTRIES else "",
                              size=g("size") if g("size") in SIZES else "", location=_t(g("location"), 120, "Location"), about=about)
                return RedirectResponse("/profile/setup/2", status_code=303)
            if step == 2:
                if not p.get("company"):
                    return RedirectResponse("/profile/setup/1", status_code=303)
                fields = dict(contact_name=_t(g("contact_name"), 80, "Your name", True),
                              contact_title=_t(g("contact_title"), 80, "Your title", True),
                              fsu_connection=_t(g("fsu_connection"), 800, "FSU connection", True, multiline=True))
                if p.get("status") in ("draft", "rejected"):
                    fields["status"] = "pending"
                save_employer(conn, user["id"], **fields)
                return RedirectResponse("/profile?welcome=1", status_code=303)
        except ProfileError as e:
            merged = {**p, **{k: g(k) for k in form.keys() if k != "csrf"}}
            return _employer_step(merged, step, str(e), 400)
    return RedirectResponse("/profile/setup", status_code=303)


# ---------- viewing profiles ----------

def _links_html(links: dict) -> str:
    out = []
    for key, label in (("linkedin", "LinkedIn"), ("website", "Website")):
        if links.get(key):
            out.append(f'<a class="b sm ghost" href="{esc(links[key])}" target="_blank" rel="noopener noreferrer nofollow ugc">{label} ↗</a>')
    return "".join(out)


def _student_card(p: dict, *, show_links: bool, show_resume: bool, owner: bool = False) -> str:
    name = p.get("display_name") or "FSU student"
    pron = f' <span class="faint small">({esc(p["pronouns"])})</span>' if p.get("pronouns") else ""
    sub = " · ".join(esc(x) for x in (p.get("degree"), p.get("major") + (f", minor in {p['minor']}" if p.get("minor") else "") if p.get("major") else "",
                                           ("Graduating " + p["grad_term"]) if p.get("grad_term") else "") if x)
    skills = "".join(f'<span class="pill">{esc(s)}</span>' for s in (p.get("skills") or [])) or '<span class="faint small">No skills added yet.</span>'
    interests = "".join(f'<span class="chip">{esc(s)}</span> ' for s in (p.get("interests") or []))
    resume = ""
    if show_resume and p.get("resume_text"):
        resume = (f'<h3 class="sec">Resume</h3><div class="card"><div class="detail-desc" style="margin:0;font-family:var(--serif);font-size:14px">'
                  f'{esc(p["resume_text"])}</div></div>')
    return f"""<div class="card"><div class="row" style="gap:16px;align-items:flex-start">
<span class="avatar lg">{ui.initials(name)}</span><div style="flex:1;min-width:0">
<h2 style="font-family:var(--serif);font-weight:500;font-size:26px;line-height:1.2">{esc(name)}{pron}</h2>
<p class="muted">{sub or "FSU student"}</p>{f'<p style="margin-top:8px">{esc(p["headline"])}</p>' if p.get("headline") else ""}
<div class="row" style="margin-top:12px">{_links_html(p.get("links") or {}) if show_links else ""}</div></div></div>
{f'<p style="margin-top:14px;white-space:pre-wrap">{esc(p["bio"])}</p>' if p.get("bio") else ""}
<h3 class="sec" style="font-size:16px">Skills</h3><div class="skills">{skills}</div>
{f'<h3 class="sec" style="font-size:16px">Interested in</h3><div>{interests}</div>' if interests else ""}</div>{resume}"""


def _employer_card(p: dict) -> str:
    st = p.get("status", "draft")
    pill = {"approved": '<span class="pill ok">✓ Approved employer</span>', "pending": '<span class="pill warn">Waiting for review</span>',
            "rejected": '<span class="pill bad">Not approved</span>', "suspended": '<span class="pill bad">Suspended</span>',
            "draft": '<span class="pill">Profile not finished</span>'}[st]
    meta = " · ".join(esc(x) for x in (p.get("industry"), p.get("size") and f"{p['size']} people", p.get("location")) if x)
    site = (f'<a class="b sm ghost" href="{esc(p["website"])}" target="_blank" rel="noopener noreferrer nofollow">Website ↗</a>'
            if p.get("website") else "")
    return f"""<div class="card"><div class="row" style="gap:16px;align-items:flex-start">
<span class="avatar lg emp">{ui.initials(p.get("company") or "?")}</span><div style="flex:1;min-width:0">
<h2 style="font-family:var(--serif);font-weight:500;font-size:26px;line-height:1.2">{esc(p.get("company") or "Your organization")}</h2>
<p class="muted">{meta}</p><div class="row" style="margin-top:10px">{pill}{site}</div></div></div>
{f'<p style="margin-top:14px;white-space:pre-wrap">{esc(p["about"])}</p>' if p.get("about") else ""}
{f'<h3 class="sec" style="font-size:16px">Working with FSU students</h3><p style="white-space:pre-wrap">{esc(p["fsu_connection"])}</p>' if p.get("fsu_connection") else ""}
{f'<p class="small muted" style="margin-top:12px">Contact: {esc(p["contact_name"])}, {esc(p["contact_title"])}</p>' if p.get("contact_name") else ""}</div>"""


@router.get("/profile", response_class=HTMLResponse)
def my_profile(request: Request, welcome: int = 0):
    user = web.require_user(request)
    with store.db() as conn:
        if user["role"] == "student":
            p = ensure_student(conn, user["id"])
            pct, missing = student_completion(p)
            if not p.get("display_name"):
                return RedirectResponse("/profile/setup", status_code=303)
            top = ""
            if welcome:
                top = ui.banner("verified", "Your profile is set up. Try the job assistant for matches, or run your resume through the studio.")
            meter = (f'<div class="card" style="margin-bottom:12px"><div class="row between"><b>Profile {pct}% complete</b>'
                     f'<a class="b sm sec" href="/profile/setup/1">Edit profile</a></div><div class="meter" style="margin-top:10px"><i style="width:{pct}%"></i></div>'
                     + (f'<p class="small muted" style="margin-top:8px">Add {esc(", ".join(missing[:3]))} for better matches.</p>' if missing else "")
                     + "</div>")
            vis = []
            vis.append("Approved employers can find you" if p["visible_to_employers"] else "Hidden from the employer directory")
            vis.append("resume shared with them" if p["share_resume"] else "resume private")
            vis.append("messages on" if p["allow_messages"] else "messages from employers off")
            privacy = (f'<div class="card" style="margin-top:12px"><div class="row between"><div><b>Privacy</b><p class="small muted">{esc("; ".join(vis)).capitalize()}.</p></div>'
                       f'<a class="b sm sec" href="/profile/setup/3">Change</a></div></div>')
            body = top + ui.page_head("Your profile", num="Profile") + meter + _student_card(p, show_links=True, show_resume=False, owner=True) + privacy
        else:
            p = ensure_employer(conn, user["id"])
            if not p.get("company"):
                return RedirectResponse("/profile/setup", status_code=303)
            top = ""
            if welcome and p["status"] == "pending":
                top = ui.banner("info", "Thanks. A reviewer will check your organization, usually within a business day. You can post jobs meanwhile; each one is reviewed too.")
            if p["status"] == "rejected" and p.get("status_note"):
                top += ui.banner("warning", "Not approved: " + p["status_note"] + " Update your profile and send it again.")
            body = top + ui.page_head("Company profile", num="Profile") + _employer_card(p) + \
                '<div class="row" style="margin-top:12px"><a class="b sec" href="/profile/setup/1">Edit profile</a></div>'
    body += f"""<h3 class="sec">Your data</h3><div class="card"><div class="row between"><div><b>Download your data</b>
<p class="small muted">Everything we store about your account, as a JSON file.</p></div><a class="b sm sec" href="/profile/export">Download</a></div></div>
<details class="card" style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;color:var(--bad)">Delete my account</summary>
<p class="small muted" style="margin:8px 0 12px">Deletes your profile, resume versions, feed posts and comments, and blanks the messages you sent. This can't be undone.</p>
<form method="post" action="/profile/delete">{ui.user_csrf_input()}<div class="form-field"><label for="d-pw">Your password</label>
<input id="d-pw" type="password" name="password" required maxlength="128" autocomplete="current-password"></div>
<button class="b danger" type="submit">Delete my account</button></form></details>"""
    return web.page(body, "Profile", active="/profile", js=True)


def can_view_student(conn, viewer: dict, student_id: int) -> tuple[bool, bool, bool]:
    """(can see basics, can see links, can see resume)."""
    if viewer["id"] == student_id:
        return True, True, True
    p = store.student_profile(conn, student_id)
    if not p or not student_ready(p):
        return False, False, False
    if viewer["role"] == "student":
        return True, False, False
    if not store.employer_approved(conn, viewer["id"]):
        return False, False, False
    talking = conn.execute("SELECT 1 FROM conversations WHERE student_id = ? AND employer_id = ? AND blocked_by IS NULL",
                           (student_id, viewer["id"])).fetchone()
    if p["visible_to_employers"] or talking:
        return True, True, bool(p["share_resume"])
    return False, False, False


@router.get("/u/{uid}", response_class=HTMLResponse)
def student_page(uid: int, request: Request):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "profile_view")
    with store.db() as conn:
        basics, links, resume = can_view_student(conn, user, uid)
        p = store.student_profile(conn, uid) if basics else None
        if not p:
            return web.page('<p class="empty" style="margin:40px 0">That profile isn\'t available.</p>', "Profile", active="", status=404)
        msg = ""
        if user["role"] == "employer" and p["allow_messages"]:
            msg = f'<a class="b" href="/messages/new?to={uid}">{ui.icon("chat", 16)} Message</a>'
    body = f'<a class="back" href="{"/talent" if user["role"] == "employer" else "/feed"}">← Back</a>' + \
        _student_card(p, show_links=links, show_resume=resume) + (f'<div class="row" style="margin-top:12px">{msg}</div>' if msg else "")
    return web.page(body, p["display_name"] or "Profile", active="")


@router.get("/company/{uid}", response_class=HTMLResponse)
def company_page(uid: int, request: Request):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "company_view")
    with store.db() as conn:
        p = store.employer_profile(conn, uid)
        if not p or (p["status"] != "approved" and user["id"] != uid):
            return web.page('<p class="empty" style="margin:40px 0">That organization isn\'t available.</p>', "Company", active="", status=404)
        jobs = store.rows(conn, "SELECT id, title, category, work_type, location, scam_status, company FROM jobs "
                                "WHERE employer_id = ? AND review_status = 'approved' ORDER BY created_at DESC LIMIT 20", (uid,))
    cards = "".join(f'<a class="job" href="/job/{int(j["id"])}"><div class="job-title">{esc(j["title"])}</div>'
                    f'<div class="job-meta"><span class="chip">{esc(j["category"])}</span><span class="chip">{esc(j["work_type"].title())}</span></div></a>'
                    for j in jobs) or '<div class="empty">No open listings right now.</div>'
    msg = (f'<div class="row" style="margin-top:12px"><a class="b" href="/messages/new?to={uid}">{ui.icon("chat", 16)} Message {esc(p["company"])}</a></div>'
           if user["role"] == "student" and p["status"] == "approved" else "")
    body = '<a class="back" href="/jobs">← Jobs</a>' + _employer_card(p) + msg + f'<h3 class="sec">Open listings</h3>{cards}'
    return web.page(body, p["company"], active="")


@router.get("/talent", response_class=HTMLResponse)
def talent(request: Request, q: str = "", skill: str = ""):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "talent")
    q = q.strip()[:80]
    skill = skill.strip()[:40]
    with store.db() as conn:
        if not store.employer_approved(conn, user["id"]):
            body = ui.page_head("Find students", num="Talent") + ui.banner(
                "info", "The student directory opens once a reviewer approves your organization. Finish your company profile if you haven't.") + \
                '<a class="b" href="/profile">Company profile</a>'
            return web.page(body, "Find students", active="/talent")
        ps = store.rows(conn, "SELECT * FROM student_profiles WHERE visible_to_employers = 1 AND display_name != '' AND major != '' "
                              "ORDER BY updated_at DESC LIMIT 400")
    results = []
    ql = q.lower()
    for p in ps:
        p["skills"] = store.jload(p["skills"], [])
        p["interests"] = store.jload(p["interests"], [])
        hay = " ".join([p["display_name"], p["major"], p["minor"], p["headline"], p["bio"], " ".join(p["skills"]), " ".join(p["interests"])]).lower()
        if ql and not all(w in hay for w in ql.split()):
            continue
        if skill and skill not in p["skills"] and skill.lower() not in (p["resume_text"] or "").lower():
            continue
        results.append(p)
    top_skills = POPULAR[:14]
    chips = "".join(f'<a class="chipf{" active" if skill == s else ""}" href="/talent?{("q=" + esc(q) + "&") if q else ""}skill={esc(s)}">{esc(s)}</a>' for s in top_skills)
    cards = "".join(f"""<div class="card lift"><div class="row between" style="align-items:flex-start">
{web.person(p["display_name"], " · ".join(x for x in (p["major"], p["grad_term"] and "Graduating " + p["grad_term"]) if x), "stu", f"/u/{int(p['user_id'])}")}
{f'<a class="b sm" href="/messages/new?to={int(p["user_id"])}">Message</a>' if p["allow_messages"] else ""}</div>
{f'<p style="margin-top:8px">{esc(p["headline"])}</p>' if p["headline"] else ""}
<div class="skills" style="margin-top:10px">{"".join(f'<span class="pill">{esc(s)}</span>' for s in p["skills"][:8])}</div></div>""" for p in results[:60])
    body = (ui.page_head("Find students", "FSU students who chose to be visible to approved employers. Reach out about real roles only; every message is scanned.", num="Talent") +
            f'<form class="searchbar" method="get" action="/talent"><input name="q" value="{esc(q)}" placeholder="Search major, skill or interest" aria-label="Search students">'
            f'<button type="submit">Search</button></form><div class="filter-row"><span class="label">Skill</span>{chips}</div>'
            f'<div class="results-head">{web.plural(len(results), "student")}</div>{cards or "<div class=empty>No students match yet.</div>"}')
    return web.page(body, "Find students", active="/talent")


# ---------- your data ----------

@router.get("/profile/export")
def export(request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        data = {"account": store.row(conn, "SELECT id, email, role, created_at, verified_at FROM users WHERE id = ?", (user["id"],)),
                "student_profile": store.student_profile(conn, user["id"]),
                "employer_profile": store.employer_profile(conn, user["id"]),
                "resume_versions": store.rows(conn, "SELECT name, body, job_id, created_at FROM resume_versions WHERE user_id = ?", (user["id"],)),
                "messages_sent": store.rows(conn, "SELECT conversation_id, body, created_at, status FROM messages WHERE sender_id = ?", (user["id"],)),
                "feed_posts": store.rows(conn, "SELECT kind, body, link, status, created_at FROM posts WHERE author_id = ?", (user["id"],)),
                "comments": store.rows(conn, "SELECT post_id, body, created_at FROM post_comments WHERE author_id = ?", (user["id"],)),
                "job_listings": store.rows(conn, "SELECT title, company, description, review_status, created_at FROM jobs WHERE employer_id = ?", (user["id"],))}
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="nolecareershield-my-data.json"', "Cache-Control": "no-store"})


@router.post("/profile/delete", response_class=HTMLResponse)
def delete_account(request: Request, password: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.user_login_limiter, "delete_account")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/profile", status_code=303)
    with store.db() as conn:
        full = accounts.get_user_by_id(conn, user["id"])
        if not full or not accounts.verify_password(password[:accounts.PW_MAX], full["pw_hash"]):
            return web.page(ui.banner("warning", "That password isn't right, so nothing was deleted.") + '<a class="b sec" href="/profile">Back to profile</a>',
                            "Delete account", active="/profile", status=401)
        store.delete_account(conn, user["id"])
    resp = HTMLResponse(ui.shell(ui.page_head("Your account is deleted", "Your profile, resume, posts and comments are gone, and the messages you sent were blanked. Thanks for using NoleCareerShield.") +
                                 '<a class="b" href="/">Home</a>', title="Account deleted — NoleCareerShield"))
    resp.delete_cookie("usession", path="/")
    return resp


# ---------- signed-in home (bento) ----------

def dashboard(user: dict) -> str:
    from datetime import datetime
    hour = datetime.now().hour
    hello = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    with store.db() as conn:
        unread = store.unread_count(conn, user["id"])
        if user["role"] == "student":
            p = ensure_student(conn, user["id"])
            jobs = store.live_jobs(conn, security.LISTING_TTL_DAYS)
            posts = store.rows(conn, "SELECT id, kind, body FROM posts WHERE status = 'published' ORDER BY created_at DESC LIMIT 2")
        else:
            p = ensure_employer(conn, user["id"])
            mine = store.rows(conn, "SELECT review_status, COUNT(*) AS n FROM jobs WHERE employer_id = ? GROUP BY review_status", (user["id"],))
    if user["role"] == "student":
        name = (p.get("display_name") or "").split(" ")[0]
        pct, missing = student_completion(p)
        setup = ""
        if not student_ready(p):
            setup = ('<div class="tile w6 tint"><h3>Finish setting up your profile</h3><p>Two minutes. It powers your job matches, '
                     'and approved employers can find you if you choose.</p><div class="foot"><a class="b" href="/profile/setup">Set up profile</a></div></div>')
        recs = matching.rank_jobs(jobs, p, limit=3) if jobs else []
        rec_html = "".join(f'<a class="job" href="/job/{int(r["job"]["id"])}" style="margin:0 0 8px"><div class="job-top"><div>'
                           f'<div class="job-title" style="font-size:16px">{esc(r["job"]["title"])}</div><div class="job-co">{esc(r["job"]["company"])}</div></div>'
                           f'<span class="pill accent">{r["score"]}% match</span></div>'
                           + ("<div class=why>" + esc(r["reasons"][0]) + "</div>" if r["reasons"] else "") + '</a>' for r in recs) \
            or '<p>No listings yet. New ones appear here as reviewers approve them.</p>'
        resume_tile = ""
        if p.get("resume_text"):
            rv = resume_engine.review(p["resume_text"])
            resume_tile = (f'<div class="tile w3"><h3>{ui.icon("file")}Resume</h3><div class="score"><div class="ring" style="--p:{rv["score"]}"><b>{rv["score"]}</b></div>'
                           f'<p>{esc(rv["grade"])}. {esc(rv["findings"][0]["message"]) if rv["findings"] else "Looking good."}</p></div>'
                           '<div class="foot"><a class="b sm sec" href="/resume">Open resume studio</a></div></div>')
        else:
            resume_tile = (f'<div class="tile w3"><h3>{ui.icon("file")}Resume</h3><p>Upload it for a score, line-by-line fixes, and a version tailored to any job.</p>'
                           '<div class="foot"><a class="b sm sec" href="/resume">Add your resume</a></div></div>')
        feed = "".join(f'<p style="border-left:2px solid var(--line);padding-left:10px;margin-top:6px">{esc(x["body"][:120])}{"…" if len(x["body"]) > 120 else ""}</p>' for x in posts) \
            or "<p>Be the first to post a question or an opportunity.</p>"
        ai_note = "Powered by Claude" if ai.enabled() else "Built-in matching"
        return f"""<div class="page-head"><div class="num">{esc(time.strftime("%A, %B %-d"))}</div><h1>{hello}{", " + esc(name) if name else ""}.</h1>
<p>Here's what's new for you. Every listing and message is scanned for scams before you see it.</p></div>
<div class="bento">{setup}
<div class="tile w4 tall"><h3>{ui.icon("spark")}Recommended for you</h3>{rec_html}<div class="foot row"><a class="b sm" href="/assistant">Ask the job assistant</a><a class="b sm sec" href="/jobs">All jobs</a></div></div>
<div class="tile w2 goldt"><h3>{ui.icon("chat")}Messages</h3><div class="big">{unread}</div><p>unread message{"s" if unread != 1 else ""}</p><div class="foot"><a class="b sm sec" href="/messages">Open messages</a></div></div>
<div class="tile w2"><h3>{ui.icon("shield")}Scam check</h3><p>Got a DM or email about a job? Paste it and get a verdict with the evidence.</p><div class="foot"><a class="b sm sec" href="/check">Check a message</a></div></div>
{resume_tile}
<div class="tile w3"><h3>{ui.icon("user")}Profile</h3><div class="meter"><i style="width:{pct}%"></i></div><p>{pct}% complete{(". Add " + esc(missing[0])) if missing else ""}</p><div class="foot"><a class="b sm sec" href="/profile">View profile</a></div></div>
<div class="tile w6"><h3>{ui.icon("feed")}From the FSU feed</h3>{feed}<div class="foot"><a class="b sm sec" href="/feed">Open the feed</a> <span class="aimode">&nbsp; Job assistant: {ai_note}</span></div></div>
</div>"""
    counts = {r["review_status"]: r["n"] for r in mine}
    st = p.get("status", "draft")
    status_tile = {
        "draft": ('tint', "Finish your company profile", "Reviewers approve employers before they can message students or post to the FSU feed.", '<a class="b" href="/profile/setup">Finish profile</a>'),
        "pending": ('goldt', "Your organization is in review", "You can post jobs now. Messaging, the student directory and feed posts open once you're approved.", '<a class="b sm sec" href="/profile">View profile</a>'),
        "approved": ('', "You're an approved employer", "You can message students, browse the directory and post opportunities to the FSU feed.", '<a class="b sm sec" href="/talent">Find students</a>'),
        "rejected": ('tint', "Your profile wasn't approved", p.get("status_note") or "Update your details and send it again.", '<a class="b" href="/profile/setup/1">Update profile</a>'),
        "suspended": ('tint', "Your account is suspended", "Contact us if you think this is a mistake.", ""),
    }[st]
    return f"""<div class="page-head"><div class="num">Employer</div><h1>{hello}{", " + esc(p.get("company")) if p.get("company") else ""}.</h1>
<p>Post roles for FSU students, answer messages, and share opportunities on the feed.</p></div>
<div class="bento"><div class="tile w4 {status_tile[0]}"><h3>{esc(status_tile[1])}</h3><p>{esc(status_tile[2])}</p><div class="foot">{status_tile[3]}</div></div>
<div class="tile w2 goldt"><h3>{ui.icon("chat")}Messages</h3><div class="big">{unread}</div><p>unread</p><div class="foot"><a class="b sm sec" href="/messages">Open messages</a></div></div>
<div class="tile w2"><h3>{ui.icon("jobs")}Live listings</h3><div class="big">{counts.get("approved", 0)}</div><p>{counts.get("pending", 0)} waiting for review</p><div class="foot"><a class="b sm" href="/post">Post a job</a></div></div>
<div class="tile w2"><h3>{ui.icon("people")}Find students</h3><p>Search students who opted in, by skill or major.</p><div class="foot"><a class="b sm sec" href="/talent">Open directory</a></div></div>
<div class="tile w2"><h3>{ui.icon("feed")}FSU feed</h3><p>Share internships, info sessions and advice. Posts must be relevant to FSU students.</p><div class="foot"><a class="b sm sec" href="/feed">Open the feed</a></div></div></div>"""
