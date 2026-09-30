"""
Events: info sessions, career fair tables, workshops and coffee chats from approved employers.

  * Approved employers create an event at /events/new. The text goes through the same scam scan as messages and posts
    (a "block" result is refused on the spot), and every event waits for a reviewer, like a listing (/admin/events).
    Editing the title, description or meeting link sends it back for review.
  * Students see upcoming approved events at /events (filters: type, this week / this month, my major), RSVP Going or
    Can't go, join a waitlist when it is full, download an .ics file, and cancel. RSVPing shares their name, major and
    class year with that employer, and the button says so.
  * The meeting link is shown only to students who are going (and to the employer). Only well-known meeting services
    (Zoom, Teams, Google Meet) are clickable; any other link is shown as text.
  * A reminder email goes out the day before (send_event_reminders(), run by the daily maintenance; each RSVP records
    when it was reminded, so it is sent once). Cancelling an event emails everyone who was going or waitlisted.
  * Approved upcoming events show in students' feed as event cards (feed_mix) and on the company page (upcoming_for_employer).

Times are stored as UTC epoch seconds and shown in America/New_York.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import css_events  # noqa: F401  (appends the event styles to ui.CSS)
import mailer
import msgcheck
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

KINDS = {"info_session": "Info session", "career_fair": "Career fair table", "workshop": "Workshop", "coffee_chat": "Coffee chat", "other": "Other"}
FORMATS = {"in_person": "In person", "virtual": "Virtual"}
DURATIONS = [30, 45, 60, 90, 120, 180, 240]
_DUR_LABEL = {30: "30 min", 45: "45 min", 60: "1 hour", 90: "1.5 hours", 120: "2 hours", 180: "3 hours", 240: "4 hours"}
MEETING_HOSTS = ("zoom.us", "teams.microsoft.com", "meet.google.com")
TITLE_MAX, DESC_MAX, LOC_MAX, URL_MAX = 120, 3000, 200, 300
MAX_MAJORS, MAJOR_LEN = 6, 60
CAPACITY_MAX = 5000
UPCOMING_CAP = 40            # upcoming events one employer can have at once
REMIND_WINDOW_H = 30         # the daily run reminds everyone going to an event that starts within this many hours
FEED_MAX = 3
_NEXT = re.compile(r"/(?:feed|events)(?:[/?][A-Za-z0-9_=&%/.-]{0,160})?")
_MAJOR = re.compile(r"[A-Za-z][A-Za-z &,.'/()-]{0,59}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def events_nav_item() -> tuple[str, str, str]:
    """The employer sidebar entry (icon, href, label); ui._EMPLOYER_NAV lists the same tuple under Hiring."""
    return ("calendar", "/events/manage", "Events")


# ---------- time (America/New_York) ----------

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                   # noqa: BLE001 - no tz database: fall back to the US rule below
    _ET = None


def _us_dst(utc: dt.datetime) -> bool:
    """US daylight time: second Sunday of March 2:00 local to first Sunday of November 2:00 local."""
    y = utc.year
    mar = dt.datetime(y, 3, 8) + dt.timedelta(days=(6 - dt.datetime(y, 3, 8).weekday()) % 7)
    nov = dt.datetime(y, 11, 1) + dt.timedelta(days=(6 - dt.datetime(y, 11, 1).weekday()) % 7)
    return mar + dt.timedelta(hours=7) <= utc.replace(tzinfo=None) < nov + dt.timedelta(hours=6)


def local(ts: float) -> dt.datetime:
    """A UTC timestamp as a naive datetime on the clock in Tallahassee."""
    if _ET:
        return dt.datetime.fromtimestamp(ts, _ET).replace(tzinfo=None)
    utc = dt.datetime.utcfromtimestamp(ts)
    return utc + dt.timedelta(hours=-4 if _us_dst(utc) else -5)


def to_ts(day: str, clock: str) -> float | None:
    """'2026-10-08', '18:30' (Eastern) -> UTC timestamp, or None when either isn't a real date/time."""
    try:
        d = dt.datetime.strptime(f"{day.strip()} {clock.strip()}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if _ET:
        return d.replace(tzinfo=_ET).timestamp()
    guess = (d + dt.timedelta(hours=5)).replace(tzinfo=dt.timezone.utc)
    if _us_dst(guess.replace(tzinfo=None)):
        guess -= dt.timedelta(hours=1)
    return guess.timestamp()


def _clock(d: dt.datetime) -> str:
    return d.strftime("%I:%M").lstrip("0") + (" AM" if d.hour < 12 else " PM")


def when_text(ev: dict, short: bool = False) -> str:
    """'Thu, Oct 8 · 6:00 – 7:00 PM ET'."""
    a = local(ev["starts_at"])
    b = local(ev["starts_at"] + 60 * int(ev["duration_min"]))
    day = a.strftime("%a, %b ") + str(a.day)
    if short:
        return f"{day} · {_clock(a)}"
    start = _clock(a)
    if a.date() == b.date() and (a.hour < 12) == (b.hour < 12):
        start = start[:-3]
    return f"{day} · {start} – {_clock(b)} ET"


def _week_end(now: float) -> float:
    d = local(now)
    end = dt.datetime(d.year, d.month, d.day) + dt.timedelta(days=7 - d.weekday())        # midnight after Sunday
    return to_ts(end.strftime("%Y-%m-%d"), "00:00") or now + 7 * 86400


def _month_end(now: float) -> float:
    d = local(now)
    nxt = dt.datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return to_ts(nxt.strftime("%Y-%m-%d"), "00:00") or now + 31 * 86400


# ---------- queries ----------

_LIVE = ("e.status = 'approved' AND e.starts_at + 60 * e.duration_min > ? "
         "AND e.employer_id IN (SELECT user_id FROM employer_profiles WHERE status = 'approved')")


def get(conn, eid: int) -> dict | None:
    ev = store.row(conn, "SELECT * FROM events WHERE id = ?", (eid,))
    if ev:
        ev["majors"] = store.jload(ev["majors"], [])
        ev["class_years"] = store.jload(ev["class_years"], [])
        ev["company"] = (store.employer_profile(conn, ev["employer_id"]) or {}).get("company") or "Employer"
    return ev


def _load(conn, sql: str, params=()) -> list[dict]:
    out = []
    for r in store.rows(conn, sql, params):
        r["majors"] = store.jload(r["majors"], [])
        r["class_years"] = store.jload(r["class_years"], [])
        r["company"] = (store.employer_profile(conn, r["employer_id"]) or {}).get("company") or "Employer"
        out.append(r)
    return out


def upcoming(conn, now: float | None = None, limit: int = 200) -> list[dict]:
    """Approved events that haven't ended, from employers that are still approved, soonest first."""
    return _load(conn, f"SELECT e.* FROM events e WHERE {_LIVE} ORDER BY e.starts_at LIMIT ?", (now or time.time(), limit))


def counts(conn, eid: int) -> dict:
    c = {"going": 0, "waitlist": 0, "not_going": 0}
    for st, n in conn.execute("SELECT status, COUNT(*) FROM event_rsvps WHERE event_id = ? GROUP BY status", (eid,)):
        c[st] = n
    return c


def my_rsvp(conn, eid: int, uid: int) -> str:
    r = conn.execute("SELECT status FROM event_rsvps WHERE event_id = ? AND student_id = ?", (eid, uid)).fetchone()
    return r[0] if r else ""


def _class_year(p: dict | None) -> str:
    t = ((p or {}).get("grad_term") or "").split()
    return t[-1] if t and t[-1].isdigit() else ""


def matches_major(ev: dict, p: dict | None) -> bool:
    m = ((p or {}).get("major") or "").strip().lower()
    return bool(m) and any(x.strip().lower() == m for x in ev["majors"])


def is_live(ev: dict, now: float | None = None) -> bool:
    return ev["status"] == "approved" and ev["starts_at"] + 60 * int(ev["duration_min"]) > (now or time.time())


def meeting_host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme == "https" and any(host == h or host.endswith("." + h) for h in MEETING_HOSTS)


def upcoming_for_employer(conn, employer_id: int, limit: int = 5) -> str:
    """The "Upcoming events" card on a company page ("" when there are none)."""
    evs = _load(conn, f"SELECT e.* FROM events e WHERE {_LIVE} AND e.employer_id = ? ORDER BY e.starts_at LIMIT ?",
                (time.time(), employer_id, limit))
    if not evs:
        return ""
    rows = "".join(_row(conn, ev, None) for ev in evs)
    return (f'<section class="card pcard"><div class="phead"><h2>Upcoming events</h2><span class="small faint">{len(evs)}</span></div>'
            f'<div class="ev-list tight">{rows}</div></section>')


# ---------- mail ----------

def _emails(conn, ids) -> dict[int, str]:
    ids = list(ids)
    if not ids:
        return {}
    return {r[0]: r[1] for r in conn.execute(f"SELECT id, email FROM users WHERE id IN ({','.join('?' * len(ids))})", ids)}


def send_all(outbox: list[tuple[str, str, str]]) -> None:
    for to, subject, body in outbox or []:
        mailer.send(to, subject, body)


def _where_line(ev: dict) -> str:
    return (f"Where: {ev['location']}" if ev["format"] == "in_person" else "Where: online. The meeting link is on the event page.")


def _page_link(ev: dict) -> str:
    return f"{security.BASE_URL}/events/{int(ev['id'])}"


def send_event_reminders(now: float | None = None) -> int:
    """Email everyone going to an event that starts within REMIND_WINDOW_H hours, once (event_rsvps.reminded_at).
    Safe to run as often as you like. Returns how many reminders went out."""
    now = now or time.time()
    out = []
    with store.db() as conn:
        due = store.rows(conn, "SELECT r.event_id, r.student_id FROM event_rsvps r JOIN events e ON e.id = r.event_id "
                               "WHERE r.status = 'going' AND r.reminded_at IS NULL AND e.status = 'approved' AND e.starts_at > ? AND e.starts_at <= ? "
                               "AND e.employer_id IN (SELECT user_id FROM employer_profiles WHERE status = 'approved')",
                         (now, now + REMIND_WINDOW_H * 3600))
        cache: dict = {}
        mails = _emails(conn, {d["student_id"] for d in due})
        for d in due:
            ev = cache.get(d["event_id"]) or get(conn, d["event_id"])
            cache[d["event_id"]] = ev
            conn.execute("UPDATE event_rsvps SET reminded_at = ? WHERE event_id = ? AND student_id = ? AND reminded_at IS NULL",
                         (now, d["event_id"], d["student_id"]))
            if d["student_id"] in mails:
                out.append((mails[d["student_id"]], f"Reminder: {ev['title']} is coming up",
                            f"You're going to {ev['title']} with {ev['company']}.\n\nWhen: {when_text(ev)}\n{_where_line(ev)}\n\n"
                            f"Event page: {_page_link(ev)}\n\nCan't make it? Cancel your RSVP on the event page so someone on the waitlist can take your spot."))
    send_all(out)
    return len(out)


def _promote(conn, ev: dict) -> list[tuple[str, str, str]]:
    """Move waitlisted students into open spots, oldest first. Returns the emails to send."""
    if not ev["capacity"]:
        ids = [r[0] for r in conn.execute("SELECT student_id FROM event_rsvps WHERE event_id = ? AND status = 'waitlist'", (ev["id"],))]
    else:
        free = ev["capacity"] - counts(conn, ev["id"])["going"]
        ids = [r[0] for r in conn.execute("SELECT student_id FROM event_rsvps WHERE event_id = ? AND status = 'waitlist' ORDER BY created_at, student_id LIMIT ?",
                                          (ev["id"], max(0, free)))]
    now = time.time()
    for sid in ids:
        conn.execute("UPDATE event_rsvps SET status = 'going', updated_at = ? WHERE event_id = ? AND student_id = ?", (now, ev["id"], sid))
    mails = _emails(conn, ids)
    return [(mails[s], f"You're in: {ev['title']}", f"A spot opened up and you're now going to {ev['title']} with {ev['company']}.\n\n"
             f"When: {when_text(ev)}\n{_where_line(ev)}\n\nEvent page: {_page_link(ev)}") for s in ids if s in mails and ev["status"] == "approved"]


def before_account_delete(conn, user_id: int) -> list[tuple[str, str, str]]:
    """An employer deleting their account cancels their upcoming events; everyone going or waitlisted is told.
    (store.delete_account then removes the events and every RSVP.) Returns the emails to send after the commit."""
    out = []
    for ev in _load(conn, "SELECT * FROM events WHERE employer_id = ? AND status IN ('approved','pending') AND starts_at > ?", (user_id, time.time())):
        out += _cancel(conn, ev, "The organization closed its NoleCareerShield account.")
    return out


def _cancel(conn, ev: dict, why: str = "") -> list[tuple[str, str, str]]:
    ids = [r[0] for r in conn.execute("SELECT student_id FROM event_rsvps WHERE event_id = ? AND status IN ('going','waitlist')", (ev["id"],))]
    conn.execute("UPDATE events SET status = 'cancelled', cancelled_at = ?, updated_at = ? WHERE id = ?", (time.time(), time.time(), ev["id"]))
    if ev["status"] != "approved":
        return []
    mails = _emails(conn, ids)
    return [(mails[s], f"Cancelled: {ev['title']}", f"{ev['company']} cancelled {ev['title']} ({when_text(ev)}).\n\n"
             + (why + "\n\n" if why else "") + "You don't need to do anything. Browse other events on NoleCareerShield.") for s in ids if s in mails]


# ---------- rendering ----------

def _date_block(ev: dict) -> str:
    a = local(ev["starts_at"])
    return (f'<span class="ev-date" aria-hidden="true"><small>{a.strftime("%b").upper()}</small><b>{a.day}</b>'
            f'<i>{a.strftime("%a")}</i></span>')


def _state_pill(state: str) -> str:
    return {"going": '<span class="pill ok">✓ Going</span>', "waitlist": '<span class="pill gold">On the waitlist</span>',
            "not_going": '<span class="pill">Can\'t go</span>'}.get(state, "")


def _status_pill(ev: dict) -> str:
    if ev["status"] == "approved" and not is_live(ev):
        return '<span class="pill">Ended</span>'
    return {"pending": '<span class="pill warn">Waiting for review</span>', "rejected": '<span class="pill bad">Not approved</span>',
            "cancelled": '<span class="pill bad">Cancelled</span>', "removed": '<span class="pill bad">Removed</span>',
            "approved": '<span class="pill ok">Live</span>'}.get(ev["status"], "")


def _spots(ev: dict, c: dict) -> str:
    if not ev["capacity"]:
        return f'{c["going"]} going'
    left = ev["capacity"] - c["going"]
    return f'{c["going"]} going · ' + (f"{left} spot{'s' if left != 1 else ''} left" if left > 0 else "Full, waitlist open")


def _spots_long(ev: dict, c: dict) -> str:
    if not ev["capacity"]:
        return f'No limit · {c["going"]} going'
    full = c["going"] >= ev["capacity"]
    return f'{c["going"]} of {ev["capacity"]} going' + (f' · full, {c["waitlist"]} on the waitlist' if full else "")


def _where(ev: dict) -> str:
    return esc(ev["location"]) if ev["format"] == "in_person" else "Virtual"


def rsvp_form(ev: dict, state: str, company: str, next_: str, compact: bool = False) -> str:
    """The RSVP control. Going/Waitlist -> a Cancel button; otherwise Going (or Join the waitlist) and Can't go."""
    csrf = ui.user_csrf_input()
    nxt = f'<input type="hidden" name="next" value="{esc(next_)}">'
    eid = int(ev["id"])
    if state in ("going", "waitlist"):
        return (f'<form method="post" action="/events/{eid}/cancel-rsvp" class="ev-rsvp">{csrf}{nxt}{_state_pill(state)}'
                f'<button class="b sm sec" type="submit">Cancel RSVP</button></form>')
    full = ev["capacity"] and ev.get("_going", 0) >= ev["capacity"]
    label = "Join the waitlist" if full else ("RSVP" if compact else "Going")
    consent = f"RSVPing shares your name, major and class year with {company}."
    no = "" if compact else (f'<button class="b sm sec" type="submit" name="status" value="not_going"'
                             f'{" aria-pressed=true" if state == "not_going" else ""}>Can\'t go</button>')
    return (f'<form method="post" action="/events/{eid}/rsvp" class="ev-rsvp">{csrf}{nxt}'
            f'<button class="b sm" type="submit" name="status" value="going" title="{esc(consent)}">{ui.icon("check", 14)} {label}</button>{no}'
            f'<span class="ev-consent">{esc(consent)}</span></form>')


def _row(conn, ev: dict, user: dict | None, state: str = "") -> str:
    """One event in a list: date block, type, title, company, time and place, and the viewer's RSVP state."""
    c = counts(conn, ev["id"])
    tags = "".join(f'<span class="chip">{esc(m)}</span>' for m in ev["majors"][:3])
    return (f'<a class="ev-row" href="/events/{int(ev["id"])}">{_date_block(ev)}<span class="ev-main">'
            f'<span class="ev-kind k-{esc(ev["kind"])}">{esc(KINDS.get(ev["kind"], "Event"))}</span>'
            f'<b class="ev-title">{esc(ev["title"])}</b><span class="ev-co">{esc(ev["company"])}</span>'
            f'<span class="ev-meta">{esc(when_text(ev, short=True))} · {_where(ev)} · {esc(_spots(ev, c))}</span>'
            + (f'<span class="ev-tags">{tags}</span>' if tags else "")
            + f'</span><span class="ev-side">{_state_pill(state)}</span></a>')


def feed_card(conn, ev: dict, user: dict, next_: str) -> str:
    """An event on the feed timeline: the date block sits in the avatar gutter; RSVP right on the card."""
    c = counts(conn, ev["id"])
    ev["_going"] = c["going"]
    state = my_rsvp(conn, ev["id"], user["id"])
    eid = int(ev["id"])
    ctl = rsvp_form(ev, state, ev["company"], next_, compact=True) if user["role"] == "student" else ""
    return (f'<article class="fd-post fd-ev" id="event-{eid}"><div class="fd-gut">{_date_block(ev)}</div><div class="fd-body">'
            f'<div class="fd-line"><span class="fd-who"><a class="fd-nm" href="/company/{int(ev["employer_id"])}">{esc(ev["company"])}</a>'
            f'<span class="fd-emp">Employer</span><span class="fd-sub">{esc(when_text(ev, short=True))}</span></span>'
            f'<span class="fd-kind k-event">{esc(KINDS.get(ev["kind"], "Event"))}</span></div>'
            f'<a class="ev-card-t" href="/events/{eid}">{esc(ev["title"])}</a>'
            f'<p class="ev-card-m">{ui.icon("calendar", 14)} {esc(when_text(ev))} · {_where(ev)} · {esc(_spots(ev, c))}</p>'
            f'<div class="ev-card-a">{ctl}<a class="ev-more" href="/events/{eid}">Details</a></div></div></article>')


def feed_mix(conn, user: dict, tab: str, posts: list[dict], render) -> str:
    """Posts rendered by `render`, with upcoming event cards mixed in for students. tab: 'feed' (Everyone, merged by when
    the event was approved), 'foryou' (events for the student's major first, placed near the top), '' (no events)."""
    html = [(p.get("created_at") or 0, render(p)) for p in posts]
    if user["role"] != "student" or tab not in ("feed", "foryou"):
        return "".join(h for _, h in html)
    evs = [e for e in upcoming(conn, limit=30) if my_rsvp(conn, e["id"], user["id"]) != "not_going"]
    if not evs:
        return "".join(h for _, h in html)
    nxt = "/feed" if tab == "feed" else "/feed?tab=foryou"
    if tab == "foryou":
        p = store.student_profile(conn, user["id"]) or {}
        yr = _class_year(p)
        evs.sort(key=lambda e: (-(4 * matches_major(e, p) + 2 * bool(yr and yr in e["class_years"])), e["starts_at"]))
        out = [h for _, h in html]
        for i, e in enumerate(evs[:FEED_MAX]):
            out.insert(min(len(out), i * 4), feed_card(conn, e, user, nxt))
        return "".join(out)
    cards = [(e.get("reviewed_at") or e["created_at"], feed_card(conn, e, user, nxt)) for e in evs[:FEED_MAX]]
    oldest = html[-1][0] if html else 0
    merged = sorted(html + [(max(k, oldest), h) for k, h in cards], key=lambda x: x[0], reverse=True)
    return "".join(h for _, h in merged)


def _meeting(ev: dict) -> str:
    url = ev["meeting_url"]
    if meeting_host_ok(url):
        return (f'<a class="b sm" href="{esc(url)}" target="_blank" rel="noopener noreferrer nofollow">{ui.icon("send", 14)} Join the meeting</a>'
                f' <span class="small faint">{esc(urlparse(url).hostname or "")}</span>')
    return (f'<code class="ev-url">{esc(url)}</code><p class="small muted" style="margin-top:4px">This link isn\'t from Zoom, Teams or Google Meet, '
            'so it isn\'t clickable. Check it with the employer before you open it.</p>')


def _detail(conn, ev: dict, user: dict, notice: str = "") -> str:
    eid = int(ev["id"])
    c = counts(conn, eid)
    ev["_going"] = c["going"]
    owner = store.org_id(user) == ev["employer_id"]
    state = my_rsvp(conn, eid, user["id"]) if user["role"] == "student" else ""
    a = local(ev["starts_at"])
    facts = [("calendar", "When", esc(when_text(ev))),
             ("home" if ev["format"] == "in_person" else "chat", "Where", esc(ev["location"]) if ev["format"] == "in_person" else "Virtual"),
             ("people", "Spots", esc(_spots_long(ev, c)))]
    if ev["majors"] or ev["class_years"]:
        facts.append(("user", "For", esc(", ".join(ev["majors"] + [f"Class of {y}" for y in ev["class_years"]]))))
    job = store.row(conn, "SELECT id, title FROM jobs WHERE id = ? AND " + store.live_where(), (ev["job_id"],)) if ev["job_id"] else None
    if job:
        facts.append(("jobs", "Related listing", f'<a href="/job/{int(job["id"])}">{esc(job["title"])}</a>'))
    fact_html = "".join(f'<div class="ev-fact">{ui.icon(i, 16)}<div><small>{esc(k)}</small><span>{v}</span></div></div>' for i, k, v in facts)
    live = is_live(ev)
    side = ""
    if user["role"] == "student":
        if not live:
            side = f'<p class="muted small">{"This event was cancelled." if ev["status"] == "cancelled" else "This event has ended."}</p>{_state_pill(state)}'
        elif not _ready(conn, user["id"]):
            side = ui.banner("info", "Add your name and major to your profile to RSVP. They are what the employer sees.") + '<a class="b sm" href="/profile/setup">Set up profile</a>'
        else:
            side = rsvp_form(ev, state, ev["company"], f"/events/{eid}")
            if state == "waitlist":
                side += '<p class="small muted" style="margin-top:8px">You\'ll get an email if a spot opens up.</p>'
        if state in ("going", "waitlist") or live:
            side += f'<p style="margin-top:12px"><a class="b sm ghost" href="/events/{eid}/event.ics">{ui.icon("calendar", 14)} Add to calendar (.ics)</a></p>'
    if ev["format"] == "virtual":
        if owner or (state == "going" and live):
            side += f'<div class="ev-join"><small>Meeting link</small>{_meeting(ev)}</div>'
        elif user["role"] == "student" and live:
            side += '<p class="small faint" style="margin-top:10px">The meeting link is shown here once you\'re going.</p>'
    msg = ""
    if user["role"] == "student" and live:
        msg = f'<a class="b sm ghost" href="/messages/new?to={int(ev["employer_id"])}">{ui.icon("chat", 14)} Message {esc(ev["company"])}</a>'
    head = (f'<a class="back" href="{"/events/manage" if owner else "/events"}">← {"Your events" if owner else "Events"}</a>'
            f'<section class="card ev-hero">{_date_block(ev)}<div class="ev-hero-t"><div class="row"><span class="ev-kind k-{esc(ev["kind"])}">{esc(KINDS.get(ev["kind"], "Event"))}</span>'
            f'{_status_pill(ev) if owner or ev["status"] != "approved" or not live else ""}</div><h1>{esc(ev["title"])}</h1>'
            f'<p class="ev-co"><a href="/company/{int(ev["employer_id"])}">{esc(ev["company"])}</a> · {esc(a.strftime("%A"))}</p></div></section>')
    body = (f'<div class="ev-grid"><div class="ev-mainc"><section class="card"><div class="ev-facts">{fact_html}</div></section>'
            f'<section class="card"><h2 class="ev-h">About this event</h2><p class="ev-desc">{esc(ev["description"])}</p>{msg}</section>'
            + (_owner_panel(conn, ev, c) if owner else "") +
            f'</div><aside class="ev-aside">' + (f'<section class="card ev-act">{side}</section>' if side else "") + '</aside></div>')
    return notice + head + body


def _ready(conn, uid: int) -> bool:
    p = store.student_profile(conn, uid)
    return bool(p and p.get("display_name") and p.get("major"))


def _owner_panel(conn, ev: dict, c: dict) -> str:
    import messaging
    eid = int(ev["id"])
    csrf = ui.user_csrf_input()
    rs = store.rows(conn, "SELECT r.*, s.display_name, s.major, s.grad_term FROM event_rsvps r JOIN student_profiles s ON s.user_id = r.student_id "
                          "WHERE r.event_id = ? AND r.status IN ('going','waitlist') ORDER BY r.status, r.created_at", (eid,))
    me = {"id": ev["employer_id"], "role": "employer"}
    rows = ""
    for r in rs:
        ok, _ = messaging.can_start(conn, me, r["student_id"])
        yr = _class_year(r)
        act = (f'<a class="b sm ghost" href="/messages/new?to={int(r["student_id"])}">{ui.icon("chat", 14)} Message</a>' if ok
               else '<span class="small faint" title="This student doesn\'t take messages from employers">No messages</span>')
        rows += (f'<tr><td><b>{esc(r["display_name"])}</b></td><td>{esc(r["major"])}</td><td>{esc("Class of " + yr if yr else "")}</td>'
                 f'<td>{_state_pill(r["status"])}</td><td>{act}</td></tr>')
    table = (f'<div class="ev-tablewrap"><table class="t"><tr><th>Name</th><th>Major</th><th>Year</th><th>RSVP</th><th></th></tr>{rows}</table></div>' if rows
             else '<p class="small muted">No RSVPs yet.</p>')
    acts = ""
    if ev["status"] in ("pending", "approved") and is_live(ev) or ev["status"] == "pending":
        acts = (f'<div class="row" style="margin-top:14px"><a class="b sm sec" href="/events/{eid}/edit">Edit</a>'
                f'<form method="post" action="/events/{eid}/cancel">{csrf}<button class="b sm danger" type="submit">Cancel event</button></form></div>'
                '<p class="small faint" style="margin-top:6px">Cancelling emails everyone who is going or waitlisted.</p>')
    return (f'<section class="card"><div class="row between"><h2 class="ev-h" style="margin:0">RSVPs</h2>'
            f'<span class="small muted">{c["going"]} going · {c["waitlist"]} waitlisted</span></div>'
            f'<p class="small muted" style="margin:6px 0 12px">Students who RSVP agree to share their name, major and class year with you. '
            'Message them only about this event or your openings.</p>' + table + acts + "</section>")


def ics(ev: dict, include_link: bool) -> str:
    def tx(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")

    def fold(line: str) -> str:
        out, b = [], line.encode()
        while len(b) > 74:
            cut = 74
            while cut and (b[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(b[:cut].decode())
            b = b" " + b[cut:]
        out.append(b.decode())
        return "\r\n".join(out)

    stamp = lambda ts: time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts))
    desc = ev["description"] + f"\n\nEvent page: {_page_link(ev)}"
    if include_link and ev["meeting_url"] and meeting_host_ok(ev["meeting_url"]):
        desc += f"\nMeeting link: {ev['meeting_url']}"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NoleCareerShield//Events//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
             f"UID:event-{int(ev['id'])}@nolecareershield", f"DTSTAMP:{stamp(time.time())}", f"DTSTART:{stamp(ev['starts_at'])}",
             f"DTEND:{stamp(ev['starts_at'] + 60 * int(ev['duration_min']))}", f"SUMMARY:{tx(ev['title'] + ' (' + ev['company'] + ')')}",
             f"DESCRIPTION:{tx(desc)}", f"LOCATION:{tx(ev['location'] if ev['format'] == 'in_person' else 'Online')}",
             f"URL:{_page_link(ev)}", "STATUS:" + ("CANCELLED" if ev["status"] == "cancelled" else "CONFIRMED"), "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


# ---------- the form ----------

def _years() -> list[str]:
    y = local(time.time()).year
    return [str(y + i) for i in range(0, 5)]


def _form(conn, uid: int, v: dict, error: str = "", eid: int = 0) -> str:
    csrf = ui.user_csrf_input()
    kind_opts = "".join(f'<option value="{k}"{" selected" if v.get("kind") == k else ""}>{esc(t)}</option>' for k, t in KINDS.items())
    dur_opts = "".join(f'<option value="{d}"{" selected" if str(v.get("duration", "60")) == str(d) else ""}>{_DUR_LABEL[d]}</option>' for d in DURATIONS)
    fmt = v.get("format") or "in_person"
    jobs = store.rows(conn, "SELECT id, title FROM jobs WHERE employer_id = ? AND " + store.live_where() + " ORDER BY created_at DESC LIMIT 50", (uid,))
    job_opts = '<option value="">None</option>' + "".join(f'<option value="{int(j["id"])}"{" selected" if str(v.get("job_id")) == str(j["id"]) else ""}>{esc(j["title"])}</option>' for j in jobs)
    years = "".join(f'<label class="chk"><input type="checkbox" name="class_years" value="{y}"{" checked" if y in (v.get("class_years") or []) else ""}><span>Class of {y}</span></label>' for y in _years())
    fmt_radio = "".join(f'<label class="chk"><input type="radio" name="format" value="{k}"{" checked" if fmt == k else ""}><span>{t}</span></label>' for k, t in FORMATS.items())
    err = ui.banner("warning", error) if error else ""
    action = f"/events/{eid}/edit" if eid else "/events/new"
    today = local(time.time()).strftime("%Y-%m-%d")
    return f"""{err}<form method="post" action="{action}" class="card ev-form">{csrf}
<div class="form-field"><label for="e-title">Title</label><input id="e-title" name="title" required maxlength="{TITLE_MAX}" value="{esc(v.get('title', ''))}" placeholder="Summer data internships: info session"></div>
<div class="grid2"><div class="form-field"><label for="e-kind">Type</label><select id="e-kind" name="kind">{kind_opts}</select></div>
<div class="form-field"><label for="e-job">Related listing (optional)</label><select id="e-job" name="job_id">{job_opts}</select></div></div>
<div class="form-field"><label for="e-desc">Description</label><p class="hint">What students will learn or do, who should come, and what to bring. Don't ask for payment or personal details.</p>
<textarea id="e-desc" name="description" required maxlength="{DESC_MAX}">{esc(v.get('description', ''))}</textarea></div>
<fieldset class="ev-fs"><legend>When <span class="faint small">(Eastern time)</span></legend><div class="ev-when">
<div class="form-field"><label for="e-date">Date</label><input id="e-date" type="date" name="date" required min="{today}" value="{esc(v.get('date', ''))}"></div>
<div class="form-field"><label for="e-time">Start time</label><input id="e-time" type="time" name="time" required step="900" value="{esc(v.get('time', ''))}"></div>
<div class="form-field"><label for="e-dur">Length</label><select id="e-dur" name="duration">{dur_opts}</select></div></div></fieldset>
<fieldset class="ev-fs"><legend>Format</legend><div class="checks" style="margin-bottom:12px">{fmt_radio}</div>
<div class="grid2"><div class="form-field"><label for="e-loc">Location (in person)</label><input id="e-loc" name="location" maxlength="{LOC_MAX}" value="{esc(v.get('location', ''))}" placeholder="Career Center, room 2"></div>
<div class="form-field"><label for="e-url">Meeting link (virtual)</label><input id="e-url" name="meeting_url" maxlength="{URL_MAX}" value="{esc(v.get('meeting_url', ''))}" placeholder="https://zoom.us/j/..."></div></div>
<p class="hint">Zoom, Microsoft Teams and Google Meet links are clickable for students who are going. Other links are shown as text.</p></fieldset>
<div class="grid2"><div class="form-field"><label for="e-cap">Capacity (optional)</label><input id="e-cap" name="capacity" inputmode="numeric" pattern="[0-9]*" maxlength="4" value="{esc(v.get('capacity', ''))}" placeholder="No limit"><p class="hint" style="margin-top:5px">When it's full, students can join a waitlist.</p></div>
<div class="form-field"><label for="e-majors">Majors (optional)</label><input id="e-majors" name="majors" maxlength="400" value="{esc(v.get('majors', ''))}" placeholder="Statistics, Computer Science"><p class="hint" style="margin-top:5px">Up to {MAX_MAJORS}, separated by commas. Everyone can still RSVP.</p></div></div>
<div class="form-field"><span class="lbl-like">Class years (optional)</span><div class="checks">{years}</div></div>
<p class="small muted">A reviewer approves every event before students see it{", and changing the title, description or meeting link sends it back for review" if eid else ""}.</p>
<div class="row" style="margin-top:12px"><button class="submit-btn" type="submit">{"Save changes" if eid else "Submit for review"}</button><a class="b sec" href="{f"/events/{eid}" if eid else "/events/manage"}">Cancel</a></div></form>"""


def _clean(conn, uid: int, f: dict) -> tuple[dict | None, str]:
    """Validate the form. Returns (fields for the table, "") or (None, reason)."""
    t = lambda k, n: _CTRL.sub("", (f.get(k) or "")).strip()[:n]
    title, desc = t("title", TITLE_MAX), _CTRL.sub("", (f.get("description") or "").replace("\r\n", "\n")).strip()[:DESC_MAX]
    if len(title) < 4:
        return None, "Give the event a title (at least 4 characters)."
    if len(desc) < 20:
        return None, "Describe the event in a sentence or two (at least 20 characters)."
    kind = f.get("kind") if f.get("kind") in KINDS else ""
    if not kind:
        return None, "Pick a type."
    ts = to_ts(f.get("date") or "", f.get("time") or "")
    if ts is None:
        return None, "Pick a date and a start time."
    if ts < time.time() + 30 * 60:
        return None, "Pick a start time at least 30 minutes from now."
    if ts > time.time() + 366 * 86400:
        return None, "Events can be posted up to a year ahead."
    try:
        dur = int(f.get("duration") or 60)
    except ValueError:
        dur = 0
    if dur not in DURATIONS:
        return None, "Pick a length."
    fmt = f.get("format") if f.get("format") in FORMATS else ""
    if not fmt:
        return None, "Pick in person or virtual."
    loc, url = t("location", LOC_MAX), t("meeting_url", URL_MAX)
    if fmt == "in_person":
        if len(loc) < 3:
            return None, "Add where the event is (building and room, or an address)."
        url = ""
    else:
        if url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?", url or ""):
            return None, "Add the meeting link (it must start with https://)."
        loc = ""
    cap_raw = t("capacity", 6)
    if cap_raw and not cap_raw.isdigit():
        return None, "Capacity is a number of students, or leave it blank for no limit."
    cap = int(cap_raw or 0)
    if cap > CAPACITY_MAX:
        return None, f"Capacity can be up to {CAPACITY_MAX}."
    majors = []
    for m in re.split(r"[,;\n]", f.get("majors") or ""):
        m = " ".join(m.split())
        if not m:
            continue
        if not _MAJOR.fullmatch(m):
            return None, f"Majors are names like Statistics or Computer Science ({m[:40]!r} isn't)."
        if m.lower() not in {x.lower() for x in majors}:
            majors.append(m)
    if len(majors) > MAX_MAJORS:
        return None, f"List up to {MAX_MAJORS} majors."
    years = [y for y in _years() if y in (f.get("class_years") or [])]
    job_id = None
    if (f.get("job_id") or "").isdigit():
        if not conn.execute("SELECT 1 FROM jobs WHERE id = ? AND employer_id = ? AND review_status = 'approved'", (int(f["job_id"]), uid)).fetchone():
            return None, "Pick one of your live listings, or None."
        job_id = int(f["job_id"])
    scan = msgcheck.check("\n".join(x for x in (title, desc, loc, url) if x))
    if scan["band"] == "block":
        why = "; ".join(x["title"] for x in scan["findings"][:2])
        return None, f"This event can't be posted because it matches scam patterns ({why}). Remove requests for payment, personal details or off-platform contact."
    return {"title": title, "kind": kind, "description": desc, "starts_at": ts, "duration_min": dur, "format": fmt, "location": loc, "meeting_url": url,
            "capacity": cap, "majors": json.dumps(majors), "class_years": json.dumps(years), "job_id": job_id, "scan_band": scan["band"],
            "scan_json": json.dumps([{"title": x["title"], "severity": x["severity"]} for x in scan["findings"][:5]])}, ""


async def _formdata(request: Request) -> dict:
    form = await request.form()
    out = {k: str(form.get(k) or "") for k in ("title", "kind", "description", "date", "time", "duration", "format", "location",
                                                  "meeting_url", "capacity", "majors", "job_id", "csrf")}
    out["class_years"] = [str(x) for x in form.getlist("class_years")][:10]
    return out


def _can_post(conn, user: dict) -> str:
    if not store.employer_approved(conn, user["id"]):
        return "Events open to employers once a reviewer approves your organization."
    return ""


# ---------- student routes ----------

FILTER_WHEN = [("", "Any time"), ("week", "This week"), ("month", "This month")]


def _events_url(kind: str = "", when: str = "", major: int = 0) -> str:
    q = [p for p in (f"type={kind}" if kind else "", f"when={when}" if when else "", "major=1" if major else "") if p]
    return "/events" + ("?" + "&".join(q) if q else "")


@router.get("/events", response_class=HTMLResponse)
def events_list(request: Request, type: str = "", when: str = "", major: int = 0):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "events")
    kind = type if type in KINDS else ""
    when = when if when in ("week", "month") else ""
    major = 1 if major and user["role"] == "student" else 0
    now = time.time()
    with store.db() as conn:
        if user["role"] == "employer" and _can_post(conn, user):
            return web.page(ui.page_head("Events", num="Career events") + ui.banner("info", _can_post(conn, user)), "Events", active="/events/manage")
        evs = upcoming(conn, now)
        p = store.student_profile(conn, user["id"]) if user["role"] == "student" else None
        if kind:
            evs = [e for e in evs if e["kind"] == kind]
        if when:
            end = _week_end(now) if when == "week" else _month_end(now)
            evs = [e for e in evs if e["starts_at"] < end]
        if major:
            evs = [e for e in evs if matches_major(e, p)]
        mine = {r[0]: r[1] for r in conn.execute("SELECT event_id, status FROM event_rsvps WHERE student_id = ?", (user["id"],))}
        going = [] if (kind or when or major) else [e for e in evs if mine.get(e["id"]) in ("going", "waitlist")]
        rows = "".join(_row(conn, e, user, mine.get(e["id"], "")) for e in evs if e not in going)
        mine_html = "".join(_row(conn, e, user, mine.get(e["id"], "")) for e in going)
    chips = "".join(f'<a class="chipf{" active" if kind == k else ""}" href="{esc(_events_url(k, when, major))}"{" aria-current=true" if kind == k else ""}>{esc(t)}</a>'
                    for k, t in [("", "All types")] + list(KINDS.items()))
    whens = "".join(f'<a class="chipf{" active" if when == k else ""}" href="{esc(_events_url(kind, k, major))}"{" aria-current=true" if when == k else ""}>{esc(t)}</a>'
                    for k, t in FILTER_WHEN)
    maj = ""
    if user["role"] == "student":
        label = f"My major{': ' + p['major'] if p and p.get('major') else ''}"
        maj = f'<a class="chipf{" active" if major else ""}" href="{esc(_events_url(kind, when, 0 if major else 1))}"{" aria-current=true" if major else ""}>{esc(label)}</a>'
    filters = (f'<div class="ev-filters"><div class="filter-row"><span class="label">Type</span>{chips}</div>'
               f'<div class="filter-row"><span class="label">When</span>{whens}{maj}</div></div>')
    empty = ('<div class="card empty ev-empty"><b>No events match</b><p class="small muted">'
             + ("Try another filter. " if kind or when or major else "")
             + ("Events with your major tagged show up under My major." if major else "When approved employers schedule info sessions and workshops, they show up here.")
             + "</p></div>")
    head = ui.page_head("Events", "Info sessions, career fair tables, workshops and coffee chats from employers our reviewers approved.", num="Career events")
    if user["role"] == "employer":
        head += '<p style="margin:-6px 0 16px"><a class="b sm" href="/events/manage">Your events</a></p>'
    yours = (f'<h2 class="ev-sec">You\'re going</h2><div class="ev-list">{mine_html}</div>' + ('<h2 class="ev-sec">Upcoming</h2>' if rows else '') if mine_html else "")
    return web.page(head + filters + yours + f'<div class="ev-list">{rows or ("" if mine_html else empty)}</div>', "Events",
                    active="/events" if user["role"] == "student" else "/events/manage")


@router.get("/events/new", response_class=HTMLResponse)
def new_form(request: Request):
    user = web.require_user(request, "employer")
    with store.db() as conn:
        why = _can_post(conn, user)
        body = ui.page_head("New event", "Info sessions, career fair tables, workshops and coffee chats for FSU students.", num="Events")
        body += ui.banner("info", why) if why else _form(conn, store.org_id(user), {"duration": "60", "format": "in_person", "kind": "info_session"})
    return web.page(body, "New event", active="/events/manage")


@router.post("/events/new", response_class=HTMLResponse)
async def create(request: Request):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "event_create")
    f = await _formdata(request)
    if not web.csrf_ok(request, f["csrf"]):
        return RedirectResponse("/events/new", status_code=303)
    with store.db() as conn:
        why = _can_post(conn, user)
        if why:
            return web.page(ui.banner("info", why), "New event", active="/events/manage", status=403)
        n = conn.execute("SELECT COUNT(*) FROM events WHERE employer_id = ? AND status IN ('pending','approved') AND starts_at > ?",
                         (store.org_id(user), time.time())).fetchone()[0]
        clean, err = _clean(conn, store.org_id(user), f) if n < UPCOMING_CAP else (None, f"You can have up to {UPCOMING_CAP} upcoming events at once.")
        if not clean:
            return web.page(ui.page_head("New event", num="Events") + _form(conn, store.org_id(user), f, err), "New event", active="/events/manage", status=400)
        now = time.time()
        cols = list(clean)
        cur = conn.execute(f"INSERT INTO events (employer_id, {', '.join(cols)}, status, created_at, updated_at) VALUES (?, {', '.join('?' * len(cols))}, 'pending', ?, ?)",
                           (store.org_id(user), *clean.values(), now, now))
        eid = cur.lastrowid
    mailer.send(user["email"], "We received your event", f"We received your event \"{clean['title']}\". A reviewer checks every event before students see it. "
                "We'll email you when it's live.")
    return RedirectResponse(f"/events/{eid}?saved=1", status_code=303)


@router.get("/events/manage", response_class=HTMLResponse)
def manage(request: Request):
    user = web.require_user(request, "employer")
    now = time.time()
    with store.db() as conn:
        why = _can_post(conn, user)
        evs = _load(conn, "SELECT * FROM events WHERE employer_id = ? AND status != 'removed' ORDER BY starts_at DESC LIMIT 200", (store.org_id(user),))
        up = sorted([e for e in evs if e["starts_at"] + 60 * e["duration_min"] > now and e["status"] in ("pending", "approved")], key=lambda e: e["starts_at"])
        past = [e for e in evs if e not in up]

        def card(e):
            c = counts(conn, e["id"])
            wl = f' · {c["waitlist"]} waitlist' if c["waitlist"] else ""
            return (f'<a class="ev-row" href="/events/{int(e["id"])}">{_date_block(e)}<span class="ev-main"><span class="ev-kind k-{esc(e["kind"])}">{esc(KINDS.get(e["kind"], "Event"))}</span>'
                    f'<b class="ev-title">{esc(e["title"])}</b><span class="ev-meta">{esc(when_text(e, short=True))} · {_where(e)}</span></span>'
                    f'<span class="ev-side">{_status_pill(e)}<span class="ev-n"><b>{c["going"]}</b> going{wl}</span></span></a>')
        up_html = "".join(card(e) for e in up)
        past_html = "".join(card(e) for e in past[:30])
    head = ui.page_head("Your events", "Info sessions, career fair tables, workshops and coffee chats. A reviewer approves each one before students see it.", num="Hiring")
    if why:
        return web.page(head + ui.banner("info", why), "Your events", active="/events/manage")
    body = (head + f'<div class="row" style="margin:-4px 0 18px"><a class="b" href="/events/new">{ui.icon("plus", 15)} New event</a>'
            '<a class="b sec" href="/events">All events</a></div>'
            + f'<h2 class="ev-sec">Upcoming</h2><div class="ev-list">{up_html or _NO_UPCOMING}</div>'
            + (f'<h2 class="ev-sec">Past and cancelled</h2><div class="ev-list">{past_html}</div>' if past_html else ""))
    return web.page(body, "Your events", active="/events/manage")


_NO_UPCOMING = ('<div class="card empty ev-empty"><b>No upcoming events</b>'
                '<p class="small muted">Host an info session or a coffee chat to meet FSU students.</p></div>')


def _visible(ev: dict | None, user: dict, conn) -> bool:
    if not ev:
        return False
    if store.org_id(user) == ev["employer_id"]:
        return ev["status"] != "removed"
    if ev["status"] == "approved" and store.employer_approved(conn, ev["employer_id"]):
        return user["role"] == "student" or store.employer_approved(conn, user["id"])
    # A cancelled event stays readable for the students who had RSVPed, so the link in their email works.
    return ev["status"] == "cancelled" and user["role"] == "student" and bool(my_rsvp(conn, ev["id"], user["id"]))


@router.get("/events/{eid}", response_class=HTMLResponse)
def detail(eid: int, request: Request, saved: int = 0, msg: str = ""):
    user = web.require_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "events")
    with store.db() as conn:
        ev = get(conn, eid)
        if not _visible(ev, user, conn):
            return web.page('<p class="empty" style="margin:40px 0">That event isn\'t available.</p>', "Event",
                            active="/events" if user["role"] == "student" else "/events/manage", status=404)
        notes = {"going": ("verified", "You're going. We'll email you a reminder the day before."),
                 "waitlist": ("info", "The event is full, so you're on the waitlist. We'll email you if a spot opens up."),
                 "not_going": ("info", "Got it, you can't go. The employer isn't told."),
                 "cancelled": ("info", "Your RSVP is cancelled."), "edited": ("verified", "Saved."),
                 "review": ("info", "Saved. Your changes go to a reviewer before students see the event again."),
                 "closed": ("info", "This event is cancelled. Everyone who was going or waitlisted was emailed."),
                 "ended": ("warning", "That event isn't taking RSVPs.")}
        notice = ui.banner(*notes[msg]) if msg in notes else ""
        if saved:
            notice = ui.banner("verified", "Submitted. A reviewer checks every event before students see it; we'll email you when it's live.")
        if ev["status"] == "cancelled" and store.org_id(user) != ev["employer_id"] and msg != "cancelled":
            notice += ui.banner("warning", "This event was cancelled by the employer.")
        if ev["status"] == "rejected" and ev["review_note"]:
            notice += ui.banner("warning", "A reviewer didn't approve this event: " + ev["review_note"])
        body = _detail(conn, ev, user, notice)
    return web.page(body, ev["title"], active="/events" if user["role"] == "student" else "/events/manage")


def _next(value: str, default: str) -> str:
    v = (value or "").strip()
    return v if _NEXT.fullmatch(v) else default


def _with_msg(url: str, msg: str) -> str:
    if url.startswith("/feed"):
        return url
    return url + ("&" if "?" in url else "?") + "msg=" + quote(msg)


@router.post("/events/{eid}/rsvp")
def rsvp(eid: int, request: Request, status: str = Form("going"), csrf: str = Form(""), next: str = Form("")):
    user = web.require_user(request, "student")
    security.enforce_rate_limit(request, security.general_limiter, "event_rsvp")
    back = _next(next, f"/events/{eid}")
    if not web.csrf_ok(request, csrf) or status not in ("going", "not_going"):
        return RedirectResponse(back, status_code=303)
    out = []
    with store.db() as conn:
        ev = get(conn, eid)
        if not ev or not is_live(ev) or not store.employer_approved(conn, ev["employer_id"]):
            return RedirectResponse(_with_msg(f"/events/{eid}", "ended"), status_code=303)
        if not _ready(conn, user["id"]):
            return RedirectResponse("/profile/setup", status_code=303)
        cur = my_rsvp(conn, eid, user["id"])
        now = time.time()
        if status == "going":
            if cur in ("going", "waitlist"):
                return RedirectResponse(_with_msg(back, cur), status_code=303)
            full = ev["capacity"] and counts(conn, eid)["going"] >= ev["capacity"]
            new = "waitlist" if full else "going"
        else:
            new = "not_going"
        conn.execute("INSERT INTO event_rsvps (event_id, student_id, status, created_at, updated_at) VALUES (?,?,?,?,?) "
                     "ON CONFLICT(event_id, student_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at, "
                     "created_at = excluded.created_at, reminded_at = NULL", (eid, user["id"], new, now, now))
        if cur == "going" and new != "going":
            out = _promote(conn, ev)
    send_all(out)
    return RedirectResponse(_with_msg(back, new), status_code=303)


@router.post("/events/{eid}/cancel-rsvp")
def cancel_rsvp(eid: int, request: Request, csrf: str = Form(""), next: str = Form("")):
    user = web.require_user(request, "student")
    back = _next(next, f"/events/{eid}")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(back, status_code=303)
    out = []
    with store.db() as conn:
        ev = get(conn, eid)
        cur = my_rsvp(conn, eid, user["id"]) if ev else ""
        conn.execute("DELETE FROM event_rsvps WHERE event_id = ? AND student_id = ?", (eid, user["id"]))
        if ev and cur == "going" and is_live(ev):
            out = _promote(conn, ev)
    send_all(out)
    return RedirectResponse(_with_msg(back, "cancelled"), status_code=303)


@router.get("/events/{eid}/event.ics")
def download_ics(eid: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        ev = get(conn, eid)
        if not _visible(ev, user, conn):
            return Response("Not found", status_code=404, media_type="text/plain")
        going = store.org_id(user) == ev["employer_id"] or my_rsvp(conn, eid, store.org_id(user)) == "going"
    return Response(ics(ev, going), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="nolecareershield-event-{int(eid)}.ics"', "Cache-Control": "no-store"})


# ---------- employer routes ----------

def _owned(conn, eid: int, user: dict) -> dict | None:
    ev = get(conn, eid)
    return ev if ev and ev["employer_id"] == store.org_id(user) and ev["status"] not in ("removed",) else None


def _values(ev: dict) -> dict:
    a = local(ev["starts_at"])
    return {"title": ev["title"], "kind": ev["kind"], "description": ev["description"], "date": a.strftime("%Y-%m-%d"), "time": a.strftime("%H:%M"),
            "duration": str(ev["duration_min"]), "format": ev["format"], "location": ev["location"], "meeting_url": ev["meeting_url"],
            "capacity": str(ev["capacity"] or ""), "majors": ", ".join(ev["majors"]), "class_years": ev["class_years"], "job_id": str(ev["job_id"] or "")}


@router.get("/events/{eid}/edit", response_class=HTMLResponse)
def edit_form(eid: int, request: Request):
    user = web.require_user(request, "employer")
    with store.db() as conn:
        ev = _owned(conn, eid, user)
        if not ev or ev["status"] not in ("pending", "approved") or _can_post(conn, user):
            return RedirectResponse(f"/events/{eid}", status_code=303)
        body = ui.page_head("Edit event", num="Events") + _form(conn, store.org_id(user), _values(ev), eid=eid)
    return web.page(body, "Edit event", active="/events/manage")


@router.post("/events/{eid}/edit", response_class=HTMLResponse)
async def edit(eid: int, request: Request):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "event_create")
    f = await _formdata(request)
    if not web.csrf_ok(request, f["csrf"]):
        return RedirectResponse(f"/events/{eid}", status_code=303)
    out = []
    with store.db() as conn:
        ev = _owned(conn, eid, user)
        if not ev or ev["status"] not in ("pending", "approved") or _can_post(conn, user):
            return RedirectResponse(f"/events/{eid}", status_code=303)
        clean, err = _clean(conn, store.org_id(user), f)
        if not clean:
            return web.page(ui.page_head("Edit event", num="Events") + _form(conn, store.org_id(user), f, err, eid), "Edit event", active="/events/manage", status=400)
        rereview = ev["status"] == "approved" and any(clean[k] != ev[k] for k in ("title", "description", "meeting_url"))
        moved = ev["status"] == "approved" and any(clean[k] != ev[k] for k in ("starts_at", "duration_min", "format", "location"))
        sets = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE events SET {sets}, updated_at = ?{', status = ' + repr('pending') if rereview else ''} WHERE id = ?",
                     (*clean.values(), time.time(), eid))
        if ev["status"] == "approved" and not rereview:
            ev.update(clean, majors=json.loads(clean["majors"]), class_years=json.loads(clean["class_years"]))
            out = _promote(conn, ev)                       # a bigger capacity lets waitlisted students in
        if moved:
            new = get(conn, eid)
            ids = [r[0] for r in conn.execute("SELECT student_id FROM event_rsvps WHERE event_id = ? AND status IN ('going','waitlist')", (eid,))]
            conn.execute("UPDATE event_rsvps SET reminded_at = NULL WHERE event_id = ?", (eid,))
            mails = _emails(conn, ids)
            out += [(mails[s], f"Updated: {new['title']}", f"{new['company']} changed the time or place of {new['title']}.\n\nWhen: {when_text(new)}\n"
                     f"{_where_line(new)}\n\nEvent page: {_page_link(new)}") for s in ids if s in mails]
    send_all(out)
    return RedirectResponse(f"/events/{eid}?msg={'review' if rereview else 'edited'}", status_code=303)


@router.post("/events/{eid}/cancel")
def cancel(eid: int, request: Request, csrf: str = Form("")):
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/events/{eid}", status_code=303)
    out = []
    with store.db() as conn:
        ev = _owned(conn, eid, user)
        if ev and ev["status"] in ("pending", "approved"):
            out = _cancel(conn, ev)
    send_all(out)
    return RedirectResponse(f"/events/{eid}?msg=closed", status_code=303)


# ---------- reviewer ----------

REJECT_NOTES = {"scam": "It matched scam patterns.", "not_fsu": "It isn't relevant to FSU students.",
                "details": "The time, place or description was unclear.", "other": "It didn't meet our guidelines."}


def pending_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM events WHERE status = 'pending'").fetchone()[0]


@router.get("/admin/events", response_class=HTMLResponse)
def admin_events(session: str | None = Cookie(default=None)):
    import admin_extra
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = admin_extra._csrf(session)
    with store.db() as conn:
        evs = _load(conn, "SELECT * FROM events WHERE status = 'pending' ORDER BY created_at LIMIT 200")
        live = _load(conn, "SELECT * FROM events WHERE status = 'approved' AND starts_at > ? ORDER BY starts_at LIMIT 100", (time.time(),))
        emails = _emails(conn, {e["employer_id"] for e in evs + live})
    rej = "".join(f'<button class="btn-reject" name="note" value="{k}" type="submit">Reject: {esc(k.replace("_", " "))}</button>' for k in REJECT_NOTES)
    cards = ""
    for e in evs:
        flags = "".join(f'<div class="finding {esc(x.get("severity", "note"))}"><b>{esc(x.get("title", ""))}</b></div>' for x in store.jload(e["scan_json"], []))
        where = esc(e["location"]) if e["format"] == "in_person" else (f'Virtual · {esc(e["meeting_url"])}' + ("" if meeting_host_ok(e["meeting_url"]) else ' <span class="pill warn">not a known meeting service</span>'))
        aud = ", ".join(e["majors"] + [f"Class of {y}" for y in e["class_years"]])
        cards += f"""<div class="rev-card"><div class="row between"><div><div class="job-title">{esc(e['title'])}</div>
<div class="job-co">{esc(e['company'])} · {esc(emails.get(e['employer_id'], ''))}</div></div><span class="pill warn">{esc(KINDS.get(e['kind'], ''))} · scan: {esc(e['scan_band'])}</span></div>
<p class="small" style="margin-top:6px"><b>{esc(when_text(e))}</b> · {where}{f' · capacity {int(e["capacity"])}' if e['capacity'] else ''}{f' · for {esc(aud)}' if aud else ''}</p>{flags}
<div class="detail-desc" style="font-size:14px;background:var(--canvas);padding:10px 12px;border-radius:8px;white-space:pre-wrap">{esc(e['description'])}</div>
<div class="rev-actions"><form method="post" action="/admin/events/{int(e['id'])}/approve">{csrf}<button class="btn-approve" type="submit">Approve</button></form>
<form method="post" action="/admin/events/{int(e['id'])}/reject" style="display:flex;gap:8px;flex-wrap:wrap">{csrf}{rej}</form></div></div>"""
    rows = "".join(f'<tr><td><b>{esc(e["title"])}</b><div class="small faint">{esc(e["company"])}</div></td><td class="small">{esc(when_text(e, short=True))}</td>'
                   f'<td><form method="post" action="/admin/events/{int(e["id"])}/remove">{csrf}<button class="b sm danger" type="submit">Remove</button></form></td></tr>' for e in live)
    body = ('<p class="lead">Employer events wait here, like listings. Approve one only when it is a real event for FSU students with a clear time and place. '
            'Changing the title, description or meeting link sends an event back here.</p>'
            + (cards or '<div class="empty">No events waiting.</div>')
            + (f'<h3 class="sec">Upcoming live events</h3><div class="card"><table class="t">{rows}</table></div>' if rows else ""))
    return admin_extra._page(body, "Events", "/admin/events")


@router.post("/admin/events/{eid}/{action}")
def admin_event_action(eid: int, action: str, request: Request, session: str | None = Cookie(default=None), csrf: str = Form(""), note: str = Form("")):
    import admin_extra
    if not admin_extra._gate(session, csrf) or action not in ("approve", "reject", "remove"):
        return RedirectResponse("/admin/events", status_code=303)
    security.enforce_rate_limit(request, security.general_limiter, "admin_action")
    out = []
    with store.db() as conn:
        ev = get(conn, eid)
        if ev:
            to = _emails(conn, [ev["employer_id"]]).get(ev["employer_id"])
            now = time.time()
            if action == "approve" and ev["status"] == "pending":
                conn.execute("UPDATE events SET status = 'approved', reviewed_at = ?, review_note = '' WHERE id = ?", (now, eid))
                ev["status"] = "approved"
                out = _promote(conn, ev)
                if to:
                    out.append((to, f"Your event is live: {ev['title']}", f"A reviewer approved \"{ev['title']}\" ({when_text(ev)}). FSU students can now see it and RSVP.\n\n"
                                f"See who's going: {_page_link(ev)}"))
            elif action == "reject" and ev["status"] == "pending":
                why = REJECT_NOTES.get(note, REJECT_NOTES["other"])
                conn.execute("UPDATE events SET status = 'rejected', reviewed_at = ?, review_note = ?, updated_at = ? WHERE id = ?", (now, why, now, eid))
                if to:
                    out.append((to, f"Your event wasn't approved: {ev['title']}", f"A reviewer didn't approve \"{ev['title']}\". {why}"))
            elif action == "remove" and ev["status"] == "approved":
                out = _cancel(conn, ev, "A NoleCareerShield reviewer took the event down.")
                conn.execute("UPDATE events SET status = 'removed' WHERE id = ?", (eid,))
    send_all(out)
    return RedirectResponse("/admin/events", status_code=303)
