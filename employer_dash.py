"""
The employer's home (a hiring dashboard) and the "Page stats" card on their own company page.

Dashboard, top to bottom:
  * a compact greeting with the three quick actions (Post a job, Find students, Open messages)
  * Needs your attention: new applicants, student messages waiting for a reply, listings about to
    expire (only when jobs.expires_at exists), what the company profile is missing (from the trust tips)
  * the candidate pipeline across every listing (hiring.STAGES)
  * one row per listing: students who viewed, Apply clicks, applicants, average match %
  * upcoming events, only when an `events` table exists

Page stats (owner only): company page views (students only, one per student per day, table
company_views), followers and how many followed in the last 30 days, listing views, and the majors of
students viewing the listings. Majors appear only once at least MAJORS_MIN distinct students have
viewed; counts are rounded and a major with a single student is folded into "Other majors", so no
one student can be picked out. Employers never see who.

Everything here only reads other modules' tables (hiring, messaging, network); demo/app.js mirrors it
(employerHome, pageStats).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import statistics
import time

import css_employer  # noqa: F401  (appends the dashboard styles to ui.CSS)
import employer_page
import fit
import hiring
import store
import ui
from ui import esc

MAJORS_MIN = 3            # distinct students before "Majors looking at your listings" shows
EXPIRY_WARN_DAYS = 7
APPLICANT_SOURCES = ("applied", "messaged")
ROWS_MAX = 8


def _plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


def _cols(conn, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def preview_link(job_id: int, cls: str = "b sm ghost") -> str:
    """The employer's own listing, as a student sees it."""
    return f'<a class="{cls}" href="/job/{int(job_id)}">Preview as students see it</a>'


# ---------- company page views ----------

def record_company_view(conn, employer_id: int, viewer: dict) -> None:
    """Students only; the owner and other employers aren't counted. One row per student per day."""
    if viewer.get("role") != "student" or viewer.get("id") == employer_id:
        return
    conn.execute("INSERT OR IGNORE INTO company_views (employer_id, viewer_id, day) VALUES (?,?,?)",
                 (employer_id, viewer["id"], _day()))


def round_count(n: int) -> str:
    """Counts shown to employers are rounded so small groups can't be singled out."""
    return "under 5" if n < 5 else f"about {int(5 * round(n / 5))}"


def page_stats(conn, uid: int, now: float | None = None) -> dict:
    now = now or time.time()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    month = _day(now - 30 * 86400)
    majors = store.rows(conn, "SELECT sp.major AS major, COUNT(DISTINCT v.user_id) AS n FROM job_views v "
                              "JOIN jobs j ON j.id = v.job_id JOIN student_profiles sp ON sp.user_id = v.user_id "
                              "WHERE j.employer_id = ? AND sp.major != '' GROUP BY sp.major ORDER BY n DESC, sp.major", (uid,))
    students = one("SELECT COUNT(DISTINCT v.user_id) FROM job_views v JOIN jobs j ON j.id = v.job_id "
                   "JOIN student_profiles sp ON sp.user_id = v.user_id WHERE j.employer_id = ? AND sp.major != ''", uid)
    return {"views_30": one("SELECT COUNT(*) FROM company_views WHERE employer_id = ? AND day >= ?", uid, month),
            "views_all": one("SELECT COUNT(*) FROM company_views WHERE employer_id = ?", uid),
            "followers": one("SELECT COUNT(*) FROM follows WHERE employer_id = ?", uid),
            "followers_30": one("SELECT COUNT(*) FROM follows WHERE employer_id = ? AND created_at >= ?", uid, now - 30 * 86400),
            "listing_views": one("SELECT COUNT(*) FROM (SELECT DISTINCT v.job_id, v.user_id FROM job_views v JOIN jobs j ON j.id = v.job_id "
                                 "WHERE j.employer_id = ?)", uid),
            "majors": fold_majors([(r["major"], r["n"]) for r in majors], students)}


def fold_majors(rows: list[tuple[str, int]], students: int, top: int = 4) -> list[tuple[str, str, int]] | None:
    """(major, rounded count, share %) or None below the privacy floor. Shared with the demo (majorsOf)."""
    if students < MAJORS_MIN:
        return None
    named = [(m, n) for m, n in rows if n >= 2][:top]
    other = students - sum(n for _, n in named)
    out = [(m, round_count(n), round(100 * n / students)) for m, n in named]
    if other > 0:
        out.append(("Other majors", round_count(other), round(100 * other / students)))
    return out


def page_stats_card(st: dict) -> str:
    grow = f'+{st["followers_30"]} in the last 30 days' if st["followers_30"] else "No new followers in the last 30 days"
    cells = (f'<div class="ps-c"><b>{st["views_30"]}</b><span>company page views</span><em>last 30 days · {st["views_all"]} all time</em></div>'
             f'<div class="ps-c"><b>{st["followers"]}</b><span>followers</span><em>{esc(grow)}</em></div>'
             f'<div class="ps-c"><b>{st["listing_views"]}</b><span>listing views</span><em>students who opened a listing</em></div>')
    if st["majors"] is None:
        majors = (f'<p class="small muted">Majors show once at least {MAJORS_MIN} students have viewed your listings. '
                  'We only ever show rounded totals, never who.</p>')
    else:
        majors = '<ul class="ps-maj">' + "".join(
            f'<li><span class="ps-m">{esc(m)}</span><span class="ps-bar" aria-hidden="true"><i style="width:{max(4, pct)}%"></i></span>'
            f'<span class="ps-v">{esc(n)}</span></li>' for m, n, pct in st["majors"]) + "</ul>"
    return (f'<section class="card pcard ps" id="page-stats"><div class="phead"><h2>Page stats</h2><span class="small faint">Only you see this</span></div>'
            f'<div class="ps-grid">{cells}</div><h3 class="ps-h">Majors looking at your listings</h3>{majors}'
            '<p class="small faint" style="margin-top:10px">Views count FSU students only, once per student per day. Totals only; you never see which students viewed.</p></section>')


# ---------- the dashboard ----------

def _expiry(v) -> float | None:
    """jobs.expires_at as epoch seconds, whether it is stored as a number or an ISO date."""
    if v in (None, ""):
        return None
    try:
        x = float(v)
        return x / 1000 if x > 1e12 else x
    except (TypeError, ValueError):
        pass
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()
    except ValueError:
        return None


def _in_days(days: int) -> str:
    return "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"


def profile_gap(tips: list[str]) -> str:
    """'a tagline, your LinkedIn page and your perks' from the trust card's "Add ... to your company profile." tip."""
    tip = next((t for t in tips if t.startswith("Add ") and t.endswith(" to your company profile.")), "")
    if not tip:
        return ""
    parts = tip[4:-len(" to your company profile.")].split(", ")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def awaiting_reply(conn, uid: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM conversations c WHERE c.employer_id = ? AND c.blocked_by IS NULL AND c.employer_hidden = 0 AND "
        "(SELECT m.sender_id FROM messages m WHERE m.conversation_id = c.id AND m.status = 'delivered' ORDER BY m.id DESC LIMIT 1) = c.student_id",
        (uid,)).fetchone()[0]


def _events(conn, uid: int, now: float) -> list[dict] | None:
    """Upcoming events this employer hosts (approved or waiting for review), with RSVP counts."""
    import events
    rows = store.rows(conn, "SELECT * FROM events WHERE employer_id = ? AND status IN ('approved','pending') AND starts_at >= ? "
                            "ORDER BY starts_at LIMIT 5", (uid, now - 3600))
    return [{"id": r["id"], "title": r["title"], "at": r["starts_at"], "when": events.when_text(r, short=True),
             "going": events.counts(conn, r["id"]).get("going", 0), "pending": r["status"] == "pending"} for r in rows]


def data(conn, user: dict, now: float | None = None) -> dict:
    now = now or time.time()
    uid = store.org_id(user)
    p = store.employer_profile(conn, uid) or {}
    jobs = store.rows(conn, "SELECT * FROM jobs WHERE employer_id = ? AND review_status IN ('approved','pending') "
                            "ORDER BY review_status = 'approved' DESC, id DESC LIMIT 100", (uid,))
    cands = store.rows(conn, "SELECT job_id, student_id, stage, source FROM candidates WHERE employer_id = ?", (uid,))
    stages = {k: 0 for k, _ in hiring.STAGES}
    for c in cands:
        if c["stage"] in stages:
            stages[c["stage"]] += 1
    new_apps = [c for c in cands if c["stage"] == "new" and c["source"] in APPLICANT_SOURCES]
    rows = []
    for j in jobs[:ROWS_MAX]:
        s = hiring.job_stats(conn, j)
        apps = [c for c in cands if c["job_id"] == j["id"] and c["source"] in APPLICANT_SOURCES]
        pcts = []
        for c in apps[:200]:
            prof = store.student_profile(conn, c["student_id"])
            if prof:
                pcts.append(fit.fit_score(j, prof)["percent"])
        rows.append({"id": j["id"], "title": j["title"], "status": j["review_status"], "views": s["views"], "clicks": s["clicks"],
                     "applicants": len(apps), "match": round(statistics.mean(pcts)) if pcts else None,
                     "new": sum(1 for c in apps if c["stage"] == "new")})
    expiring = []
    if "expires_at" in _cols(conn, "jobs"):
        for j in jobs:
            t = _expiry(j.get("expires_at"))
            if j["review_status"] == "approved" and t is not None and now <= t <= now + EXPIRY_WARN_DAYS * 86400:
                expiring.append({"id": j["id"], "title": j["title"], "days": int((t - now) // 86400)})
    t = employer_page.trust(conn, uid)
    return {"company": p.get("company") or "", "status": p.get("status") or "draft", "status_note": p.get("status_note") or "",
            "new_apps": len(new_apps), "new_job": new_apps[0]["job_id"] if new_apps and len({c["job_id"] for c in new_apps}) == 1 else None,
            "awaiting": awaiting_reply(conn, uid), "expiring": expiring, "gap": profile_gap(t["tips"]),
            "pending": sum(1 for j in jobs if j["review_status"] == "pending"), "live": sum(1 for j in jobs if store.visible_listing(j)),
            "stages": stages, "rows": rows, "more": max(0, len(jobs) - ROWS_MAX), "events": _events(conn, uid, now)}


STATUS_ITEM = {
    "draft": ("warn", "Finish your company profile so a reviewer can approve you", "/profile/setup", "Finish profile"),
    "pending": ("", "Your organization is waiting for a reviewer. Messaging and the student directory open once you're approved", "/profile", "View profile"),
    "rejected": ("warn", "Your profile wasn't approved. Update it and send it again", "/profile/setup/1", "Update profile"),
    "suspended": ("warn", "Your account is suspended. Contact us if you think this is a mistake", "/about", "Contact"),
}


def queue(d: dict) -> list[tuple[str, str, str, str, str]]:
    """(tone, icon, text html, href, action) in the order an employer should handle them."""
    items = []
    if d["status"] in STATUS_ITEM:
        tone, text, href, act = STATUS_ITEM[d["status"]]
        items.append((tone, "shield", esc(text + (": " + d["status_note"] if d["status"] == "rejected" and d["status_note"] else "") + "."), href, act))
    if d["new_apps"]:
        href = f'/hiring/{int(d["new_job"])}?tab=candidates' if d["new_job"] else "/hiring"
        items.append(("hot", "people", f'<b>{esc(_plural(d["new_apps"], "new applicant"))}</b> to review', href, "Review"))
    if d["awaiting"]:
        items.append(("hot", "chat", f'<b>{esc(_plural(d["awaiting"], "student message"))}</b> waiting for a reply', "/messages", "Reply"))
    for e in d["expiring"]:
        items.append(("warn", "jobs", f'<b>{esc(e["title"])}</b> expires {_in_days(e["days"])}', f'/hiring/{int(e["id"])}', "Manage"))
    if d["gap"]:
        items.append(("", "user", f'Your company profile is missing <b>{esc(d["gap"])}</b>', "/profile/setup/1", "Add them"))
    if d["pending"]:
        items.append(("", "check", f'{esc(_plural(d["pending"], "listing"))} waiting for review. Nothing is published until a person approves it', "/hiring", "See status"))
    return items


def _hello_word(hour: int) -> str:
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


def html(d: dict, hello: str, date: str) -> str:
    """The dashboard markup (demo/app.js employerHome builds the same)."""
    h = lambda href: f'href="{esc(href)}"'
    items = queue(d)
    n_hot = sum(1 for it in items if it[0] in ("hot", "warn"))
    sub = (f"{_plural(n_hot, 'thing needs', 'things need')} you today." if n_hot else "You're all caught up.") + \
        f" {_plural(d['live'], 'live listing')}."
    head = (f'<section class="ed-hello"><div class="ed-hi"><div class="eyebrow">Employer · {esc(date)}</div>'
            f'<h1>{esc(hello)}{"," if d["company"] else "."} <em>{esc(d["company"])}</em></h1><p>{esc(sub)}</p></div>'
            f'<nav class="ed-quick" aria-label="Quick actions"><a class="b" {h("/post")}>{ui.icon("plus", 16)} Post a job</a>'
            f'<a class="b sec" {h("/talent")}>{ui.icon("people", 16)} Find students</a><a class="b sec" {h("/messages")}>{ui.icon("chat", 16)} Open messages</a></nav></section>')
    if items:
        lis = "".join(f'<li class="ed-act {tone}"><a {h(href)}><span class="ed-ic">{ui.icon(ic, 17)}</span><span class="ed-t">{text}</span>'
                      f'<span class="ed-go">{esc(act)} →</span></a></li>' for tone, ic, text, href, act in items)
        q_body = f'<ul class="ed-acts">{lis}</ul>'
    else:
        q_body = f'<p class="ed-clear">{ui.icon("check", 18)} Nothing waiting on you. New applicants and messages show up here.</p>'
    q = (f'<section class="card ed-queue" aria-labelledby="ed-q"><div class="phead"><h2 id="ed-q">Needs your attention</h2>'
         f'{f"<span class=ed-badge>{n_hot}</span>" if n_hot else ""}</div>{q_body}</section>')
    total = sum(d["stages"].values())
    steps = "".join(f'<div class="pstep{" has" if d["stages"][k] else ""}"><span class="n">{d["stages"][k]}</span><span class="l">{esc(v)}</span></div>'
                    for k, v in hiring.STAGES)
    pipe = (f'<section class="card ed-pipe" aria-labelledby="ed-p"><div class="phead"><h2 id="ed-p">Candidate pipeline</h2>'
            f'<span class="small faint">{esc(_plural(total, "candidate"))}</span></div><div class="pipe" aria-label="Candidates by stage, all listings">{steps}</div>'
            '<p class="small faint">Across all your listings. Stages and notes are private to your organization.</p></section>')
    if d["rows"]:
        tone = {"approved": ("ok", "Live"), "pending": ("warn", "In review")}
        rows = "".join(
            f'<div class="ed-row"><div class="ed-ti"><a class="ed-name" href="/hiring/{int(r["id"])}">{esc(r["title"])}</a>'
            f'<span class="pill {tone[r["status"]][0]}">{tone[r["status"]][1]}</span>'
            + (f'<span class="pill gold">{r["new"]} new</span>' if r["new"] else "") + '</div>'
            f'<div class="ed-m"><b>{r["views"]}</b><span>viewed</span></div><div class="ed-m"><b>{r["clicks"]}</b><span>Apply clicks</span></div>'
            f'<div class="ed-m"><b>{r["applicants"]}</b><span>applicants</span></div>'
            f'<div class="ed-m"><b>{str(r["match"]) + "%" if r["match"] is not None else "—"}</b><span>avg match</span></div>'
            f'<div class="ed-ac">{preview_link(r["id"], "ed-pv") if r["status"] == "approved" else ""}</div></div>' for r in d["rows"])
        more = f'<p class="small muted" style="margin-top:10px">{d["more"]} more on <a {h("/hiring")}>Your listings</a>.</p>' if d["more"] else ""
        lst = (f'<section class="card ed-list" aria-labelledby="ed-l"><div class="phead"><h2 id="ed-l">Your listings</h2><a class="small ed-all" {h("/hiring")}>Manage all →</a></div>'
               f'<div class="ed-rows">{rows}</div>{more}<p class="small faint" style="margin-top:10px">Views and Apply clicks are totals; you never see which students viewed.</p></section>')
    else:
        lst = (f'<section class="card ed-list"><div class="phead"><h2>Your listings</h2></div><div class="empty">No listings yet. '
               f'<a {h("/post")}>Post your first job</a>; every one is scam-checked and approved by a person.</div></section>')
    ev = ""
    if d["events"] is not None:
        inner = ("".join(f'<li><a {h("/events/%d" % int(e["id"]))}><b>{esc(e["title"])}</b></a><span>{esc(e["when"])} · '
                         f'{e["going"]} going{" · in review" if e["pending"] else ""}</span></li>' for e in d["events"])
                 if d["events"] else "")
        ev = (f'<section class="card ed-events"><div class="phead"><h2>Upcoming events</h2><a class="small ed-all" {h("/events/manage")}>Manage events →</a></div>'
              + (f'<ul class="ed-ev">{inner}</ul>' if inner else '<p class="small muted">Nothing scheduled. <a ' + h('/events/new') + '>Host an info session or a coffee chat</a> for FSU students.</p>') + '</section>')
    return head + f'<div class="ed-grid">{q}{pipe}{lst}{ev}</div>'


def dashboard(user: dict) -> str:
    from datetime import datetime
    now = datetime.now()
    with store.db() as conn:
        d = data(conn, user)
    return html(d, _hello_word(now.hour), now.strftime("%A, %B %-d"))
