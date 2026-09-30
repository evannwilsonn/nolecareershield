"""
Saved replies for employers in Messages.

Each employer keeps up to 30 templates (title + body up to 2,000 characters). Four defaults are added the first time
they open templates or a composer, and they can edit or delete them (deleted defaults don't come back). Every body is
scanned with msgcheck when it's saved; scam-level content (the "block" band) is refused.

Placeholders {first_name}, {job_title} and {company} are filled from the conversation when a template is inserted.
In the composer, "Insert template" is a <details> list of links that reload the composer with the filled text
(works without JS); static/app.js inserts it in place instead when scripts run.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import msgcheck
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

MAX_TEMPLATES = 30
TITLE_MAX = 80
BODY_MAX = 2000
PLACEHOLDERS = ("first_name", "job_title", "company")

DEFAULTS = [
    ("Thanks for applying",
     "Hi {first_name},\n\nThanks for applying to the {job_title} role at {company}. We're reviewing applications now and "
     "will get back to you within a week about next steps.\n\nThanks again for your interest!"),
    ("Next steps",
     "Hi {first_name},\n\nThanks again for your interest in {job_title}. The next step is a short interview with our team. "
     "I'll send a few times here in Messages; pick whichever works best for you. If none of them fit, just let me know."),
    ("Not moving forward",
     "Hi {first_name},\n\nThank you for applying for {job_title} at {company}, and for the time you put into it. After careful "
     "review, we've decided not to move forward with your application for this role. It was a hard decision, and it isn't a "
     "reflection of your potential.\n\nWe'd be glad to see you apply for future openings. Best of luck in your search."),
    ("Interview confirmation",
     "Hi {first_name},\n\nYour interview for {job_title} at {company} is confirmed. The time and details are in this "
     "conversation, and you can add it to your calendar from there. Let me know here if anything changes. Looking forward to talking!"),
]


def ensure_defaults(conn, employer_id: int) -> None:
    if conn.execute("SELECT 1 FROM template_seeds WHERE employer_id = ?", (employer_id,)).fetchone():
        return
    conn.execute("INSERT OR IGNORE INTO template_seeds (employer_id) VALUES (?)", (employer_id,))
    now = time.time()
    for i, (title, body) in enumerate(DEFAULTS):
        conn.execute("INSERT INTO message_templates (employer_id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (employer_id, title, body, now + i * 1e-3, now + i * 1e-3))


def templates_for(conn, employer_id: int) -> list[dict]:
    ensure_defaults(conn, employer_id)
    return store.rows(conn, "SELECT * FROM message_templates WHERE employer_id = ? ORDER BY id LIMIT ?", (employer_id, MAX_TEMPLATES))


def fill(body: str, first_name: str = "", job_title: str = "", company: str = "") -> str:
    vals = {"first_name": first_name or "there", "job_title": job_title or "this role", "company": company or "our team"}
    out = body
    for k in PLACEHOLDERS:
        out = out.replace("{" + k + "}", vals[k])
    return out


def context(conn, employer_id: int, student_id: int, job_title: str = "") -> dict:
    sp = store.student_profile(conn, student_id) or {}
    ep = store.employer_profile(conn, employer_id) or {}
    first = (sp.get("display_name") or "").split()
    return {"first_name": first[0] if first else "", "job_title": job_title, "company": ep.get("company") or ""}


def filled(conn, tpl: dict, employer_id: int, student_id: int, job_title: str = "") -> str:
    return fill(tpl["body"], **context(conn, employer_id, student_id, job_title))


def get(conn, employer_id: int, tid: int) -> dict | None:
    return store.row(conn, "SELECT * FROM message_templates WHERE id = ? AND employer_id = ?", (tid, employer_id))


def picker(conn, user: dict, student_id: int, job_title: str, href, textarea_id: str) -> str:
    """The composer's "Insert template" control. `href(tid)` gives the no-JS link that reloads the composer prefilled."""
    if user["role"] != "employer":
        return ""
    tpls = templates_for(conn, store.org_id(user))
    ctx = context(conn, store.org_id(user), student_id, job_title)
    items = "".join(f'<li><a href="{esc(href(t["id"]))}" data-tpl-fill="{esc(fill(t["body"], **ctx))}" data-tpl-for="{esc(textarea_id)}">'
                    f'<b>{esc(t["title"])}</b><span>{esc(fill(t["body"], **ctx).replace(chr(10), " ")[:90])}</span></a></li>' for t in tpls)
    if not items:
        items = '<li class="tpl-empty">No templates yet.</li>'
    return (f'<details class="tpl-pick"><summary>{ui.icon("file", 14)} Insert template</summary>'
            f'<ul class="tpl-list">{items}</ul><a class="tpl-manage" href="/messages/templates">Manage templates →</a></details>')


def validate(title: str, body: str) -> tuple[str, str, str]:
    title = " ".join(security._CONTROL_CHARS_RE.sub("", title or "").split())[:TITLE_MAX + 1]
    body = security._CONTROL_CHARS_RE.sub("", (body or "").replace("\r\n", "\n")).strip()
    if not title:
        return title, body, "Give the template a title."
    if len(title) > TITLE_MAX:
        return title, body, f"Titles can be up to {TITLE_MAX} characters."
    if not body:
        return title, body, "Write the template text."
    if len(body) > BODY_MAX:
        return title, body, f"Templates can be up to {BODY_MAX:,} characters."
    if msgcheck.check(fill(body))["band"] == "block":
        return title, body, ("That text matches scam patterns (for example asking for money, bank details, check deposits or a chat on "
                             "another app), so it can't be saved.")
    return title, body, ""


# ---------- pages ----------

def _page(conn, user: dict, error: str = "", draft: dict | None = None, edit_err: tuple[int, str] | None = None,
          done: str = "", status: int = 200) -> HTMLResponse:
    tpls = templates_for(conn, store.org_id(user))
    csrf = ui.user_csrf_input()
    draft = draft or {}
    cards = []
    for t in tpls:
        err = ui.banner("warning", edit_err[1]) if edit_err and edit_err[0] == t["id"] else ""
        cards.append(
            f'<article class="tpl-card" id="t{int(t["id"])}"><details{" open" if err else ""}><summary><span class="tpl-t">{esc(t["title"])}</span>'
            f'<span class="tpl-b">{esc(t["body"].replace(chr(10), " ")[:140])}</span><span class="tpl-edit">Edit</span></summary>{err}'
            f'<form method="post" action="/messages/templates/{int(t["id"])}">{csrf}'
            f'<div class="form-field"><label for="tt{int(t["id"])}">Title</label><input id="tt{int(t["id"])}" name="title" maxlength="{TITLE_MAX}" required value="{esc(t["title"])}"></div>'
            f'<div class="form-field"><label for="tb{int(t["id"])}">Text</label><textarea id="tb{int(t["id"])}" name="body" maxlength="{BODY_MAX}" required rows="6" data-count>{esc(t["body"])}</textarea></div>'
            f'<div class="row"><button class="b sm" type="submit">Save</button></div></form>'
            f'<form method="post" action="/messages/templates/{int(t["id"])}/delete" class="tpl-del">{csrf}<button class="b sm ghost" type="submit">Delete</button></form>'
            '</details></article>')
    full = len(tpls) >= MAX_TEMPLATES
    new = ("" if full else
           f'<form class="card tpl-new" method="post" action="/messages/templates">{csrf}<h2>New template</h2>'
           + (ui.banner("warning", error) if error else "") +
           f'<div class="form-field"><label for="nt-title">Title</label><input id="nt-title" name="title" maxlength="{TITLE_MAX}" required value="{esc(draft.get("title", ""))}" placeholder="Following up"></div>'
           f'<div class="form-field"><label for="nt-body">Text</label><textarea id="nt-body" name="body" maxlength="{BODY_MAX}" required rows="6" data-count placeholder="Hi {{first_name}}, …">{esc(draft.get("body", ""))}</textarea></div>'
           '<button class="b" type="submit">Save template</button></form>')
    note = ui.banner("verified", done) if done else ""
    if full:
        note += ui.banner("warning", error) if error else ""
    body = ('<a class="back" href="/messages">← Messages</a>' +
            ui.page_head("Message templates", "Saved replies you can drop into any conversation. "
                         "<code>{first_name}</code>, <code>{job_title}</code> and <code>{company}</code> are filled in when you insert one.", num="Messages") +
            note + f'<p class="small muted tpl-count">{len(tpls)} of {MAX_TEMPLATES} templates. Every template is scanned for scam patterns when you save it.</p>'
            f'<div class="tpl-grid"><div class="tpl-cards">{"".join(cards) or "<p class=muted>No templates. Add one.</p>"}</div>{new}</div>')
    return web.page(body, "Message templates", active="/messages", js=True, status=status)


def _employer(request: Request) -> dict:
    return web.require_user(request, "employer")


@router.get("/messages/templates", response_class=HTMLResponse)
def templates_page(request: Request, done: str = ""):
    user = _employer(request)
    msgs = {"saved": "Template saved.", "deleted": "Template deleted.", "added": "Template added."}
    with store.db() as conn:
        return _page(conn, user, done=msgs.get(done, ""))


@router.post("/messages/templates", response_class=HTMLResponse)
def create(request: Request, title: str = Form(""), body: str = Form(""), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/messages/templates", status_code=303)
    security.enforce_key_limit(security.message_limiter, f"u{user['id']}", "saving templates")
    title, body, err = validate(title, body)
    with store.db() as conn:
        ensure_defaults(conn, store.org_id(user))
        n = conn.execute("SELECT COUNT(*) FROM message_templates WHERE employer_id = ?", (store.org_id(user),)).fetchone()[0]
        if not err and n >= MAX_TEMPLATES:
            err = f"You can keep up to {MAX_TEMPLATES} templates. Delete one to add another."
        if err:
            return _page(conn, user, error=err, draft={"title": title, "body": body[:BODY_MAX]}, status=400)
        now = time.time()
        cur = conn.execute("INSERT INTO message_templates (employer_id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
                           (store.org_id(user), title, body, now, now))
    return RedirectResponse(f"/messages/templates?done=added#t{cur.lastrowid}", status_code=303)


@router.post("/messages/templates/{tid}", response_class=HTMLResponse)
def save(tid: int, request: Request, title: str = Form(""), body: str = Form(""), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/messages/templates", status_code=303)
    security.enforce_key_limit(security.message_limiter, f"u{user['id']}", "saving templates")
    title, body, err = validate(title, body)
    with store.db() as conn:
        if not get(conn, store.org_id(user), tid):
            return RedirectResponse("/messages/templates", status_code=303)
        if err:
            return _page(conn, user, edit_err=(tid, err), status=400)
        conn.execute("UPDATE message_templates SET title = ?, body = ?, updated_at = ? WHERE id = ? AND employer_id = ?",
                     (title, body, time.time(), tid, store.org_id(user)))
    return RedirectResponse(f"/messages/templates?done=saved#t{int(tid)}", status_code=303)


@router.post("/messages/templates/{tid}/delete")
def delete(tid: int, request: Request, csrf: str = Form("")):
    user = _employer(request)
    if web.csrf_ok(request, csrf):
        with store.db() as conn:
            conn.execute("DELETE FROM message_templates WHERE id = ? AND employer_id = ?", (tid, store.org_id(user)))
    return RedirectResponse("/messages/templates?done=deleted", status_code=303)


def new_message_href(to: int, job: int):
    return lambda tid: "/messages/new?" + urlencode({"to": to, "job": job, "tpl": tid}) if job else "/messages/new?" + urlencode({"to": to, "tpl": tid})
