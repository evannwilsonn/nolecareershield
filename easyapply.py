"""
Quick apply: an employer can choose, per listing, to collect applications here instead of sending students to an
outside link. They write up to five questions; a student fills the form from their profile, and the application
lands in the employer's candidate tracker with the answers attached.

What the employer sees is spelled out to the student on the form: name, major, links, the answers, and the
resume only if the student ticks it. Questions can't ask for anything a scammer would want (SSN, bank or card
details, passwords), and the question text goes through the same scam scan as the listing.
"""

from __future__ import annotations

import json
import re
import time

from fastapi import Depends, APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import hiring
import profiles
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

MAX_QUESTIONS = 5
Q_LEN = 160
ANSWER_LEN = {"short": 300, "long": 1500, "yesno": 3}
NOTE_LEN = 1000
DAILY_CAP = 40            # applications one student can send per day
KINDS = [("short", "Short answer"), ("long", "Long answer"), ("yesno", "Yes / no")]
KIND_NAME = dict(KINDS)

# Things a real employer never needs to ask for on an application form.
_BANNED = re.compile(r"\b(ssn|social\s+security|routing\s+number|account\s+number|bank\s+(?:account|details|login)|credit\s+card|debit\s+card|"
                     r"card\s+number|cvv|password|passcode|passport|driver'?s?\s+licen[cs]e|gift\s+card|wire\s+transfer|cash\s?app|zelle|venmo|crypto)\b", re.I)


class QuestionError(ValueError):
    pass


def clean_questions(raw) -> list[dict]:
    """A list of {"q", "kind", "required"} from form fields or a saved draft. Blank questions are dropped."""
    out = []
    for item in (raw or [])[:MAX_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        q = security._CONTROL_CHARS_RE.sub("", str(item.get("q", ""))).strip()
        if not q:
            continue
        if len(q) > Q_LEN:
            raise QuestionError(f"Keep each quick apply question under {Q_LEN} characters.")
        if _BANNED.search(q):
            raise QuestionError("Quick apply questions can't ask for SSNs, bank or card details, passwords or ID numbers. "
                                "Real employers collect those only after a hire, through their own paperwork.")
        kind = item.get("kind") if item.get("kind") in KIND_NAME else "short"
        out.append({"q": q, "kind": kind, "required": bool(item.get("required"))})
    return out


def questions_of(job: dict) -> list[dict]:
    return store.jload(job.get("questions"), [])


def is_easy(job: dict) -> bool:
    return bool(job.get("easy_apply"))


def questions_text(questions: list[dict]) -> str:
    """Appended to the description the scam scanner reads, so a question can't hide what the description doesn't say."""
    return "\n".join(q["q"] for q in questions)


# ---------- queries ----------

def application(conn, job_id: int, student_id: int) -> dict | None:
    a = store.row(conn, "SELECT * FROM applications WHERE job_id = ? AND student_id = ?", (job_id, student_id))
    if a:
        a["answers"] = store.jload(a["answers"], [])
    return a


def applications_for(conn, job_id: int) -> dict[int, dict]:
    out = {}
    for a in store.rows(conn, "SELECT * FROM applications WHERE job_id = ?", (job_id,)):
        a["answers"] = store.jload(a["answers"], [])
        out[a["student_id"]] = a
    return out


def can_apply(conn, job: dict) -> bool:
    return (is_easy(job) and store.visible_listing(job) and bool(job.get("employer_id"))
            and store.employer_approved(conn, job["employer_id"]))


# ---------- employer side ----------

def application_html(a: dict, p: dict) -> str:
    """The application as the employer sees it, inside a candidate card."""
    rows = "".join(f'<div class="qa"><div class="q">{esc(x["q"])}</div><div class="a">{esc(x["a"]) or "<span class=faint>No answer</span>"}</div></div>'
                   for x in a["answers"])
    note = f'<div class="qa"><div class="q">Note to you</div><div class="a">{esc(a["note"])}</div></div>' if a["note"] else ""
    resume = ""
    if a["share_resume"] and p.get("resume_text"):
        resume = f'<div class="qa"><div class="q">Resume</div><div class="a resume">{esc(p["resume_text"])}</div></div>'
    elif not a["share_resume"]:
        resume = '<p class="small faint" style="margin-top:6px">The student chose not to include a resume.</p>'
    n = len(a["answers"]) + (1 if a["note"] else 0)
    body = (rows + note + resume) or '<p class="small faint">No questions on this listing.</p>'
    return (f'<details class="appl"><summary><b>Application</b> <span class="faint">· sent {esc(web.ago(a["created_at"]))}'
            f'{f" · {n} answer" + ("s" if n != 1 else "") if n else ""}</span></summary>{body}</details>')


# ---------- student side ----------

def _job_or_none(conn, job_id: int) -> dict | None:
    return store.row(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))


def _unavailable(msg: str = "That listing isn't taking applications here.") -> HTMLResponse:
    return web.page(ui.page_head("Quick apply") + f'<div class="empty">{esc(msg)} <a href="/jobs">Back to jobs</a></div>', "Quick apply", active="/jobs", status=404)


def _field(i: int, q: dict, value: str = "") -> str:
    req = " required" if q["required"] else ""
    label = f'{esc(q["q"])}{"" if q["required"] else " <span class=faint>(optional)</span>"}'
    fid = f"a{i}"
    if q["kind"] == "yesno":
        opts = "".join(f'<label class="pick"><input type="radio" name="{fid}" value="{v}"{req}{" checked" if value == v else ""}> {v}</label>' for v in ("Yes", "No"))
        return f'<fieldset class="form-field"><legend>{label}</legend><div class="row">{opts}</div></fieldset>'
    if q["kind"] == "long":
        return f'<div class="form-field"><label for="{fid}">{label}</label><textarea id="{fid}" name="{fid}" maxlength="{ANSWER_LEN["long"]}"{req}>{esc(value)}</textarea></div>'
    return f'<div class="form-field"><label for="{fid}">{label}</label><input id="{fid}" name="{fid}" maxlength="{ANSWER_LEN["short"]}"{req} value="{esc(value)}"></div>'


def _form_page(job: dict, p: dict, values: dict | None = None, error: str = "", status: int = 200) -> HTMLResponse:
    v = values or {}
    qs = questions_of(job)
    fields = "".join(_field(i, q, v.get(f"a{i}", "")) for i, q in enumerate(qs))
    sub = " · ".join(x for x in (p.get("major"), p.get("grad_term") and "Graduating " + p["grad_term"]) if x)
    has_resume = bool(p.get("resume_text"))
    resume = ('<label class="toggle"><input type="checkbox" name="share_resume" value="1"' + (" checked" if v.get("share_resume", "1") == "1" or not values else "") +
              '><span><b>Include my resume.</b> The employer sees the resume saved on your profile.</span></label>'
              if has_resume else '<p class="small faint">You haven\'t added a resume yet, so none will be sent. <a href="/resume">Resume studio</a></p>')
    err = ui.banner("warning", error) if error else ""
    body = (f'<a class="back" href="/job/{int(job["id"])}">← {esc(job["title"])}</a>'
            + ui.page_head("Quick apply", f'{esc(job["title"])} at {esc(job["company"])}. Your profile fills in the basics; answer the questions and send.', num="Apply")
            + '<p class="qa-note">Quick apply makes job applications short and sweet. However, experts recommend applying directly on company websites.</p>'
            + err
            + f'<form method="post" action="/job/{int(job["id"])}/easy" class="card easy">{ui.user_csrf_input()}'
              f'<div class="row" style="gap:12px;align-items:center;margin-bottom:14px">{web.person(p["display_name"], sub, "stu")}</div>'
              f'{fields}'
              f'<div class="form-field"><label for="a-note">Note to the employer <span class="faint">(optional)</span></label>'
              f'<textarea id="a-note" name="note" maxlength="{NOTE_LEN}" placeholder="Anything you want them to know">{esc(v.get("note", ""))}</textarea></div>'
              f'{resume}'
              f'<p class="small muted" style="margin:14px 0">The employer will see your name, major, graduation term, profile links, these answers and the resume if ticked. '
              'Nothing else from your account, and never your email. You can withdraw the application any time.</p>'
              f'<button class="b" type="submit">{ui.icon("send", 16)} Send application</button> <a class="b ghost" href="/job/{int(job["id"])}">Cancel</a></form>')
    return web.page(body, "Quick apply", active="/jobs", status=status)


def _gate(request: Request, job_id: int):
    """(user, job, profile) or a response to send instead."""
    user = web.require_user(request, "student")
    with store.db() as conn:
        job = _job_or_none(conn, job_id)
        if not job or not can_apply(conn, job):
            return _unavailable()
        p = store.student_profile(conn, user["id"])
        done = application(conn, job_id, user["id"])
    if not p or not profiles.student_ready(p):
        return RedirectResponse("/profile/setup", status_code=303)
    if done:
        return RedirectResponse("/applications?already=1", status_code=303)
    return user, job, p


@router.get("/job/{job_id}/easy", response_class=HTMLResponse)
def easy_form(job_id: int, request: Request):
    security.enforce_rate_limit(request, security.general_limiter, "easy_form")
    g = _gate(request, job_id)
    if not isinstance(g, tuple):
        return g
    _, job, p = g
    return _form_page(job, p)


@router.post("/job/{job_id}/easy", response_class=HTMLResponse)
def easy_send(job_id: int, request: Request, form=Depends(web.form_data)):      # question fields are dynamic (a0, a1, ...)
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, str(form.get("csrf", ""))):
        return RedirectResponse(f"/job/{job_id}/easy", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "applications")
    g = _gate(request, job_id)
    if not isinstance(g, tuple):
        return g
    _, job, p = g
    qs = questions_of(job)
    typed = {f"a{i}": str(form.get(f"a{i}", "")) for i in range(len(qs))}
    typed["note"] = str(form.get("note", ""))
    typed["share_resume"] = "1" if form.get("share_resume") else "0"
    answers, error = [], ""
    for i, q in enumerate(qs):
        a = security._CONTROL_CHARS_RE.sub("", typed[f"a{i}"].replace("\r\n", "\n")).strip()
        if q["kind"] == "yesno" and a not in ("", "Yes", "No"):
            a = ""
        if q["required"] and not a:
            error = "Answer the required questions first. Your other answers are still here."
        if len(a) > ANSWER_LEN[q["kind"]]:
            error = f"One answer is too long (up to {ANSWER_LEN[q['kind']]:,} characters)."
        answers.append({"q": q["q"], "a": a})
    note = security._CONTROL_CHARS_RE.sub("", typed["note"].replace("\r\n", "\n")).strip()
    if len(note) > NOTE_LEN:
        error = f"The note can be up to {NOTE_LEN:,} characters."
    if error:
        return _form_page(job, p, typed, error, status=400)
    now = time.time()
    with store.db() as conn:
        sent_today = conn.execute("SELECT COUNT(*) FROM applications WHERE student_id = ? AND created_at > ?", (user["id"], now - 86400)).fetchone()[0]
        if sent_today >= DAILY_CAP:
            return _form_page(job, p, typed, "That's a lot of applications for one day. Try again tomorrow.", status=429)
        share = 1 if (typed["share_resume"] == "1" and p.get("resume_text")) else 0
        conn.execute("INSERT OR IGNORE INTO applications (job_id, student_id, employer_id, answers, note, share_resume, created_at) VALUES (?,?,?,?,?,?,?)",
                     (job_id, user["id"], job["employer_id"], json.dumps(answers), note, share, now))
        hiring.add_candidate(conn, job_id, user["id"], job["employer_id"], "applied")
        hiring.record_apply_click(conn, job_id, user["id"])
    return RedirectResponse(f"/applications?sent={job_id}", status_code=303)


@router.get("/applications", response_class=HTMLResponse)
def my_applications(request: Request, sent: int = 0, already: int = 0, withdrawn: int = 0):
    user = web.require_user(request, "student")
    security.enforce_rate_limit(request, security.general_limiter, "applications")
    with store.db() as conn:
        apps = store.rows(conn, "SELECT a.*, j.title, j.company, j.review_status, j.listing_status, j.expires_at, j.created_at AS job_created "
                                "FROM applications a JOIN jobs j ON j.id = a.job_id "
                                "WHERE a.student_id = ? ORDER BY a.created_at DESC LIMIT 100", (user["id"],))
    note = ""
    if sent:
        note = ui.banner("verified", "Application sent. The employer sees it in their candidate tracker.")
    elif already:
        note = ui.banner("info", "You already applied to that listing.")
    elif withdrawn:
        note = ui.banner("info", "Application withdrawn.")
    head = ui.page_head("Your applications", "Everything you sent with quick apply. Employers see it only while it's here.", num="Apply")
    if not apps:
        return web.page(head + note + '<div class="empty">No applications yet. Listings with a <b>Quick apply</b> button let you apply without leaving the site. <a href="/jobs">Browse jobs</a></div>',
                        "Applications", active="/applications")
    csrf = ui.user_csrf_input()
    cards = "".join(
        f'<div class="card app"><div class="row between" style="align-items:flex-start;gap:12px"><div style="min-width:0">'
        f'<a class="job-title" href="/job/{int(a["job_id"])}">{esc(a["title"])}</a><div class="job-co">{esc(a["company"])} · sent {esc(web.ago(a["created_at"]))}</div>'
        f'{_closed_note(a)}</div>'
        f'<form method="post" action="/applications/{int(a["job_id"])}/withdraw" class="navform">{csrf}<button class="b sm ghost" type="submit">Withdraw</button></form></div></div>'
        for a in apps)
    return web.page(head + note + cards, "Applications", active="/applications")


_CLOSED_NOTES = {"closed": "Closed: the employer closed this listing. Your application stays with them unless you withdraw it.",
                 "paused": "Paused: the employer paused this listing for now. Your application stays with them.",
                 "expired": "Expired: this listing is no longer on the board. Your application stays with the employer.",
                 "removed": "Removed: this listing was taken down.", "pending": "Being re-reviewed: the employer edited this listing."}


def _closed_note(a: dict) -> str:
    """A short note on an application whose listing isn't live any more (the listing's own state, never the employer's stage)."""
    state = store.listing_state(dict(a, created_at=a.get("job_created")))
    note = _CLOSED_NOTES.get(state)
    if not note:
        return ""
    label, text = note.split(": ", 1)
    return f'<p class="small appnote"><span class="pill{" bad" if state in ("closed", "removed") else " warn"}">{esc(label)}</span> {esc(text)}</p>'


@router.post("/applications/{job_id}/withdraw")
def withdraw(job_id: int, request: Request, csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/applications", status_code=303)
    with store.db() as conn:
        conn.execute("DELETE FROM applications WHERE job_id = ? AND student_id = ?", (job_id, user["id"]))
        # Still untouched in the employer's tracker? Then it goes too. If they've moved it, the row stays as their own record.
        conn.execute("DELETE FROM candidates WHERE job_id = ? AND student_id = ? AND source = 'applied' AND stage = 'new'", (job_id, user["id"]))
    return RedirectResponse("/applications?withdrawn=1", status_code=303)
