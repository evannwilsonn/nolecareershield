"""
The reviewer's intel page, the decoy desk, forward-by-email checks and the peer-school feed (the web side of defense.py).

- /admin/intel         drift and novelty alerts, the most-reported contact details (masked), scam rings, look-alike domains
                       from certificate logs, the campus scam calendar, and which outside checks are switched on.
- /admin/decoys        only when DECOY_ENABLED=1. A reviewer logs a conversation they are having with a scammer from a text-only
                       decoy persona. Nothing is ever sent from here: the site drafts at most a suggested reply for the reviewer
                       to copy. The scammer's messages become label-queue items, so their contact details are indexed.
- /inbound/email       a mail provider's inbound-parse webhook (SendGrid or Mailgun), protected by INBOUND_EMAIL_TOKEN. A
                       student forwards a suspicious email to the check address and gets the verdict back by email.
- /api/indicators      hashed, confirmed-scam identifiers for partner schools, behind the X-Share-Key header (SHARE_FEED_KEY).
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import time

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import admin_extra
import defense
import learning
import mailer
import store
import ui
from ui import esc

log = logging.getLogger("nolecareershield.defense")
router = APIRouter()


def decoys_enabled() -> bool:
    return os.environ.get("DECOY_ENABLED", "").lower() in ("1", "true", "yes", "on")


DECOY_SCHEMA = """
CREATE TABLE IF NOT EXISTS decoy_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, persona TEXT NOT NULL, wave INTEGER, direction TEXT NOT NULL,
    body TEXT NOT NULL, check_id INTEGER, created_at REAL NOT NULL);
"""

# Invented people. Text only: no photos, no real names or accounts, no documents, and never any money.
PERSONAS = {
    "maya": "Maya, sophomore, psychology. Looking for 10-15 hours a week, remote is fine. Replies quickly, a little trusting.",
    "jordan": "Jordan, junior, computer science. Wants a paid summer internship. Asks practical questions about pay and start dates.",
    "sam": "Sam, grad student, public health. Needs weekend work. Busy; short replies; says they're 'checking with their advisor'.",
}

PROTOCOL = [
    "FSU legal sign-off is required before the first conversation. Keep the approval on file.",
    "Text only. Never send a photo, a document, a real name, a real phone number, a school ID or any account detail.",
    "Never move money: don't deposit a check, buy gift cards, open an account, accept a transfer or send crypto, even 'to test'.",
    "Never click a link from the scammer on a work device. Paste links here; the checker reads them safely.",
    "Stop when they ask for money or a document. That's the evidence. Log it and end the conversation.",
    "If a real student is being targeted by the same crew, contact them through the university, not through the decoy.",
]


# ---------- the intel page ----------

def _config_rows() -> str:
    on = lambda *keys: all(os.environ.get(k, "").strip() for k in keys)
    rows = [
        ("Outside lookups (domain age, email auth, shortened links)", defense.network_on(), "INTEL_NETWORK=1, on by default in production"),
        ("URLhaus malware-link blocklist", on("URLHAUS_AUTH_KEY"), "URLHAUS_AUTH_KEY"),
        ("Spamhaus domain blocklist", on("SPAMHAUS_DQS_KEY"), "SPAMHAUS_DQS_KEY"),
        ("Chainabuse crypto-wallet reports", on("CHAINABUSE_API_KEY"), "CHAINABUSE_API_KEY"),
        ("Twilio phone line type (VoIP numbers)", on("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"), "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN"),
        ("Sharing with partner schools", on("SHARE_HMAC_KEY"), "SHARE_HMAC_KEY, SHARE_FEED_KEY, PEER_FEEDS"),
        ("Scam archive feeds", on("ARCHIVE_FEEDS"), "ARCHIVE_FEEDS"),
        ("Forward-by-email checks", on("INBOUND_EMAIL_TOKEN"), "INBOUND_EMAIL_TOKEN (and SMTP_* to reply)"),
        ("Decoy desk", decoys_enabled(), "DECOY_ENABLED=1, after legal sign-off"),
    ]
    on_, off = '<span class="pill ok">on</span>', '<span class="pill">off</span>'
    return "".join(f'<li>{on_ if v else off} {esc(t)}<span class="ev">{esc(k)}</span></li>' for t, v, k in rows)


@router.get("/admin/intel", response_class=HTMLResponse)
def intel_page(session: str | None = Cookie(default=None)):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = admin_extra._csrf(session)
    with store.db() as conn:
        alerts = defense.alerts(conn)
        top = store.rows(conn, """SELECT ci.kind, ci.shown, COUNT(DISTINCT ci.check_id) AS n,
                                         SUM(sc.review_label = 'scam') AS scam, SUM(sc.review_label = 'legit') AS legit
                                  FROM check_indicators ci JOIN submitted_checks sc ON sc.id = ci.check_id
                                  WHERE sc.created_at > ? GROUP BY ci.hash HAVING n >= 2 ORDER BY n DESC LIMIT 20""",
                         (time.time() - 90 * 86400,))
        ring_map = defense.rings(conn)
        ring_ids = sorted(set(ring_map.values()), key=lambda r: -sum(1 for v in ring_map.values() if v == r))[:8]
        rings = [defense.ring_summary(conn, r, ring_map) for r in ring_ids]
        ct = store.rows(conn, "SELECT * FROM ct_lookalikes ORDER BY found_at DESC LIMIT 20")
        windows = store.rows(conn, "SELECT * FROM risk_windows ORDER BY start_md")
        runs = store.rows(conn, "SELECT * FROM defense_runs ORDER BY job")
        peers = conn.execute("SELECT COUNT(*) FROM peer_indicators").fetchone()[0]
    lv = {"bad": "warning", "warn": "warning", "info": "info"}
    al = "".join(f'<div class="banner {lv.get(a["level"], "info")}" style="margin-bottom:8px"><b>{esc(a["title"])}</b>'
                 f'<div class="small">{esc(a["detail"])}</div></div>' for a in alerts) or '<p class="muted">Nothing unusual this week.</p>'
    tp = "".join(f'<tr><td>{esc(t["kind"])}</td><td><code>{esc(t["shown"])}</code></td><td>{t["n"]}</td>'
                 f'<td>{int(t["scam"] or 0)} scam · {int(t["legit"] or 0)} real</td></tr>' for t in top)
    rg = "".join(f'<li><b>Ring #{r["ring"]}</b>: {r["size"]} reports sharing contact details'
                 f'{" (" + ", ".join(f"{n} {esc(l)}" for l, n in r["labels"].items()) + ")" if r["labels"] else ""}</li>' for r in rings if r)
    cl = "".join(f'<li><code>{esc(c["domain"])}</code> imitates {esc(c["brand"])}<span class="ev">{esc(c["reason"])}</span></li>' for c in ct)
    wn = "".join(f'<li><b>{esc(w["name"])}</b> {esc(w["start_md"])} to {esc(w["end_md"])}<span class="ev">{esc(w["note"])}</span>'
                 f'<form method="post" action="/admin/intel/window/delete" style="display:inline">{csrf}<input type="hidden" name="wid" value="{w["id"]}">'
                 f'<button class="b sm ghost" type="submit">Remove</button></form></li>' for w in windows)
    rn = "".join(f'<li>{esc(r["job"])}: {esc(r["detail"])} <span class="muted small">{time.strftime("%b %d %H:%M", time.gmtime(r["last_run"]))} UTC</span></li>'
                 for r in runs) or "<li class=muted>No scheduled checks have run yet.</li>"
    body = f"""<section class="card"><h2>Alerts</h2>{al}</section>
<section class="card"><h2>Contact details seen in more than one report (last 90 days)</h2>
<p class="small muted">Shown masked. Stored as keyed hashes, so the database alone can't be read back into phone numbers or emails.</p>
{f'<table class="tbl"><tr><th>Kind</th><th>Detail</th><th>Reports</th><th>Labels</th></tr>{tp}</table>' if tp else '<p class="muted">None yet.</p>'}</section>
<section class="card"><h2>Scam rings</h2><p class="small muted">Reports joined because they share a phone, email, domain, handle or wallet.</p>
<ul class="reasons">{rg or "<li class=muted>None yet.</li>"}</ul></section>
<section class="card"><h2>Look-alike domains in certificate logs</h2><ul class="reasons">{cl or "<li class=muted>None found.</li>"}</ul></section>
<section class="card"><h2>Scam calendar</h2><p class="small muted">Students see a notice on the scam check during these windows.</p>
<ul class="reasons">{wn}</ul>
<form method="post" action="/admin/intel/window" class="row">{csrf}
<input name="name" maxlength="80" placeholder="Name, e.g. Career fair week" required>
<input name="start_md" pattern="\\d{{2}}-\\d{{2}}" placeholder="MM-DD" required style="width:90px">
<input name="end_md" pattern="\\d{{2}}-\\d{{2}}" placeholder="MM-DD" required style="width:90px">
<input name="note" maxlength="240" placeholder="What students should watch for">
<button class="b sm" type="submit">Add</button></form></section>
<section class="card"><h2>Outside checks</h2><ul class="reasons">{_config_rows()}</ul>
<p class="small muted">Peer indicators on file: {peers}. Keys live only in the server's environment.</p>
<h3 class="sec">Scheduled checks</h3><ul class="small">{rn}</ul></section>"""
    return admin_extra._page(body, "Scam intel", "/admin/intel")


_MD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


@router.post("/admin/intel/window")
def window_add(name: str = Form(""), start_md: str = Form(""), end_md: str = Form(""), note: str = Form(""),
               session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    if name.strip() and _MD.match(start_md) and _MD.match(end_md):
        with store.db() as conn:
            conn.execute("INSERT INTO risk_windows (name, start_md, end_md, note) VALUES (?,?,?,?)",
                         (name.strip()[:80], start_md, end_md, note.strip()[:240]))
    return RedirectResponse("/admin/intel", status_code=303)


@router.post("/admin/intel/window/delete")
def window_delete(wid: int = Form(0), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    with store.db() as conn:
        conn.execute("DELETE FROM risk_windows WHERE id = ?", (wid,))
    return RedirectResponse("/admin/intel", status_code=303)


# ---------- the decoy desk (off unless DECOY_ENABLED) ----------

def _decoy_schema(conn) -> None:
    conn.executescript(DECOY_SCHEMA)


def draft_reply(persona: str, history: list[dict]) -> str:
    """A suggested next line for the reviewer to copy. Never sent from here. Empty when the AI isn't configured."""
    import ai
    if not ai.enabled() or persona not in PERSONAS:
        return ""
    system = ("You help a university fraud reviewer keep a job scammer talking long enough to learn their contact details and "
              "script. You write ONE short, plausible text reply as this invented student: " + PERSONAS[persona] + " Rules: text only; "
              "never agree to send or receive money, deposit anything, buy anything or share documents; never give a real name, "
              "number, school ID or account; if they ask for money or documents, stall politely and ask where to send questions. "
              "Ask for the company's website, the recruiter's full name and a phone number where natural.")
    convo = "\n".join(f"{'Scammer' if h['direction'] == 'in' else 'Student'}: {h['body']}" for h in history[-12:])
    try:
        resp = ai.call(system, [{"role": "user", "content": ai.tag("conversation", convo) + "\nWrite the student's next reply only."}],
                       max_tokens=200)
        return ai.text_of(resp).strip()[:600]
    except Exception:                                    # noqa: BLE001
        log.exception("decoy draft failed")
        return ""


@router.get("/admin/decoys", response_class=HTMLResponse)
def decoy_desk(persona: str = "", draft: int = 0, session: str | None = Cookie(default=None)):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    if not decoys_enabled():
        return admin_extra._page('<section class="card"><p>The decoy desk is off. It needs FSU legal sign-off, then '
                                 '<code>DECOY_ENABLED=1</code> in the server environment.</p></section>', "Decoy desk", "/admin/intel")
    csrf = admin_extra._csrf(session)
    persona = persona if persona in PERSONAS else next(iter(PERSONAS))
    with store.db() as conn:
        _decoy_schema(conn)
        logs = store.rows(conn, "SELECT * FROM decoy_logs WHERE persona = ? ORDER BY id DESC LIMIT 60", (persona,))
    logs.reverse()
    suggestion = draft_reply(persona, logs) if draft else ""
    tabs = " ".join(f'<a class="b sm {"" if p == persona else "ghost"}" href="/admin/decoys?persona={p}">{esc(p.title())}</a>' for p in PERSONAS)
    convo = "".join(f'<li><span class="pill {"bad" if h["direction"] == "in" else ""}">{"Scammer" if h["direction"] == "in" else "Decoy"}</span>'
                    f'<span class="ev" style="white-space:pre-wrap">{esc(h["body"])}</span></li>' for h in logs) or "<li class=muted>Nothing logged yet.</li>"
    body = f"""<section class="card"><h2>Protocol</h2><ol class="small">{"".join(f"<li>{esc(p)}</li>" for p in PROTOCOL)}</ol></section>
<section class="card"><div class="row">{tabs}</div><p class="small muted" style="margin-top:8px">{esc(PERSONAS[persona])}</p>
<ol class="reasons">{convo}</ol>
{f'<div class="banner info"><b>Suggested reply (copy it yourself; nothing is sent):</b><div style="white-space:pre-wrap">{esc(suggestion)}</div></div>' if suggestion else ''}
<form method="post" action="/admin/decoys/log">{csrf}<input type="hidden" name="persona" value="{persona}">
<div class="form-field"><label>Paste the next message</label><textarea name="body" required maxlength="8000"></textarea></div>
<div class="row"><button class="b sm" name="direction" value="in">They sent this</button>
<button class="b sm sec" name="direction" value="out">The decoy sent this</button>
<a class="b sm ghost" href="/admin/decoys?persona={persona}&draft=1">Suggest a reply</a></div></form></section>"""
    return admin_extra._page(body, "Decoy desk", "/admin/intel")


@router.post("/admin/decoys/log")
def decoy_log(persona: str = Form(""), body: str = Form(""), direction: str = Form("in"),
              session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf) or not decoys_enabled() or persona not in PERSONAS:
        return RedirectResponse("/admin", status_code=303)
    body = body.strip()[:8000]
    if body and direction in ("in", "out"):
        import msgcheck
        with store.db() as conn:
            _decoy_schema(conn)
            cid = None
            if direction == "in":                        # the scammer's words become a label-queue item: indexed, grouped into waves
                band = msgcheck.check(body)["band"]
                cid = learning.add_submission(conn, body=body, band=band, kind="message", source="decoy")
            prev = conn.execute("SELECT check_id FROM decoy_logs WHERE persona = ? AND check_id IS NOT NULL ORDER BY id LIMIT 1",
                                (persona,)).fetchone()
            if cid and prev and prev[0]:
                conn.execute("UPDATE submitted_checks SET campaign = COALESCE((SELECT campaign FROM submitted_checks WHERE id = ?), ?) "
                             "WHERE id = ?", (prev[0], prev[0], cid))
            conn.execute("INSERT INTO decoy_logs (persona, wave, direction, body, check_id, created_at) VALUES (?,?,?,?,?,?)",
                         (persona, prev[0] if prev else cid, direction, body, cid, time.time()))
    return RedirectResponse(f"/admin/decoys?persona={persona}", status_code=303)


# ---------- forward-by-email ----------

_sent: dict = {}
INBOUND_PER_DAY = 10


def _addr(v: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", v or "")
    return m.group(0).lower() if m else ""


def forwarded_part(text: str) -> tuple[str, str]:
    """(original sender, the forwarded message) from a forwarded email body; falls back to the whole body."""
    t = text or ""
    m = re.search(r"(?:-{3,}\s*Forwarded message\s*-{3,}|Begin forwarded message:|-----Original Message-----)", t, re.I)
    part = t[m.end():] if m else t
    sender = ""
    fm = re.search(r"^\s*From:\s*(.+)$", part, re.I | re.M)
    if fm:
        sender = _addr(fm.group(1))
    part = re.sub(r"^\s*(From|To|Cc|Date|Sent|Subject):.*$", "", part, flags=re.I | re.M).strip()
    return sender, part


def _auth_failed(headers: str) -> bool:
    ar = " ".join(re.findall(r"Authentication-Results:.*(?:\n[ \t].*)*", headers or "", re.I))
    return bool(re.search(r"\bdmarc=fail\b", ar, re.I)) and not re.search(r"\bdmarc=pass\b", ar, re.I)


def verdict_email(r: dict, thread: dict | None) -> str:
    lines = [r["title"], "", r["advice"], ""]
    for f in r["findings"][:5]:
        if f["severity"] != "note":
            lines.append(f"- {f['title']}: {f['why']}")
    if r.get("asks"):
        lines += ["", "What they're asking you to do:"] + [f"- {a['label']}" for a in r["asks"][:6]]
    if thread and thread.get("next_step"):
        lines += ["", "What usually comes next: " + thread["next_step"]]
    if r["level"] >= 2:
        lines += ["", "Report it: https://reportfraud.ftc.gov/ and, if you lost money, https://www.ic3.gov/"]
    lines += ["", "This is an automatic check by NoleCareerShield. It can be wrong; when in doubt, ask the Career Center."]
    return "\n".join(lines)


@router.post("/inbound/email")
async def inbound_email(request: Request, token: str = ""):
    want = os.environ.get("INBOUND_EMAIL_TOKEN", "")
    if not want or not hmac.compare_digest(token, want):
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()
    get = lambda *ks: next((str(form.get(k)) for k in ks if form.get(k)), "")
    student = _addr(get("from", "sender", "From"))
    text = get("text", "body-plain", "stripped-text")
    headers = get("headers", "message-headers")
    subject = get("subject", "Subject")[:200]
    if not student or not text.strip():
        return {"status": "ignored"}
    if _auth_failed(headers):                            # a spoofed forwarder: don't reply to someone who didn't write
        return {"status": "ignored"}
    day = time.strftime("%Y-%m-%d")
    key = (student, day)
    _sent[key] = _sent.get(key, 0) + 1
    if _sent[key] > INBOUND_PER_DAY:
        return {"status": "limited"}
    import msgcheck
    from scam_detector.conversation import analyze_thread
    orig_sender, body = forwarded_part(text)
    body = body[:20000]
    thread = analyze_thread(body) if len(re.findall(r"^\s*(?:On .+ wrote:|From:)", text, re.M)) >= 2 else None
    r = msgcheck.check(body[:8000], orig_sender)
    msgcheck.enrich(r, text=body[:8000], sender=orig_sender, extra=(thread or {}).get("findings") or [])
    with store.db() as conn:                             # the message is kept for reviewers; the student's address is not
        learning.add_submission(conn, body=body[:8000], sender=orig_sender, band=r["band"], kind="message", title=subject, source="email")
    mailer.send(student, f"Scam check: {r['title']}", verdict_email(r, thread))
    defense.bump("email_checks")
    return {"status": "ok", "band": r["band"]}


# ---------- the peer-school feed ----------

@router.get("/api/indicators")
def indicators(request: Request):
    want = os.environ.get("SHARE_FEED_KEY", "")
    got = request.headers.get("x-share-key", "")
    if not want or not defense._share_key() or not hmac.compare_digest(got, want):
        return JSONResponse({"error": "not found"}, status_code=404)
    with store.db() as conn:
        return JSONResponse(defense.share_feed(conn), headers={"Cache-Control": "no-store"})
