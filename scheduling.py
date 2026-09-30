"""
Interview scheduling inside Messages.

In an employer <-> student conversation the (approved) employer proposes 1-5 times with a format (video, phone or
in person) and a meeting link, phone note or address. The proposal shows in the thread as a card; the conversation's
student picks one time (or says none work, with an optional note). The employer can cancel or propose new times
(reschedule). Every step adds a line to the thread and sends an email (mailer.send, so the in-site Emails keep a copy).
Emails carry the time but never the link or address: those stay on the site, like message text.

All times are shown in Eastern Time (America/New_York). The DST rule is computed here (second Sunday of March to the
first Sunday of November), so nothing depends on the system's time-zone database. A confirmed interview downloads as
an .ics calendar file built here, with times in UTC.

Other modules can import `upcoming_interviews(conn, user_id)`.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import mailer
import msgcheck
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

# A calendar icon for the cards (added here so ui.py stays untouched; the demo's ICONS has the same path).
CAL_ICON = '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10.5h16M8.5 3.5v4M15.5 3.5v4"/>'
ui._ICON_PATHS.setdefault("calendar", CAL_ICON)

MAX_SLOTS = 5
DURATIONS = (15, 30, 45, 60)
FORMATS = {"video": "Video call", "phone": "Phone call", "in_person": "In person"}
FORMAT_ICON = {"video": "chat", "phone": "chat", "in_person": "home"}
LOCATION_MAX = 300
NOTE_MAX = 1000
STUDENT_NOTE_MAX = 500
MAX_AHEAD_DAYS = 180
MIN_LEAD_MINUTES = 10
TZ_NAME = "America/New_York"
# Meeting links from these hosts are clickable; anything else stays plain text (the "links aren't clickable" rule).
MEETING_HOSTS = ("zoom.us", "teams.microsoft.com", "meet.google.com")
# Link kinds the scanner flags that never belong in an interview card.
_BAD_LINK_RULES = {"chat_link", "short_link", "ip_link", "fsu_lookalike_link"}

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_UTC = dt.timezone.utc


# ---------- Eastern Time without a tz database ----------

def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    return d + dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def _dst_utc(year: int) -> tuple[dt.datetime, dt.datetime]:
    """DST in America/New_York runs from 2:00 local on the second Sunday of March (07:00 UTC)
    to 2:00 local on the first Sunday of November (06:00 UTC)."""
    a, b = _nth_sunday(year, 3, 2), _nth_sunday(year, 11, 1)
    return (dt.datetime(a.year, a.month, a.day, 7, tzinfo=_UTC), dt.datetime(b.year, b.month, b.day, 6, tzinfo=_UTC))


def et_offset_hours(ts: float) -> int:
    u = dt.datetime.fromtimestamp(ts, _UTC)
    start, end = _dst_utc(u.year)
    return -4 if start <= u < end else -5


def to_et(ts: float) -> dt.datetime:
    """A naive datetime holding the Eastern wall-clock time."""
    return (dt.datetime.fromtimestamp(ts, _UTC) + dt.timedelta(hours=et_offset_hours(ts))).replace(tzinfo=None)


def from_et(local: dt.datetime) -> float:
    """UTC epoch seconds for an Eastern wall-clock time. The skipped spring hour counts as daylight time and the
    repeated autumn hour as the first (daylight) one."""
    a, b = _nth_sunday(local.year, 3, 2), _nth_sunday(local.year, 11, 1)
    dst = dt.datetime(a.year, a.month, a.day, 2) <= local < dt.datetime(b.year, b.month, b.day, 2)
    return (local - dt.timedelta(hours=-4 if dst else -5)).replace(tzinfo=_UTC).timestamp()


def _hm(d: dt.datetime, ampm: bool = True) -> str:
    s = f"{d.hour % 12 or 12}:{d.minute:02d}"
    return f"{s} {'AM' if d.hour < 12 else 'PM'}" if ampm else s


def fmt_day(ts: float) -> str:
    d = to_et(ts)
    return f"{_DAYS[d.weekday()]}, {_MONTHS[d.month - 1]} {d.day}"


def fmt_range(ts: float, minutes: int) -> str:
    a, b = to_et(ts), to_et(ts + minutes * 60)
    same = (a.hour < 12) == (b.hour < 12)
    return f"{_hm(a, not same)} – {_hm(b)} ET"


def fmt_slot(ts: float, minutes: int) -> str:
    """'Tue, Oct 6 · 2:00 – 2:30 PM ET'"""
    return f"{fmt_day(ts)} · {fmt_range(ts, minutes)}"


# ---------- links ----------

def meeting_link(location: str) -> str | None:
    """The location as a clickable URL when it is exactly one https link to a well-known meeting host."""
    s = (location or "").strip()
    if not re.fullmatch(r"https://[^\s<>\"']+", s):
        return None
    try:
        u = urlparse(s)
        host = (u.hostname or "").lower()
        if u.username or u.password or u.port:
            return None
    except ValueError:
        return None
    for h in MEETING_HOSTS:
        if host == h or (h == "zoom.us" and host.endswith(".zoom.us")):
            return s
    return None


def location_html(location: str) -> str:
    link = meeting_link(location)
    if link:
        return f'<a href="{esc(link)}" target="_blank" rel="noopener noreferrer">{esc(link)}</a>'
    return esc(location)


# ---------- rules ----------

def _clean(s: str, n: int, multiline: bool = False) -> str:
    s = security._CONTROL_CHARS_RE.sub("", (s or "").replace("\r\n", "\n"))
    if not multiline:
        s = " ".join(s.split())
    return s.strip()[:n]


def scan_problem(text: str, location: str = "") -> str:
    """Why the text can't go in an interview card, or ''. Scam-level content (block or review band) and chat-app,
    shortened, raw-IP or FSU look-alike links are refused."""
    if not (text or location).strip():
        return ""
    r = msgcheck.check((text + "\n" + location).strip())
    if r["band"] in ("block", "review"):
        return "That text matches scam patterns (for example asking for money, bank details or a chat on another app), so it can't be sent."
    if any(f["rule_id"] in _BAD_LINK_RULES for f in msgcheck.link_findings(location + "\n" + text)):
        return "Use a meeting link from Zoom, Microsoft Teams or Google Meet, or your own company's site. Chat-app, shortened and look-alike links aren't allowed."
    return ""


def parse_slots(form, now: float | None = None) -> tuple[list[tuple[float, int]], str]:
    """Rows d1/t1/m1 .. d5/t5/m5 from the propose form. Returns (slots, error)."""
    now = time.time() if now is None else now
    out: list[tuple[float, int]] = []
    for i in range(1, MAX_SLOTS + 1):
        d, t, m = (str(form.get(f"d{i}", "") or "").strip(), str(form.get(f"t{i}", "") or "").strip(),
                   str(form.get(f"m{i}", "") or "30").strip())
        if not d and not t:
            continue
        if not (d and t):
            return [], f"Time {i} needs both a date and a start time."
        try:
            local = dt.datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
            minutes = int(m)
        except ValueError:
            return [], f"Time {i} isn't a valid date and time."
        if minutes not in DURATIONS:
            return [], "Pick a length of 15, 30, 45 or 60 minutes."
        ts = from_et(local)
        if ts < now + MIN_LEAD_MINUTES * 60:
            return [], f"Time {i} is in the past. Pick a time later than now."
        if ts > now + MAX_AHEAD_DAYS * 86400:
            return [], f"Time {i} is more than {MAX_AHEAD_DAYS} days away."
        if all(abs(ts - x) > 1 for x, _ in out):
            out.append((ts, minutes))
    if not out:
        return [], "Add at least one time."
    return sorted(out)[:MAX_SLOTS], ""


def _convo(conn, cid: int, user: dict) -> dict | None:
    c = store.row(conn, "SELECT * FROM conversations WHERE id = ?", (cid,))
    if not c or _side(user) not in (c["student_id"], c["employer_id"]):
        return None
    return c


def _side(user: dict) -> int:
    """A student's own id, or the org id for any member of a company's team (they all act for the company)."""
    return store.org_id(user) if user["role"] == "employer" else user["id"]


def _employer_to(conn, c: dict) -> int:
    """Who on the company's side gets interview emails: the member who last wrote in the thread, else the owner."""
    import messaging
    return messaging._employer_recipient(conn, c)


def can_propose(conn, c: dict, user: dict) -> tuple[bool, str]:
    import messaging
    if user["role"] != "employer" or _side(user) != c["employer_id"]:
        return False, "Only the employer in this conversation can propose interview times."
    if not store.employer_approved(conn, user["id"]):
        return False, "Scheduling opens once a reviewer approves your organization."
    return messaging.can_send(conn, c, user)


def _proposal(conn, cid: int, pid: int) -> dict | None:
    return store.row(conn, "SELECT * FROM interview_proposals WHERE id = ? AND conversation_id = ?", (pid, cid))


def _slots(conn, pid: int) -> list[dict]:
    return store.rows(conn, "SELECT * FROM interview_slots WHERE proposal_id = ? ORDER BY starts_at", (pid,))


def _chosen(conn, p: dict) -> dict | None:
    return store.row(conn, "SELECT * FROM interview_slots WHERE id = ? AND proposal_id = ?", (p["chosen_slot"] or 0, p["id"]))


def _event(conn, p: dict, text: str) -> None:
    now = time.time()
    conn.execute("INSERT INTO interview_events (proposal_id, conversation_id, text, created_at) VALUES (?,?,?,?)",
                 (p["id"], p["conversation_id"], text[:400], now))
    conn.execute("UPDATE conversations SET last_at = ?, student_hidden = 0, employer_hidden = 0 WHERE id = ?", (now, p["conversation_id"]))


def _names(conn, c: dict) -> tuple[str, str, str]:
    """(student name, employer name, role title) for emails and thread lines."""
    s = web.display_name(conn, c["student_id"])[0]
    e = web.display_name(conn, c["employer_id"])[0]
    job = c.get("subject") or ""
    if not job and c.get("job_id"):
        r = conn.execute("SELECT title FROM jobs WHERE id = ?", (c["job_id"],)).fetchone()
        job = r[0] if r else ""
    return s, e, job


def _email_of(conn, uid: int) -> str | None:
    r = conn.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
    return r[0] if r else None


_MAIL_FOOT = ("\n\nWe never put meeting links, addresses or message text in emails. If an email that looks like ours asks you to "
              "click a different link or send personal details, it isn't from us.")


def _mail(background: BackgroundTasks, conn, uid: int, subject: str, body: str) -> None:
    to = _email_of(conn, uid)
    if to:
        background.add_task(mailer.send, to, subject, body + _MAIL_FOOT)


# ---------- the helper other modules use ----------

def upcoming_interviews(conn, user_id: int, limit: int = 5) -> list[dict]:
    """Confirmed interviews for this user (student or employer) that haven't ended, soonest first.
    Each dict: proposal_id, conversation_id, starts_at, minutes, when, format, format_label, location, link,
    other_id, other_name, job_title, url, ics_url."""
    now = time.time()
    rows = store.rows(conn, """SELECT p.*, s.starts_at, s.minutes, c.subject, c.job_id FROM interview_proposals p
                               JOIN interview_slots s ON s.id = p.chosen_slot JOIN conversations c ON c.id = p.conversation_id
                               WHERE p.status = 'confirmed' AND (p.student_id = ? OR p.employer_id = ?) AND s.starts_at + s.minutes * 60 > ?
                               ORDER BY s.starts_at LIMIT ?""", (user_id, user_id, now, max(1, int(limit))))
    out = []
    for r in rows:
        other = r["employer_id"] if r["student_id"] == user_id else r["student_id"]
        out.append({"proposal_id": r["id"], "conversation_id": r["conversation_id"], "starts_at": r["starts_at"], "minutes": r["minutes"],
                    "when": fmt_slot(r["starts_at"], r["minutes"]), "format": r["format"], "format_label": FORMATS.get(r["format"], ""),
                    "location": r["location"], "link": meeting_link(r["location"]), "other_id": other,
                    "other_name": web.display_name(conn, other)[0], "job_title": r["subject"] or "",
                    "url": f"/messages/{r['conversation_id']}", "ics_url": f"/messages/{r['conversation_id']}/interview/{r['id']}/invite.ics"})
    return out


def upcoming_block(conn, user: dict) -> str:
    items = upcoming_interviews(conn, _side(user))
    if not items:
        return ""
    lis = "".join(
        f'<li><a class="iv-up-main" href="{esc(i["url"])}"><span class="iv-up-when">{esc(i["when"])}</span>'
        f'<span class="iv-up-who">{esc(i["other_name"])}{" · " + esc(i["job_title"]) if i["job_title"] else ""} · {esc(i["format_label"])}</span></a>'
        f'<a class="b sm ghost" href="{esc(i["ics_url"])}" download>{ui.icon("calendar", 14)} .ics</a></li>' for i in items)
    return (f'<section class="iv-up" aria-labelledby="iv-up-h"><h2 id="iv-up-h">{ui.icon("calendar", 16)} Upcoming interviews</h2>'
            f'<ul>{lis}</ul></section>')


# ---------- rendering ----------

_STATUS = {"open": ("Interview times proposed", "accent"), "confirmed": ("Interview confirmed", "ok"),
           "declined": ("None of these times worked", "warn"), "cancelled": ("Interview cancelled", "warn"),
           "rescheduled": ("Replaced by new times", "")}


def proposal_card(conn, c: dict, p: dict, user: dict) -> str:
    now = time.time()
    slots = _slots(conn, p["id"])
    chosen = _chosen(conn, p)
    is_student, is_emp = user["id"] == c["student_id"], user["role"] == "employer" and _side(user) == c["employer_id"]
    csrf = ui.user_csrf_input()
    base = f"/messages/{int(c['id'])}/interview/{int(p['id'])}"
    head, tone = _STATUS.get(p["status"], ("Interview", ""))
    fmt = FORMATS.get(p["format"], "Interview")
    top = (f'<div class="iv-top"><span class="iv-ic">{ui.icon("calendar", 18)}</span><div class="iv-h"><b>{esc(head)}</b>'
           f'<span class="iv-sub">{esc(fmt)} · Eastern Time</span></div>'
           f'<span class="pill {"ok" if tone == "ok" else "gold" if tone == "accent" else ""}">{esc(p["status"].capitalize())}</span></div>')
    if p["status"] in ("rescheduled",):
        return f'<div class="iv-card iv-muted" id="iv-{int(p["id"])}">{top}</div>'
    parts = [top]
    if p["status"] == "confirmed" and chosen:
        parts.append(f'<p class="iv-when">{esc(fmt_slot(chosen["starts_at"], chosen["minutes"]))}</p>')
    elif p["status"] == "open":
        lis = []
        for s in slots:
            past = s["starts_at"] <= now
            label = f'<span class="iv-d">{esc(fmt_day(s["starts_at"]))}</span><span class="iv-t">{esc(fmt_range(s["starts_at"], s["minutes"]))} · {int(s["minutes"])} min</span>'
            if is_student and not past:
                lis.append(f'<li><form method="post" action="{base}/pick" class="iv-pick">{csrf}<input type="hidden" name="slot" value="{int(s["id"])}">'
                           f'<button type="submit" class="iv-slot">{label}<span class="iv-go">Pick</span></button></form></li>')
            else:
                lis.append(f'<li><div class="iv-slot{" past" if past else ""}">{label}<span class="iv-go">{"Passed" if past else ""}</span></div></li>')
        parts.append(f'<ul class="iv-slots">{"".join(lis)}</ul>')
        if slots and all(s["starts_at"] <= now for s in slots):
            parts.append('<p class="iv-note small muted">All of these times have passed.</p>')
    elif p["status"] == "cancelled" and chosen:
        parts.append(f'<p class="iv-when iv-strike">{esc(fmt_slot(chosen["starts_at"], chosen["minutes"]))}</p>')
    if p["status"] in ("open", "confirmed") and p["location"]:
        lab = {"video": "Meeting link", "phone": "Phone", "in_person": "Where"}.get(p["format"], "Details")
        parts.append(f'<p class="iv-loc"><span class="iv-k">{lab}</span> <span class="iv-v">{location_html(p["location"])}</span></p>')
    if p["note"] and p["status"] in ("open", "confirmed"):
        parts.append(f'<p class="iv-msg">{esc(p["note"])}</p>')
    if p["status"] == "declined" and p["student_note"]:
        parts.append(f'<p class="iv-msg"><span class="iv-k">Note</span> {esc(p["student_note"])}</p>')
    acts = []
    if p["status"] == "confirmed" and chosen:
        acts.append(f'<a class="b sm" href="{base}/invite.ics" download>{ui.icon("calendar", 14)} Add to calendar (.ics)</a>')
    if is_student and p["status"] == "open":
        acts.append(f'<details class="iv-none"><summary class="b sm ghost">None of these work</summary>'
                    f'<form method="post" action="{base}/decline">{csrf}<label for="ivn-{int(p["id"])}">Note (optional)</label>'
                    f'<textarea id="ivn-{int(p["id"])}" name="note" maxlength="{STUDENT_NOTE_MAX}" rows="2" placeholder="For example: I\'m free weekday afternoons after 3."></textarea>'
                    '<button class="b sm sec" type="submit">Send</button></form></details>')
    if is_emp and p["status"] in ("open", "confirmed", "declined"):
        acts.append(f'<a class="b sm sec" href="/messages/{int(c["id"])}/interview?re={int(p["id"])}">{"Propose new times" if p["status"] == "declined" else "Reschedule"}</a>')
        if p["status"] != "declined":
            acts.append(f'<form method="post" action="{base}/cancel" class="navform">{csrf}<button class="b sm ghost" type="submit">Cancel interview</button></form>')
    if acts:
        parts.append(f'<div class="iv-acts">{"".join(acts)}</div>')
    return f'<div class="iv-card{" iv-ok" if p["status"] == "confirmed" else ""}" id="iv-{int(p["id"])}">{"".join(parts)}</div>'


def thread_items(conn, c: dict, user: dict) -> list[tuple[float, str]]:
    """Proposal cards and system lines for one conversation, as (time, html) to merge with its messages."""
    out = [(p["created_at"], proposal_card(conn, c, p, user))
           for p in store.rows(conn, "SELECT * FROM interview_proposals WHERE conversation_id = ? ORDER BY id", (c["id"],))]
    out += [(e["created_at"], f'<div class="iv-sys" role="note">{ui.icon("calendar", 13)} <span>{esc(e["text"])}</span></div>')
            for e in store.rows(conn, "SELECT * FROM interview_events WHERE conversation_id = ? ORDER BY id", (c["id"],))]
    return out


def propose_button(conn, c: dict, user: dict) -> str:
    if user["role"] != "employer" or not can_propose(conn, c, user)[0]:
        return ""
    return f'<a class="b sm" href="/messages/{int(c["id"])}/interview">{ui.icon("calendar", 14)} Propose interview times</a>'


# ---------- calendar file ----------

def _ics_text(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def ics(p: dict, slot: dict, summary: str, description: str) -> str:
    stamp = lambda ts: dt.datetime.fromtimestamp(ts, _UTC).strftime("%Y%m%dT%H%M%SZ")
    host = re.sub(r"^https?://", "", security.BASE_URL).split("/")[0] or "nolecareershield"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NoleCareerShield//Interviews//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:interview-{int(p['id'])}-{int(slot['id'])}@{host}", f"DTSTAMP:{stamp(time.time())}",
             f"DTSTART:{stamp(slot['starts_at'])}", f"DTEND:{stamp(slot['starts_at'] + slot['minutes'] * 60)}",
             f"SUMMARY:{_ics_text(summary)}", f"DESCRIPTION:{_ics_text(description)}"]
    if p["location"]:
        lines.append(f"LOCATION:{_ics_text(p['location'])}")
    link = meeting_link(p["location"])
    if link:
        lines.append(f"URL:{link}")
    lines += ["STATUS:CONFIRMED", "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Interview reminder", "TRIGGER:-PT30M", "END:VALARM",
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


# ---------- routes ----------

def _form_page(conn, c: dict, user: dict, v: dict | None = None, error: str = "", status: int = 200) -> HTMLResponse:
    v = v or {}
    name = web.display_name(conn, c["student_id"])[0]
    today = to_et(time.time()).date().isoformat()
    last = to_et(time.time() + MAX_AHEAD_DAYS * 86400).date().isoformat()
    rows = []
    for i in range(1, MAX_SLOTS + 1):
        m = str(v.get(f"m{i}") or "30")
        opts = "".join(f'<option value="{d}"{" selected" if str(d) == m else ""}>{d} min</option>' for d in DURATIONS)
        rows.append(f'<fieldset class="iv-row"><legend>Time {i}{" (optional)" if i > 1 else ""}</legend>'
                    f'<div><label for="d{i}">Date</label><input id="d{i}" type="date" name="d{i}" min="{today}" max="{last}" value="{esc(v.get(f"d{i}", ""))}"{" required" if i == 1 else ""}></div>'
                    f'<div><label for="t{i}">Start (ET)</label><input id="t{i}" type="time" name="t{i}" step="300" value="{esc(v.get(f"t{i}", ""))}"{" required" if i == 1 else ""}></div>'
                    f'<div><label for="m{i}">Length</label><select id="m{i}" name="m{i}">{opts}</select></div></fieldset>')
    fmt = v.get("format") or "video"
    chips = "".join(f'<label class="chk"><input type="radio" name="format" value="{k}"{" checked" if k == fmt else ""}><span>{esc(lab)}</span></label>'
                    for k, lab in FORMATS.items())
    re_id = int(v.get("re") or 0)
    err = ui.banner("warning", error) if error else ""
    body = (f'<a class="back" href="/messages/{int(c["id"])}">← Back to the conversation</a>' +
            ui.page_head("Reschedule the interview" if re_id else "Propose interview times",
                         f"Offer {name} up to {MAX_SLOTS} times. They pick one in Messages, and you both get the confirmed time by email with a calendar file.",
                         num="Messages") + err +
            f'<form class="card iv-form" method="post" action="/messages/{int(c["id"])}/interview">{ui.user_csrf_input()}'
            f'<input type="hidden" name="re" value="{re_id}">'
            f'<p class="iv-tz">{ui.icon("calendar", 15)} All times are Eastern Time ({TZ_NAME}).</p>{"".join(rows)}'
            f'<div class="form-field"><span class="lbl" id="fmt-l">Format</span><div class="checks" role="radiogroup" aria-labelledby="fmt-l">{chips}</div></div>'
            f'<div class="form-field"><label for="iv-loc">Meeting link, phone details or address</label>'
            '<p class="hint">Zoom, Microsoft Teams and Google Meet links are clickable for the student; anything else shows as plain text. '
            'For a phone call, say who calls whom. Don\'t ask for the student\'s phone number here; they can share it in a message.</p>'
            f'<input id="iv-loc" name="location" maxlength="{LOCATION_MAX}" value="{esc(v.get("location", ""))}" placeholder="https://zoom.us/j/… or 123 College Ave, Suite 4"></div>'
            f'<div class="form-field"><label for="iv-note">Note (optional)</label><textarea id="iv-note" name="note" maxlength="{NOTE_MAX}" rows="3" data-count '
            f'placeholder="Who they\'ll meet and what to prepare.">{esc(v.get("note", ""))}</textarea></div>'
            '<p class="small faint">The note and location are scanned like every message. Anything asking for money, bank details or a chat on another app is blocked.</p>'
            f'<div class="row"><button class="b" type="submit">{ui.icon("send", 15)} Send times</button><a class="b ghost" href="/messages/{int(c["id"])}">Cancel</a></div></form>')
    return web.page(body, "Propose interview times", active="/messages", js=True, status=status)


def _deny(msg: str, cid: int, status: int = 403) -> HTMLResponse:
    return web.page(ui.banner("info", msg) + f'<a class="b sec" href="/messages/{int(cid)}">Back to the conversation</a>',
                    "Interview", active="/messages", status=status)


@router.get("/messages/{cid}/interview", response_class=HTMLResponse)
def propose_form(cid: int, request: Request, re_: int = Query(0, alias="re")):
    user = web.require_user(request)
    with store.db() as conn:
        c = _convo(conn, cid, user)
        if not c:
            return web.page('<p class="empty" style="margin:40px 0">That conversation isn\'t available.</p>', "Messages", active="/messages", status=404)
        ok, why = can_propose(conn, c, user)
        if not ok:
            return _deny(why, cid)
        v = {}
        if re_:
            old = _proposal(conn, cid, re_)
            if old:
                v = {"re": old["id"], "format": old["format"], "location": old["location"], "note": old["note"]}
        return _form_page(conn, c, user, v)


@router.post("/messages/{cid}/interview", response_class=HTMLResponse)
async def propose(cid: int, request: Request, background: BackgroundTasks):
    user = web.require_user(request)
    form = await request.form()
    v = {k: str(form.get(k, "") or "") for k in ["re", "format", "location", "note"] + [f"{x}{i}" for i in range(1, MAX_SLOTS + 1) for x in "dtm"]}
    if not web.csrf_ok(request, str(form.get("csrf", "") or "")):
        return RedirectResponse(f"/messages/{int(cid)}/interview", status_code=303)
    security.enforce_key_limit(security.message_limiter, f"u{user['id']}", "sending messages")
    with store.db() as conn:
        c = _convo(conn, cid, user)
        if not c:
            return web.page('<p class="empty">That conversation isn\'t available.</p>', "Messages", active="/messages", status=404)
        ok, why = can_propose(conn, c, user)
        if not ok:
            return _deny(why, cid)
        fmt = v["format"] if v["format"] in FORMATS else ""
        location = _clean(v["location"], LOCATION_MAX)
        note = _clean(v["note"], NOTE_MAX, multiline=True)
        v["location"], v["note"] = location, note
        slots, err = parse_slots(form)
        if not err and not fmt:
            err = "Pick a format: video, phone or in person."
        if not err and fmt == "video" and not location:
            err = "Add the meeting link for the video call."
        if not err and fmt == "in_person" and not location:
            err = "Add the address for the in-person interview."
        if not err and fmt == "video" and location.lower().startswith("http://"):
            err = "Use an https:// meeting link."
        if not err:
            err = scan_problem(note, location)
        if err:
            return _form_page(conn, c, user, v, err, status=400)
        now = time.time()
        old = _proposal(conn, cid, int(v["re"] or 0)) if (v["re"] or "0").isdigit() and int(v["re"] or 0) else None
        # One live proposal per conversation: new times replace any open or confirmed one.
        live = store.rows(conn, "SELECT * FROM interview_proposals WHERE conversation_id = ? AND status IN ('open','confirmed','declined')", (cid,))
        for p in live:
            conn.execute("UPDATE interview_proposals SET status = 'rescheduled', updated_at = ? WHERE id = ?", (now, p["id"]))
        cur = conn.execute("INSERT INTO interview_proposals (conversation_id, employer_id, student_id, format, location, note, status, created_at, updated_at) "
                           "VALUES (?,?,?,?,?,?,'open',?,?)", (cid, c["employer_id"], c["student_id"], fmt, location, note, now, now))
        pid = cur.lastrowid
        for ts, minutes in slots:
            conn.execute("INSERT INTO interview_slots (proposal_id, starts_at, minutes) VALUES (?,?,?)", (pid, ts, minutes))
        p = store.row(conn, "SELECT * FROM interview_proposals WHERE id = ?", (pid,))
        sname, ename, job = _names(conn, c)
        again = bool(live or old)
        _event(conn, p, f"{ename} proposed {'new ' if again else ''}{len(slots)} interview time{'s' if len(slots) != 1 else ''}.")
        times = "\n".join(f"  - {fmt_slot(ts, m)}" for ts, m in slots)
        _mail(background, conn, c["student_id"], f"{ename} proposed {'new ' if again else ''}interview times",
              f"{ename} proposed {'new ' if again else ''}interview times{' for ' + job if job else ''} ({FORMATS[fmt].lower()}):\n\n{times}\n\n"
              f"All times are Eastern Time. Pick the one that works for you on NoleCareerShield: {security.BASE_URL}/messages/{int(cid)}")
    return RedirectResponse(f"/messages/{int(cid)}#iv-{pid}", status_code=303)


def _action(request: Request, cid: int, pid: int, csrf: str):
    user = web.require_user(request)
    if not web.csrf_ok(request, csrf):
        return user, None, None, RedirectResponse(f"/messages/{int(cid)}", status_code=303)
    return user, cid, pid, None


@router.post("/messages/{cid}/interview/{pid}/pick", response_class=HTMLResponse)
def pick(cid: int, pid: int, request: Request, background: BackgroundTasks, slot: int = Form(0), csrf: str = Form("")):
    import messaging
    user, _, _, bad = _action(request, cid, pid, csrf)
    if bad:
        return bad
    with store.db() as conn:
        c = _convo(conn, cid, user)
        p = _proposal(conn, cid, pid) if c else None
        if not c or not p:
            return web.page('<p class="empty">That interview isn\'t available.</p>', "Messages", active="/messages", status=404)
        if user["id"] != c["student_id"]:
            return _deny("Only the student in this conversation can pick a time.", cid)
        ok, why = messaging.can_send(conn, c, user)
        if not ok:
            return _deny(why, cid)
        if p["status"] != "open":
            return _deny("These times aren't open any more. Check the conversation for the latest.", cid, 409)
        s = store.row(conn, "SELECT * FROM interview_slots WHERE id = ? AND proposal_id = ?", (slot, pid))
        if not s:
            return _deny("Pick one of the proposed times.", cid, 400)
        if s["starts_at"] <= time.time():
            return _deny("That time has already passed. Pick another, or tell them none of these work.", cid, 400)
        now = time.time()
        conn.execute("UPDATE interview_proposals SET status = 'confirmed', chosen_slot = ?, updated_at = ? WHERE id = ?", (s["id"], now, pid))
        sname, ename, job = _names(conn, c)
        when = fmt_slot(s["starts_at"], s["minutes"])
        _event(conn, p, f"{sname} picked {when}. Interview confirmed.")
        fmt = FORMATS.get(p["format"], "Interview")
        url = f"{security.BASE_URL}/messages/{int(cid)}"
        for uid, other in ((c["student_id"], ename), (_employer_to(conn, c), sname)):
            _mail(background, conn, uid, f"Interview confirmed: {when}",
                  f"Your interview is confirmed.\n\nWhen: {when} ({TZ_NAME})\nFormat: {fmt}\nWith: {other}\n" + (f"Role: {job}\n" if job else "") +
                  f"\nThe meeting details and a calendar file (.ics) are in the conversation: {url}")
    return RedirectResponse(f"/messages/{int(cid)}#iv-{pid}", status_code=303)


@router.post("/messages/{cid}/interview/{pid}/decline", response_class=HTMLResponse)
def decline(cid: int, pid: int, request: Request, background: BackgroundTasks, note: str = Form(""), csrf: str = Form("")):
    import messaging
    user, _, _, bad = _action(request, cid, pid, csrf)
    if bad:
        return bad
    with store.db() as conn:
        c = _convo(conn, cid, user)
        p = _proposal(conn, cid, pid) if c else None
        if not c or not p:
            return web.page('<p class="empty">That interview isn\'t available.</p>', "Messages", active="/messages", status=404)
        if user["id"] != c["student_id"]:
            return _deny("Only the student in this conversation can answer these times.", cid)
        ok, why = messaging.can_send(conn, c, user)
        if not ok:
            return _deny(why, cid)
        if p["status"] != "open":
            return _deny("These times aren't open any more. Check the conversation for the latest.", cid, 409)
        text = _clean(note, STUDENT_NOTE_MAX, multiline=True)
        problem = scan_problem(text)
        if problem:
            return _deny(problem, cid, 400)
        conn.execute("UPDATE interview_proposals SET status = 'declined', student_note = ?, updated_at = ? WHERE id = ?", (text, time.time(), pid))
        sname, ename, job = _names(conn, c)
        _event(conn, p, f"{sname} said none of these times work{' and left a note' if text else ''}.")
        _mail(background, conn, _employer_to(conn, c), f"{sname} needs different interview times",
              f"{sname} said none of the interview times you proposed{' for ' + job if job else ''} work." +
              (" They left a note in the conversation." if text else "") +
              f"\n\nPropose new times on NoleCareerShield: {security.BASE_URL}/messages/{int(cid)}")
    return RedirectResponse(f"/messages/{int(cid)}#iv-{pid}", status_code=303)


@router.post("/messages/{cid}/interview/{pid}/cancel", response_class=HTMLResponse)
def cancel(cid: int, pid: int, request: Request, background: BackgroundTasks, csrf: str = Form("")):
    user, _, _, bad = _action(request, cid, pid, csrf)
    if bad:
        return bad
    with store.db() as conn:
        c = _convo(conn, cid, user)
        p = _proposal(conn, cid, pid) if c else None
        if not c or not p:
            return web.page('<p class="empty">That interview isn\'t available.</p>', "Messages", active="/messages", status=404)
        if user["role"] != "employer" or _side(user) != c["employer_id"]:
            return _deny("Only the employer can cancel an interview. If you can't make it, send them a message.", cid)
        if p["status"] not in ("open", "confirmed"):
            return RedirectResponse(f"/messages/{int(cid)}", status_code=303)
        conn.execute("UPDATE interview_proposals SET status = 'cancelled', updated_at = ? WHERE id = ?", (time.time(), pid))
        sname, ename, job = _names(conn, c)
        s = _chosen(conn, p) if p["status"] == "confirmed" else None
        when = fmt_slot(s["starts_at"], s["minutes"]) if s else ""
        _event(conn, p, f"{ename} cancelled the interview{' on ' + when if when else ''}.")
        _mail(background, conn, c["student_id"], f"{ename} cancelled the interview",
              f"{ename} cancelled the interview{' on ' + when if when else ''}{' for ' + job if job else ''}. "
              f"If you add it to your calendar, remove it.\n\nSee the conversation: {security.BASE_URL}/messages/{int(cid)}")
    return RedirectResponse(f"/messages/{int(cid)}", status_code=303)


@router.get("/messages/{cid}/interview/{pid}/invite.ics")
def invite_ics(cid: int, pid: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        c = _convo(conn, cid, user)
        p = _proposal(conn, cid, pid) if c else None
        s = _chosen(conn, p) if p and p["status"] == "confirmed" else None
        if not s:
            return Response("Not found", status_code=404, media_type="text/plain")
        sname, ename, job = _names(conn, c)
        other = ename if user["id"] == c["student_id"] else sname
        summary = f"Interview with {other}" + (f": {job}" if job else "")
        desc = (f"{FORMATS.get(p['format'], 'Interview')} scheduled on NoleCareerShield.\n"
                + (f"{p['note']}\n" if p["note"] else "") + f"Conversation: {security.BASE_URL}/messages/{int(cid)}")
        text = ics(p, s, summary, desc)
    return Response(text, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="interview-{int(pid)}.ics"', "Cache-Control": "no-store"})
