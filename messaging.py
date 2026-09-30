"""
Messaging between FSU students and approved employers.

Who can start a conversation:
  * A student can message any approved employer (from a listing, a company page or a feed post).
  * An approved employer can message a student who allows employer messages AND either chose to
    be visible in the directory or already has a conversation with them.
  * No student-to-student or employer-to-employer messages, and unapproved or suspended employers
    can't send anything.

Every message is scanned by the same scam detector as the scam checker, the moment it's sent:
  * "Scam" band (block): held for a reviewer and not delivered.
  * "Likely a scam" band (review): delivered with a warning and the evidence, shown to the reader.
  * Links are never clickable in messages, so a bad link can't be opened by accident.
Either side can block or report. Email notifications say only that a message is waiting, never
what it says, so they can't be used to phish.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import mailer
import msgcheck
import profiles
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

MAX_BODY = 4000
NOTIFY_EVERY = 6 * 3600


# ---------- rules ----------

def _role(conn, uid: int) -> str | None:
    r = conn.execute("SELECT role FROM users WHERE id = ? AND verified = 1", (uid,)).fetchone()
    return r[0] if r else None


def can_start(conn, sender: dict, to_id: int) -> tuple[bool, str]:
    to_role = _role(conn, to_id)
    if not to_role or to_id == sender["id"]:
        return False, "That account isn't available."
    if sender["role"] == to_role:
        return False, "Messages are between students and employers."
    if sender["role"] == "student":
        if not store.employer_approved(conn, to_id):
            return False, "That employer hasn't been approved yet, so it can't receive messages."
        return True, ""
    if not store.employer_approved(conn, sender["id"]):
        return False, "Messaging opens once a reviewer approves your organization."
    p = store.student_profile(conn, to_id)
    if not p or not profiles.student_ready(p) or not p["allow_messages"]:
        return False, "That student isn't accepting messages from employers."
    talking = conn.execute("SELECT 1 FROM conversations WHERE student_id = ? AND employer_id = ?", (to_id, sender["id"])).fetchone()
    if not (p["visible_to_employers"] or talking):
        return False, "That student isn't accepting messages from employers."
    return True, ""


def get_convo(conn, cid: int, user: dict) -> dict | None:
    c = store.row(conn, "SELECT * FROM conversations WHERE id = ?", (cid,))
    if not c or user["id"] not in (c["student_id"], c["employer_id"]):
        return None
    return c


def can_send(conn, c: dict, user: dict) -> tuple[bool, str]:
    if c["blocked_by"]:
        return False, "This conversation is closed." if c["blocked_by"] != user["id"] else "You blocked this conversation. Unblock it to reply."
    if user["role"] == "employer" and not store.employer_approved(conn, user["id"]):
        return False, "Your organization isn't approved to send messages right now."
    other = c["employer_id"] if user["id"] == c["student_id"] else c["student_id"]
    if not _role(conn, other):
        return False, "The other account no longer exists."
    return True, ""


def add_message(conn, c: dict, sender: dict, body: str) -> dict:
    r = msgcheck.check(body)
    band = r["band"]
    status = "held" if band == "block" else "delivered"
    findings = [{"title": f["title"], "why": f["why"], "severity": f["severity"]} for f in r["findings"][:5]]
    now = time.time()
    cur = conn.execute("INSERT INTO messages (conversation_id, sender_id, body, created_at, scan_band, scan_score, scan_json, status) "
                       "VALUES (?,?,?,?,?,?,?,?)", (c["id"], sender["id"], body, now, band, r["score"], json.dumps(findings), status))
    conn.execute("UPDATE conversations SET last_at = ?, student_hidden = 0, employer_hidden = 0 WHERE id = ?", (now, c["id"]))
    return {"id": cur.lastrowid, "status": status, "band": band}


def clean_body(body: str) -> str:
    body = security._CONTROL_CHARS_RE.sub("", (body or "").replace("\r\n", "\n")).strip()
    if not body:
        raise ValueError("Write a message first.")
    if len(body) > MAX_BODY:
        raise ValueError(f"Messages can be up to {MAX_BODY:,} characters.")
    return body


def _notify(background: BackgroundTasks, conn, c: dict, sender: dict) -> None:
    to = c["employer_id"] if sender["id"] == c["student_id"] else c["student_id"]
    last = conn.execute("SELECT sent_at FROM notify_log WHERE user_id = ? AND conversation_id = ?", (to, c["id"])).fetchone()
    if last and time.time() - last[0] < NOTIFY_EVERY:
        return
    user = conn.execute("SELECT email FROM users WHERE id = ?", (to,)).fetchone()
    if not user:
        return
    conn.execute("INSERT OR REPLACE INTO notify_log (user_id, conversation_id, sent_at) VALUES (?,?,?)", (to, c["id"], time.time()))
    name = web.display_name(conn, sender["id"], sender["role"])[0]
    background.add_task(mailer.send, user[0], "You have a new message on NoleCareerShield",
                        f"{name} sent you a message on NoleCareerShield.\n\nRead it on the site: {security.BASE_URL}/messages/{c['id']}\n\n"
                        "We never put message text in emails. If an email claiming to be from us asks you to reply with personal "
                        "details or click a different link, it isn't from us.")


# ---------- rendering ----------

def _thread_list(conn, user: dict, active: int = 0) -> str:
    side = "student" if user["role"] == "student" else "employer"
    other = "employer_id" if side == "student" else "student_id"
    convos = store.rows(conn, f"""SELECT c.*, (SELECT body FROM messages WHERE conversation_id = c.id AND (status = 'delivered' OR sender_id = ?)
                                   ORDER BY id DESC LIMIT 1) AS last_body,
                                  (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND sender_id != ? AND read_at IS NULL AND status = 'delivered') AS unread
                                  FROM conversations c WHERE c.{side}_id = ? AND c.{side}_hidden = 0 ORDER BY c.last_at DESC LIMIT 100""",
                        (user["id"], user["id"], user["id"]))
    if not convos:
        hint = ("Message an employer from a job listing or company page." if side == "student"
                else "Message students from the directory, or reply when a student writes to you.")
        return f'<div style="padding:20px" class="muted small">No conversations yet. {hint}</div>'
    out = []
    for c in convos:
        name, sub, kind = web.display_name(conn, c[other])
        dot = '<span class="dot" aria-label="unread"></span>' if c["unread"] and not c["blocked_by"] else ""
        last = (c["last_body"] or "").replace("\n", " ")[:80] or "(no messages)"
        out.append(f'<a href="/messages/{int(c["id"])}"{" class=on" if c["id"] == active else ""}><div class="t1"><span>{esc(name)}</span>'
                   f'<span class="faint small" style="font-weight:400">{esc(web.ago(c["last_at"]))}{dot}</span></div>'
                   f'<div class="t2">{esc(c["subject"]) + " · " if c["subject"] else ""}{esc(last)}</div></a>')
    return "".join(out)


def message_json(m: dict, me: int) -> dict:
    mine = m["sender_id"] == me
    flag = None
    if not mine and m["scan_band"] in ("review", "caution") and m["status"] == "delivered":
        flag = {"level": "bad" if m["scan_band"] == "review" else "warn",
                "items": [f["title"] for f in store.jload(m["scan_json"], [])][:4]}
    body = m["body"]
    if m["status"] == "removed":
        body = ""
    return {"id": m["id"], "mine": mine, "body": body, "at": web.ago(m["created_at"]), "status": m["status"], "flag": flag}


def _bubble(mj: dict) -> str:
    if mj["status"] == "removed":
        return f'<div class="bubble {"me" if mj["mine"] else "them"}" style="opacity:.6"><i>Message removed</i></div>'
    pre = ""
    if mj["flag"]:
        items = "".join(f"<li>{esc(t)}</li>" for t in mj["flag"]["items"])
        head = ("⚠ Our scanner found scam signals in this message." if mj["flag"]["level"] == "bad"
                else "Heads up: a couple of things in this message are worth checking.")
        pre = (f'<div class="scanbox{" bad" if mj["flag"]["level"] == "bad" else ""}" data-mid="{mj["id"]}"><b>{head}</b><ul>{items}</ul>'
               f'<a href="/check?m={mj["id"]}">See the full check →</a></div>')
    held = '<span class="meta">Held for a safety review. A reviewer checks it before it\'s delivered.</span>' if mj["status"] == "held" else ""
    return (f'{pre}<div class="bubble {"me" if mj["mine"] else "them"}{" flag" if mj["flag"] else ""}" data-id="{mj["id"]}">'
            f'{esc(mj["body"])}<span class="meta">{esc(mj["at"])}</span>{held}</div>')


def _inbox_page(conn, user: dict, c: dict | None = None, error: str = "", draft: str = "", status: int = 200) -> HTMLResponse:
    threads = _thread_list(conn, user, c["id"] if c else 0)
    if not c:
        right = ('<div class="convo" style="justify-content:center;align-items:center;padding:40px;text-align:center">'
                 f'<div>{ui.icon("chat", 34)}<p class="muted" style="margin-top:10px">Pick a conversation.</p>'
                 '<p class="small faint" style="margin-top:6px">Every message is scanned for scam signs. Links in messages are never clickable.</p></div></div>')
        body = ui.page_head("Messages", num="Inbox") + f'<div class="inbox">{f"<div class=threads>{threads}</div>"}{right}</div>'
        return web.page(body, "Messages", active="/messages", js=True, status=status)
    other = c["employer_id"] if user["id"] == c["student_id"] else c["student_id"]
    name, sub, kind = web.display_name(conn, other)
    href = f"/company/{other}" if kind == "emp" else f"/u/{other}"
    msgs = store.rows(conn, "SELECT * FROM messages WHERE conversation_id = ? AND (status != 'held' OR sender_id = ?) ORDER BY id LIMIT 500",
                      (c["id"], user["id"]))
    conn.execute("UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL AND status = 'delivered'",
                 (time.time(), c["id"], user["id"]))
    bubbles = "".join(_bubble(message_json(m, user["id"])) for m in msgs) or '<p class="faint small" style="text-align:center">No messages yet.</p>'
    ok, why = can_send(conn, c, user)
    csrf = ui.user_csrf_input()
    last_id = msgs[-1]["id"] if msgs else 0
    err = f'<div class="banner warning" style="margin:10px 12px 0">{esc(error)}</div>' if error else ""
    if ok:
        composer = (f'{err}<form class="composer" method="post" action="/messages/{int(c["id"])}/send" data-send="{int(c["id"])}">{csrf}'
                    f'<label for="m-body" class="hp">Message</label><textarea id="m-body" name="body" maxlength="{MAX_BODY}" required placeholder="Write a message" rows="1">{esc(draft)}</textarea>'
                    f'<button class="b" type="submit" aria-label="Send">{ui.icon("send", 16)}</button></form>')
    else:
        composer = f'<div class="composer"><span class="muted small">{esc(why)}</span></div>'
    blocked_by_me = c["blocked_by"] == user["id"]
    actions = (f'<form method="post" action="/messages/{int(c["id"])}/{"unblock" if blocked_by_me else "block"}" class="navform">{csrf}'
               f'<button class="b sm sec" type="submit">{"Unblock" if blocked_by_me else "Block"}</button></form>'
               f'<form method="post" action="/messages/{int(c["id"])}/report" class="navform">{csrf}<button class="b sm danger" type="submit">{ui.icon("flag", 14)} Report</button></form>'
               f'<form method="post" action="/messages/{int(c["id"])}/hide" class="navform">{csrf}<button class="b sm ghost" type="submit">Archive</button></form>')
    subject = f'<span class="pill">{esc(c["subject"])}</span>' if c["subject"] else ""
    right = (f'<div class="convo"><div class="convo-head"><div class="row">{web.person(name, sub, kind, href)}{subject}</div><div class="row">{actions}</div></div>'
             f'<div class="thread" id="thread" data-cid="{int(c["id"])}" data-last="{int(last_id)}" aria-live="polite">{bubbles}</div>{composer}</div>')
    body = (f'<a class="back" href="/messages" style="margin-top:14px">← All messages</a>'
            f'<div class="inbox open" style="margin-top:6px"><div class="threads">{threads}</div>{right}</div>'
            '<p class="small faint" style="margin-top:10px">Links in messages aren\'t clickable. Never send money, gift cards or bank details to get a job. '
            '<a href="/check">Check a message</a></p>')
    return web.page(body, f"Messages with {name}", active="/messages", js=True, status=status)


# ---------- routes ----------

@router.get("/messages", response_class=HTMLResponse)
def inbox(request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        return _inbox_page(conn, user)


@router.get("/messages/new", response_class=HTMLResponse)
def new_form(request: Request, to: int = 0, job: int = 0):
    user = web.require_user(request)
    with store.db() as conn:
        ok, why = can_start(conn, user, to)
        if not ok:
            return web.page(ui.page_head("New message") + ui.banner("info", why) + '<a class="b sec" href="/messages">Messages</a>',
                            "New message", active="/messages", status=403)
        student_id, employer_id = (user["id"], to) if user["role"] == "student" else (to, user["id"])
        existing = store.row(conn, "SELECT id FROM conversations WHERE student_id = ? AND employer_id = ? AND job_id = ?",
                             (student_id, employer_id, job if job > 0 else 0))
        if existing:
            return RedirectResponse(f"/messages/{existing['id']}", status_code=303)
        name, sub, kind = web.display_name(conn, to)
        jobrow = store.row(conn, "SELECT id, title FROM jobs WHERE id = ? AND review_status = 'approved' AND employer_id = ?",
                           (job, employer_id)) if job > 0 else None
    about = f'<p class="small muted" style="margin:10px 0 0">About: <b>{esc(jobrow["title"])}</b></p>' if jobrow else ""
    tip = ("Introduce yourself and say which role you're interested in. Don't include your student ID, SSN or bank details. No real employer needs them in a first message."
           if user["role"] == "student" else
           "Be specific about the role, pay and next step. Messages asking students for money, bank details, check deposits or chats on other apps are blocked.")
    body = (ui.page_head("New message", tip) +
            f'<div class="card" style="max-width:680px">{web.person(name, sub, kind)}{about}'
            f'<form method="post" action="/messages/new" style="margin-top:14px">{ui.user_csrf_input()}<input type="hidden" name="to" value="{int(to)}">'
            f'<input type="hidden" name="job" value="{int(jobrow["id"]) if jobrow else 0}">'
            f'<div class="form-field"><label for="n-body">Message</label><textarea id="n-body" name="body" required maxlength="{MAX_BODY}" data-count></textarea></div>'
            '<button class="submit-btn" type="submit">Send</button></form></div>')
    return web.page(body, "New message", active="/messages", js=True)


@router.post("/messages/new")
def new_send(request: Request, background: BackgroundTasks, to: int = Form(0), job: int = Form(0), body: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/messages/new?to={int(to)}", status_code=303)
    security.enforce_key_limit(security.message_limiter, f"u{user['id']}", "sending messages")
    try:
        text = clean_body(body)
    except ValueError as e:
        return web.page(ui.banner("warning", str(e)) + f'<a class="b sec" href="/messages/new?to={int(to)}">Back</a>', "New message", active="/messages", status=400)
    with store.db() as conn:
        ok, why = can_start(conn, user, to)
        if not ok:
            return web.page(ui.banner("info", why), "New message", active="/messages", status=403)
        student_id, employer_id = (user["id"], to) if user["role"] == "student" else (to, user["id"])
        jobrow = store.row(conn, "SELECT id, title FROM jobs WHERE id = ? AND review_status = 'approved' AND employer_id = ?",
                           (job, employer_id)) if job > 0 else None
        job_id = jobrow["id"] if jobrow else 0
        c = store.row(conn, "SELECT * FROM conversations WHERE student_id = ? AND employer_id = ? AND job_id = ?", (student_id, employer_id, job_id))
        if not c:
            security.enforce_key_limit(security.new_convo_limiter, f"u{user['id']}", "starting conversations")
            now = time.time()
            cur = conn.execute("INSERT INTO conversations (student_id, employer_id, job_id, subject, started_by, created_at, last_at) VALUES (?,?,?,?,?,?,?)",
                               (student_id, employer_id, job_id, jobrow["title"][:120] if jobrow else "", user["id"], now, now))
            c = store.row(conn, "SELECT * FROM conversations WHERE id = ?", (cur.lastrowid,))
        ok, why = can_send(conn, c, user)
        if not ok:
            return RedirectResponse(f"/messages/{c['id']}", status_code=303)
        res = add_message(conn, c, user, text)
        if res["status"] == "delivered":
            _notify(background, conn, c, user)
    return RedirectResponse(f"/messages/{c['id']}", status_code=303)


@router.get("/messages/{cid}", response_class=HTMLResponse)
def open_convo(cid: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        c = get_convo(conn, cid, user)
        if not c:
            return web.page('<p class="empty" style="margin:40px 0">That conversation isn\'t available.</p>', "Messages", active="/messages", status=404)
        return _inbox_page(conn, user, c)


def _send(request: Request, background: BackgroundTasks, cid: int, body: str, csrf: str):
    user = web.require_user(request)
    if not web.csrf_ok(request, csrf):
        return None, "That page had been open too long. Your message is still here; send it again.", 400
    security.enforce_key_limit(security.message_limiter, f"u{user['id']}", "sending messages")
    try:
        text = clean_body(body)
    except ValueError as e:
        return None, str(e), 400
    with store.db() as conn:
        c = get_convo(conn, cid, user)
        if not c:
            return None, "That conversation isn't available.", 404
        ok, why = can_send(conn, c, user)
        if not ok:
            return None, why, 403
        res = add_message(conn, c, user, text)
        if res["status"] == "delivered":
            _notify(background, conn, c, user)
        m = store.row(conn, "SELECT * FROM messages WHERE id = ?", (res["id"],))
        return message_json(m, user["id"]), "", 200


@router.post("/messages/{cid}/send")
def send_form(cid: int, request: Request, background: BackgroundTasks, body: str = Form(""), csrf: str = Form("")):
    msg, err, status = _send(request, background, cid, body, csrf)
    if err:
        user = web.require_user(request)
        with store.db() as conn:
            c = get_convo(conn, cid, user)
            if not c:
                return web.page('<p class="empty">That conversation isn\'t available.</p>', "Messages", active="/messages", status=404)
            return _inbox_page(conn, user, c, error=err, draft=body[:MAX_BODY], status=status)
    return RedirectResponse(f"/messages/{cid}#thread", status_code=303)


@router.post("/api/messages/{cid}")
async def send_api(cid: int, request: Request, background: BackgroundTasks):
    web.require_user(request)
    try:
        data = await request.json()
    except ValueError:
        return JSONResponse({"error": "Bad request."}, status_code=400)
    if not isinstance(data, dict) or not isinstance(data.get("body", ""), str):
        return JSONResponse({"error": "Bad request."}, status_code=400)
    msg, err, status = _send(request, background, cid, data.get("body", ""), request.headers.get("x-csrf-token", ""))
    if err:
        return JSONResponse({"error": err}, status_code=status)
    return JSONResponse({"message": msg, "html": _bubble(msg)})


@router.get("/api/messages/{cid}")
def poll_api(cid: int, request: Request, after: int = 0):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "poll")
    with store.db() as conn:
        c = get_convo(conn, cid, user)
        if not c:
            return JSONResponse({"error": "Not found."}, status_code=404)
        msgs = store.rows(conn, "SELECT * FROM messages WHERE conversation_id = ? AND id > ? AND (status = 'delivered' OR sender_id = ?) ORDER BY id LIMIT 100",
                          (cid, after, user["id"]))
        conn.execute("UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL AND status = 'delivered'",
                     (time.time(), cid, user["id"]))
    items = [message_json(m, user["id"]) for m in msgs]
    return JSONResponse({"messages": [{"id": i["id"], "mine": i["mine"], "html": _bubble(i)} for i in items],
                         "closed": bool(c["blocked_by"])}, headers={"Cache-Control": "no-store"})


def _convo_action(request: Request, cid: int, csrf: str, action):
    user = web.require_user(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/messages/{cid}", status_code=303)
    with store.db() as conn:
        c = get_convo(conn, cid, user)
        if c:
            return action(conn, c, user)
    return RedirectResponse("/messages", status_code=303)


@router.post("/messages/{cid}/block")
def block(cid: int, request: Request, csrf: str = Form("")):
    def act(conn, c, user):
        if not c["blocked_by"]:
            conn.execute("UPDATE conversations SET blocked_by = ? WHERE id = ?", (user["id"], c["id"]))
        return RedirectResponse(f"/messages/{c['id']}", status_code=303)
    return _convo_action(request, cid, csrf, act)


@router.post("/messages/{cid}/unblock")
def unblock(cid: int, request: Request, csrf: str = Form("")):
    def act(conn, c, user):
        conn.execute("UPDATE conversations SET blocked_by = NULL WHERE id = ? AND blocked_by = ?", (c["id"], user["id"]))
        return RedirectResponse(f"/messages/{c['id']}", status_code=303)
    return _convo_action(request, cid, csrf, act)


@router.post("/messages/{cid}/hide")
def hide(cid: int, request: Request, csrf: str = Form("")):
    def act(conn, c, user):
        col = "student_hidden" if user["id"] == c["student_id"] else "employer_hidden"
        conn.execute(f"UPDATE conversations SET {col} = 1 WHERE id = ?", (c["id"],))
        return RedirectResponse("/messages", status_code=303)
    return _convo_action(request, cid, csrf, act)


@router.post("/messages/{cid}/report", response_class=HTMLResponse)
def report(cid: int, request: Request, csrf: str = Form("")):
    def act(conn, c, user):
        conn.execute("INSERT OR IGNORE INTO reports (reporter_id, target_type, target_id, reason, created_at) VALUES (?,?,?,?,?)",
                     (user["id"], "conversation", c["id"], "reported from messages", time.time()))
        if not c["blocked_by"]:
            conn.execute("UPDATE conversations SET blocked_by = ? WHERE id = ?", (user["id"], c["id"]))
        body = (ui.page_head("Thanks for reporting", "A reviewer will look at this conversation. We also blocked it, so they can't message you here.") +
                '<ol class="next"><li>Don\'t send money, gift cards, or bank or ID details.</li>'
                '<li>If you already shared banking details or deposited a check they sent, call your bank now.</li>'
                '<li>Report fraud to the FTC at reportfraud.ftc.gov.</li></ol>'
                f'<a class="b sec" href="/messages/{int(c["id"])}">Back to the conversation</a>')
        return web.page(body, "Reported", active="/messages")
    return _convo_action(request, cid, csrf, act)
