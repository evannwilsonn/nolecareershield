"""
Reviewer queues for the network features, behind the same reviewer sign-in as the job queue:
employers waiting for approval, employer feed posts, anything the scanner held (posts,
comments, messages), user reports, and messages students sent in from the scam checker.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import security
import employer_page
import store
import ui
import web
from scam_detector.rules import FREE_MAIL
from ui import esc

router = APIRouter()

REJECT_NOTES = {
    "unverifiable": "We couldn't confirm the organization from its website and email.",
    "mismatch": "Sign up with an email address at your organization's own domain.",
    "not_fsu": "We couldn't see how the organization hires or supports FSU students.",
    "other": "It didn't meet our guidelines.",
}


def _ok(session: str | None) -> bool:
    return security.session_valid(session)


def _gate(session: str | None, csrf: str) -> bool:
    return _ok(session) and security.verify_csrf(csrf, "admin:" + session)


def _csrf(session: str) -> str:
    return f'<input type="hidden" name="csrf" value="{security.make_csrf("admin:" + session)}">'


def counts(conn) -> dict:
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "employers": one("SELECT COUNT(*) FROM employer_profiles WHERE status = 'pending'"),
        "posts": one("SELECT COUNT(*) FROM posts WHERE status IN ('pending','held')") + one("SELECT COUNT(*) FROM post_comments WHERE status = 'held'"),
        "messages": one("SELECT COUNT(*) FROM messages WHERE status = 'held'"),
        "reports": one("SELECT COUNT(*) FROM reports WHERE resolved = 0"),
        "checks": one("SELECT COUNT(*) FROM submitted_checks"),
        "schools": one("SELECT COUNT(DISTINCT lower(school)) FROM school_requests"),
    }


def tabs(active: str) -> str:
    with store.db() as conn:
        c = counts(conn)
    items = [("/admin", "Listings", None), ("/admin/employers", "Employers", c["employers"]), ("/admin/posts", "Feed", c["posts"]),
             ("/admin/messages", "Held messages", c["messages"]), ("/admin/reports", "Reports", c["reports"]),
             ("/admin/checks", "Sent-in messages", c["checks"]), ("/admin/schools", "School requests", c["schools"])]
    return '<div class="admin-tabs seg">' + "".join(
        f'<a href="{h}"{" class=on" if h == active else ""}>{esc(t)}{f" · {n}" if n else ""}</a>' for h, t, n in items) + "</div>"


def _page(body: str, title: str, active: str) -> HTMLResponse:
    return HTMLResponse(ui.shell(f'<h2 class="page">{esc(title)}</h2>' + tabs(active) + body, title=title, admin=True))


def _domain_note(email: str, website: str) -> str:
    ed = email.rsplit("@", 1)[-1].lower()
    host = (urlparse(website).hostname or "").lower().removeprefix("www.")
    if ed in FREE_MAIL:
        return f'<span class="pill warn">Personal email (@{esc(ed)})</span>'
    if host and (ed == host or ed.endswith("." + host) or host.endswith("." + ed)):
        return '<span class="pill ok">✓ Email domain matches website</span>'
    return f'<span class="pill warn">Email @{esc(ed)} ≠ website {esc(host or "?")}</span>'


@router.get("/admin/employers", response_class=HTMLResponse)
def employers(session: str | None = Cookie(default=None)):
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = _csrf(session)
    with store.db() as conn:
        pend = store.rows(conn, "SELECT e.*, u.email FROM employer_profiles e JOIN users u ON u.id = e.user_id WHERE e.status = 'pending' ORDER BY e.updated_at")
        live = store.rows(conn, "SELECT e.*, u.email FROM employer_profiles e JOIN users u ON u.id = e.user_id WHERE e.status IN ('approved','suspended') ORDER BY e.company LIMIT 200")
        for e in pend + live:
            e["trust_pill"] = employer_page.trust_pill(employer_page.trust(conn, e["user_id"]))
    rej = "".join(f'<button class="btn-reject" name="note" value="{k}" type="submit">Reject: {esc(k.replace("_", " "))}</button>' for k in REJECT_NOTES)
    cards = "".join(f"""<div class="rev-card"><div class="row between"><div><div class="job-title">{esc(e['company'])}</div>
<div class="job-co">{esc(e['email'])} · {esc(e['website'])}</div></div><div class="row">{_domain_note(e['email'], e['website'])}{e['trust_pill']}</div></div>
<p class="small muted" style="margin-top:6px">{esc(" · ".join(x for x in (e['industry'], e['size'], e['location']) if x))}</p>
<p style="margin-top:8px;white-space:pre-wrap">{esc(e['about'])}</p>
<p class="small" style="margin-top:8px"><b>FSU connection:</b> {esc(e['fsu_connection'])}</p>
<p class="small muted">Contact: {esc(e['contact_name'])}, {esc(e['contact_title'])}</p>
<div class="rev-actions"><form method="post" action="/admin/employers/{int(e['user_id'])}/approve">{csrf}<button class="btn-approve" type="submit">Approve</button></form>
<form method="post" action="/admin/employers/{int(e['user_id'])}/reject" style="display:flex;gap:8px;flex-wrap:wrap">{csrf}{rej}</form></div></div>""" for e in pend) \
        or '<div class="empty">No employers waiting.</div>'
    rows = "".join(f"""<tr><td><b>{esc(e['company'])}</b><div class="small faint">{esc(e['email'])}</div></td><td>{esc(e['status'])}</td><td>{e['trust_pill']}</td>
<td><form method="post" action="/admin/employers/{int(e['user_id'])}/{'suspend' if e['status'] == 'approved' else 'approve'}">{csrf}
<button class="b sm {'danger' if e['status'] == 'approved' else 'sec'}" type="submit">{'Suspend' if e['status'] == 'approved' else 'Reinstate'}</button></form></td></tr>""" for e in live)
    body = (f'<p class="lead">Approve an organization only when the website, email domain and FSU connection check out. Approval lets them '
            f'message students, see the opt-in directory and submit feed posts (each post is still reviewed).</p>{cards}'
            + (f'<h3 class="sec">Approved and suspended</h3><div class="card"><table class="t">{rows}</table></div>' if rows else ""))
    return _page(body, "Employers", "/admin/employers")


@router.post("/admin/employers/{uid}/{action}")
def employer_action(uid: int, action: str, request: Request, session: str | None = Cookie(default=None),
                    csrf: str = Form(""), note: str = Form("")):
    if not _gate(session, csrf) or action not in ("approve", "reject", "suspend"):
        return RedirectResponse("/admin/employers", status_code=303)
    security.enforce_rate_limit(request, security.general_limiter, "admin_action")
    status = {"approve": "approved", "reject": "rejected", "suspend": "suspended"}[action]
    msg = REJECT_NOTES.get(note, REJECT_NOTES["other"]) if action == "reject" else ""
    with store.db() as conn:
        conn.execute("UPDATE employer_profiles SET status = ?, status_note = ?, reviewed_at = ? WHERE user_id = ?", (status, msg, time.time(), uid))
        if action == "suspend":
            # Nothing they sent that is still waiting gets delivered.
            conn.execute("UPDATE posts SET status = 'removed' WHERE author_id = ? AND status IN ('pending','held')", (uid,))
    return RedirectResponse("/admin/employers", status_code=303)


@router.get("/admin/posts", response_class=HTMLResponse)
def posts(session: str | None = Cookie(default=None)):
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = _csrf(session)
    with store.db() as conn:
        ps = store.rows(conn, "SELECT p.*, u.email, u.role FROM posts p JOIN users u ON u.id = p.author_id WHERE p.status IN ('pending','held') ORDER BY p.created_at")
        cs = store.rows(conn, "SELECT c.*, u.email FROM post_comments c JOIN users u ON u.id = c.author_id WHERE c.status = 'held' ORDER BY c.created_at")
        names = {p["author_id"]: web.display_name(conn, p["author_id"], p["role"])[0] for p in ps}
    out = ""
    for p in ps:
        scan = store.jload(p["scan_json"], [])
        rel = store.jload(p["relevance_json"], {})
        flags = "".join(f'<div class="finding {esc(f.get("severity", "note"))}"><b>{esc(f.get("title", ""))}</b></div>' for f in scan)
        relinfo = ""
        if rel:
            relinfo = f'<p class="small muted">FSU signals: {esc(", ".join(rel.get("signals", [])) or "none")}'
            if rel.get("ai"):
                relinfo += f' · AI: {"relevant" if rel["ai"].get("relevant") else "not relevant"} ({esc(rel["ai"].get("reason", ""))})'
            relinfo += "</p>"
        why = "Employer post, needs approval" if p["status"] == "pending" else "Held: scanner flags or reports"
        out += f"""<div class="rev-card"><div class="row between"><div><b>{esc(names[p['author_id']])}</b> <span class="faint small">{esc(p['email'])} · {esc(p['role'])}</span></div>
<span class="pill warn">{esc(why)}</span></div><p class="small" style="margin-top:4px">Type: {esc(p['kind'])} · scan: {esc(p['scan_band'])}</p>{relinfo}{flags}
<div class="detail-desc" style="font-size:14px;background:var(--canvas);padding:10px 12px;border-radius:8px">{esc(p['body'])}</div>{f'<p class="small">Link: {esc(p["link"])}</p>' if p['link'] else ''}
<div class="rev-actions"><form method="post" action="/admin/posts/{int(p['id'])}/publish">{csrf}<button class="btn-approve" type="submit">Publish</button></form>
<form method="post" action="/admin/posts/{int(p['id'])}/reject">{csrf}<button class="btn-reject" type="submit">Reject</button></form></div></div>"""
    for c in cs:
        out += f"""<div class="rev-card"><div class="row between"><b>Comment by {esc(c['email'])}</b><span class="pill warn">Held: scanner flags</span></div>
<div class="detail-desc" style="font-size:14px">{esc(c['body'])}</div><div class="rev-actions">
<form method="post" action="/admin/comments/{int(c['id'])}/publish">{csrf}<button class="btn-approve" type="submit">Publish</button></form>
<form method="post" action="/admin/comments/{int(c['id'])}/remove">{csrf}<button class="btn-reject" type="submit">Remove</button></form></div></div>"""
    return _page(out or '<div class="empty">Nothing waiting.</div>', "Feed review", "/admin/posts")


@router.post("/admin/posts/{pid}/{action}")
def post_action(pid: int, action: str, request: Request, session: str | None = Cookie(default=None), csrf: str = Form("")):
    if _gate(session, csrf) and action in ("publish", "reject", "remove"):
        status = {"publish": "published", "reject": "rejected", "remove": "removed"}[action]
        with store.db() as conn:
            conn.execute("UPDATE posts SET status = ?, reviewed_at = ? WHERE id = ?", (status, time.time(), pid))
            if action == "publish":
                conn.execute("UPDATE reports SET resolved = 1 WHERE target_type = 'post' AND target_id = ?", (pid,))
    return RedirectResponse("/admin/posts", status_code=303)


@router.post("/admin/comments/{cid}/{action}")
def comment_action(cid: int, action: str, session: str | None = Cookie(default=None), csrf: str = Form("")):
    if _gate(session, csrf) and action in ("publish", "remove"):
        with store.db() as conn:
            conn.execute("UPDATE post_comments SET status = ? WHERE id = ?", ("published" if action == "publish" else "removed", cid))
            conn.execute("UPDATE posts SET comment_count = (SELECT COUNT(*) FROM post_comments WHERE post_id = posts.id AND status = 'published') "
                         "WHERE id = (SELECT post_id FROM post_comments WHERE id = ?)", (cid,))
    return RedirectResponse("/admin/posts", status_code=303)


@router.get("/admin/messages", response_class=HTMLResponse)
def held_messages(session: str | None = Cookie(default=None)):
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = _csrf(session)
    with store.db() as conn:
        ms = store.rows(conn, """SELECT m.*, u.email AS sender_email, u.role AS sender_role FROM messages m JOIN users u ON u.id = m.sender_id
                                  WHERE m.status = 'held' ORDER BY m.created_at LIMIT 200""")
    out = "".join(f"""<div class="rev-card"><div class="row between"><b>From {esc(m['sender_email'])} ({esc(m['sender_role'])})</b>
<span class="rev-score held">Score {int(m['scan_score'])} · {esc(m['scan_band'])}</span></div>
{"".join(f'<div class="finding {esc(f.get("severity", "note"))}"><b>{esc(f.get("title", ""))}</b><br>{esc(f.get("why", ""))}</div>' for f in store.jload(m['scan_json'], []))}
<div class="detail-desc" style="font-size:14px;background:var(--canvas);padding:10px 12px;border-radius:8px">{esc(m['body'])}</div>
<div class="rev-actions"><form method="post" action="/admin/messages/{int(m['id'])}/release">{csrf}<button class="btn-approve" type="submit">Deliver it</button></form>
<form method="post" action="/admin/messages/{int(m['id'])}/remove">{csrf}<button class="btn-reject" type="submit">Remove</button></form>
<form method="post" action="/admin/messages/{int(m['id'])}/remove-suspend">{csrf}<button class="btn-reject" type="submit">Remove and suspend sender</button></form></div></div>""" for m in ms)
    return _page('<p class="lead">Messages the scanner scored as scams are held here, undelivered. Delivering one also shows it with its warning.</p>'
                 + (out or '<div class="empty">No held messages.</div>'), "Held messages", "/admin/messages")


@router.post("/admin/messages/{mid}/{action}")
def message_action(mid: int, action: str, session: str | None = Cookie(default=None), csrf: str = Form("")):
    if _gate(session, csrf) and action in ("release", "remove", "remove-suspend"):
        with store.db() as conn:
            m = store.row(conn, "SELECT * FROM messages WHERE id = ?", (mid,))
            if m:
                if action == "release":
                    # Delivered with its warning (the reader still sees the scanner's findings).
                    conn.execute("UPDATE messages SET status = 'delivered', scan_band = 'review' WHERE id = ?", (mid,))
                else:
                    conn.execute("UPDATE messages SET status = 'removed' WHERE id = ?", (mid,))
                    if action == "remove-suspend":
                        conn.execute("UPDATE employer_profiles SET status = 'suspended', reviewed_at = ? WHERE user_id = ?", (time.time(), m["sender_id"]))
                        conn.execute("UPDATE messages SET status = 'removed' WHERE sender_id = ? AND status = 'held'", (m["sender_id"],))
    return RedirectResponse("/admin/messages", status_code=303)


@router.get("/admin/reports", response_class=HTMLResponse)
def reports(session: str | None = Cookie(default=None)):
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = _csrf(session)
    with store.db() as conn:
        rs = store.rows(conn, """SELECT target_type, target_id, COUNT(*) AS n, MIN(created_at) AS first FROM reports WHERE resolved = 0
                                  GROUP BY target_type, target_id ORDER BY n DESC, first LIMIT 200""")
        out = ""
        for r in rs:
            detail = ""
            if r["target_type"] == "post":
                p = store.row(conn, "SELECT p.*, u.email FROM posts p JOIN users u ON u.id = p.author_id WHERE p.id = ?", (r["target_id"],))
                if p:
                    detail = (f'<p class="small muted">Post by {esc(p["email"])} · status {esc(p["status"])}</p>'
                              f'<div class="detail-desc" style="font-size:14px">{esc(p["body"])}</div>')
                actions = (f'<form method="post" action="/admin/posts/{int(r["target_id"])}/remove">{csrf}<button class="btn-reject" type="submit">Remove post</button></form>'
                           f'<form method="post" action="/admin/posts/{int(r["target_id"])}/publish">{csrf}<button class="btn-approve" type="submit">Keep it up</button></form>')
            else:
                c = store.row(conn, "SELECT * FROM conversations WHERE id = ?", (r["target_id"],))
                if c:
                    ms = store.rows(conn, "SELECT m.body, m.scan_band, u.email, u.role FROM messages m JOIN users u ON u.id = m.sender_id "
                                          "WHERE m.conversation_id = ? ORDER BY m.id DESC LIMIT 8", (c["id"],))
                    detail = "".join(f'<div class="finding {"warning" if x["scan_band"] in ("review", "block") else "note"}"><b>{esc(x["email"])} ({esc(x["role"])})</b>'
                                     f'<br>{esc(x["body"][:500])}</div>' for x in reversed(ms))
                    actions = (f'<form method="post" action="/admin/employers/{int(c["employer_id"])}/suspend">{csrf}<button class="btn-reject" type="submit">Suspend the employer</button></form>')
                else:
                    actions = ""
            out += (f'<div class="rev-card"><div class="row between"><b>{esc(r["target_type"].title())} #{int(r["target_id"])}</b>'
                    f'<span class="pill bad">{web.plural(r["n"], "report")}</span></div>{detail}<div class="rev-actions">{actions}'
                    f'<form method="post" action="/admin/reports/{esc(r["target_type"])}/{int(r["target_id"])}/resolve">{csrf}<button class="btn-reject" type="submit">Mark resolved</button></form></div></div>')
    return _page(out or '<div class="empty">No open reports.</div>', "Reports", "/admin/reports")


@router.post("/admin/reports/{ttype}/{tid}/resolve")
def resolve(ttype: str, tid: int, session: str | None = Cookie(default=None), csrf: str = Form("")):
    if _gate(session, csrf) and ttype in ("post", "conversation"):
        with store.db() as conn:
            conn.execute("UPDATE reports SET resolved = 1 WHERE target_type = ? AND target_id = ?", (ttype, tid))
    return RedirectResponse("/admin/reports", status_code=303)


@router.get("/admin/checks", response_class=HTMLResponse)
def checks(session: str | None = Cookie(default=None)):
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    with store.db() as conn:
        cs = store.rows(conn, "SELECT * FROM submitted_checks ORDER BY created_at DESC LIMIT 200")
    out = "".join(f"""<div class="rev-card"><div class="row between"><span class="small muted">{esc(time.strftime('%Y-%m-%d', time.gmtime(c['created_at'])))}
{(' · from ' + esc(c['sender'])) if c['sender'] else ''}</span><span class="row"><span class="pill">detector: {esc(c['band'])}</span>
<span class="pill {'bad' if c['user_label'] == 'scam' else 'ok' if c['user_label'] == 'legit' else ''}">student says: {esc(c['user_label'])}</span></span></div>
<div class="detail-desc" style="font-size:14px;max-height:180px;overflow:auto">{esc(c['body'])}</div></div>""" for c in cs)
    return _page('<p class="lead">Messages students sent in from the scam checker. Label the clear ones into the corpus (see ADAPTING.md) '
                 'so the next rule update learns from them.</p>' + (out or '<div class="empty">Nothing sent in yet.</div>'),
                 "Sent-in messages", "/admin/checks")


@router.get("/admin/schools", response_class=HTMLResponse)
def schools(session: str | None = Cookie(default=None)):
    """Schools visitors asked for from the public scam check: leads for the next campus."""
    if not _ok(session):
        return RedirectResponse("/admin", status_code=303)
    with store.db() as conn:
        rs = store.rows(conn, "SELECT min(school) AS school, COUNT(*) AS n, MAX(created_at) AS last FROM school_requests "
                              "GROUP BY lower(school) ORDER BY n DESC, last DESC LIMIT 200")
    rows = "".join(f'<tr><td><b>{esc(r["school"])}</b></td><td>{int(r["n"])}</td><td class="small muted">{esc(time.strftime("%Y-%m-%d", time.gmtime(r["last"])))}</td></tr>'
                   for r in rs)
    body = ('<p class="lead">Schools that visitors asked for after using the public scam check. Only the school name is stored.</p>'
            + (f'<div class="card"><table class="t"><tr><th>School</th><th>Requests</th><th>Latest</th></tr>{rows}</table></div>' if rows
               else '<div class="empty">No requests yet.</div>'))
    return _page(body, "School requests", "/admin/schools")
