"""Emails: an in-site copy of every email the site sends to someone who has an account.

mailer.send calls keep() for each message. A copy is kept only for a verified account with that address,
and one-time links (confirm, reset, team invites) are replaced with a note, so the inbox never holds a working
credential. Only the account holder can read their copies; they go with the account and after a year.
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import security
import store
import ui
import web
from ui import esc

router = APIRouter()
_SECRET_LINK = re.compile(r"https?://\S*(?:/verify|/reset|/login/link|/team/join|token=)\S*", re.IGNORECASE)
REDACTED = "[This one-time link was sent only to your email inbox.]"


def keep(to: str, subject: str, body: str) -> None:
    with store.db() as conn:
        r = conn.execute("SELECT id FROM users WHERE lower(email) = lower(?) AND verified = 1", ((to or "").strip(),)).fetchone()
        if not r:
            return
        conn.execute("INSERT INTO emails (user_id, subject, body, sent_at) VALUES (?,?,?,?)",
                     (r[0], subject[:200], _SECRET_LINK.sub(REDACTED, body)[:8000], time.time()))


def unread(conn, uid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM emails WHERE user_id = ? AND read_at IS NULL", (uid,)).fetchone()[0]


@router.get("/emails", response_class=HTMLResponse)
def inbox(request: Request, id: int = 0):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "emails")
    with store.db() as conn:
        rows = store.rows(conn, "SELECT * FROM emails WHERE user_id = ? ORDER BY sent_at DESC LIMIT 200", (user["id"],))
        cur = next((r for r in rows if r["id"] == id), None)
        if cur and not cur["read_at"]:
            conn.execute("UPDATE emails SET read_at = ? WHERE id = ? AND user_id = ?", (time.time(), cur["id"], user["id"]))
            cur["read_at"] = time.time()
    head = ui.page_head("Emails", f"A copy of every email we send to {esc(user['email'])}. One-time sign-in links stay in your real inbox only.", num="Inbox")
    if not rows:
        return web.page(head + '<div class="card empty" style="padding:40px;text-align:center"><b>No emails yet</b>'
                        '<p class="small muted">When we email you about your account, listings or messages, a copy shows up here.</p></div>',
                        "Emails", active="/emails")
    items = "".join(
        f'<a class="mi{" on" if cur and r["id"] == cur["id"] else ""}{"" if r["read_at"] else " unread"}" href="/emails?id={r["id"]}">'
        f'<b>{esc(r["subject"])}</b><span class="snip">{esc(r["body"].strip().splitlines()[0][:90] if r["body"].strip() else "")}</span>'
        f'<small>{esc(web.ago(r["sent_at"]))}</small></a>' for r in rows)
    if cur:
        view = (f'<a class="back" href="/emails">← All emails</a><h2>{esc(cur["subject"])}</h2>'
                f'<p class="small muted" style="margin:0">From NoleCareerShield · to {esc(user["email"])} · {esc(web.ago(cur["sent_at"]))}</p>'
                f'<pre>{esc(cur["body"])}</pre><form method="post" action="/emails/{cur["id"]}/delete" style="margin-top:18px">{ui.user_csrf_input()}'
                f'<button class="b sm sec" type="submit">Delete</button></form>')
    else:
        view = '<p class="muted" style="margin:40px 0;text-align:center">Pick an email to read it.</p>'
    return web.page(f'{head}<div class="mailbox{" open" if cur else ""}"><div class="ml">{items}</div><div class="mv">{view}</div></div>',
                    "Emails", active="/emails")


@router.post("/emails/{eid}/delete")
def delete(eid: int, request: Request, csrf: str = Form("")):
    user = web.require_user(request)
    if web.csrf_ok(request, csrf):
        with store.db() as conn:
            conn.execute("DELETE FROM emails WHERE id = ? AND user_id = ?", (eid, user["id"]))
    return RedirectResponse("/emails", status_code=303)
