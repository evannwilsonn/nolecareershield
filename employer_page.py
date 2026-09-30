"""
Employer company pages (LinkedIn company page x Handshake employer page) and the employer
trust score.

Trust score: 0-100, higher is safer. It is built only from things this site can check:

    Verification   30   reviewer approval, email domain vs website, time since approval
    Listings       25   listings approved vs rejected, scam scans, any rejected as a scam or aggregator
    Conduct        20   messages held, flagged or warned about by the scanner, open reports, students who blocked them
    Responsiveness 15   share of student messages answered, typical reply time
    Profile        10   how complete the company profile is

A part with no history yet (no listings, no student messages) counts as neutral, not as zero,
so new employers start at "Building trust" rather than "Use caution". trust_from_signals() is
a pure function so the demo (demo/app.js) can mirror it exactly.
"""

from __future__ import annotations

import json
import statistics
import time
from urllib.parse import urlparse

from scam_detector.rules import FREE_MAIL

import events
import network
import store
import ui
import web
from ui import esc

WEIGHTS = {"verification": 30, "listings": 25, "conduct": 20, "responsiveness": 15, "profile": 10}
NAMES = {"verification": "Verification", "listings": "Listing record", "conduct": "Conduct with students",
         "responsiveness": "Responsiveness", "profile": "Profile"}
LABELS = [(85, "Highly trusted", "ok"), (70, "Trusted", "ok"), (50, "Building trust", ""), (0, "Use caution", "bad")]
PERKS = ["Paid", "Flexible hours", "Remote-friendly", "Mentorship", "Return offers", "Housing help", "Tuition help", "Networking events"]
PROFILE_FIELDS = [("website", "a website"), ("about", "an About section"), ("industry", "your industry"), ("size", "company size"),
                  ("location", "a location"), ("contact_name", "a contact name"), ("fsu_connection", "how you work with FSU students"),
                  ("tagline", "a tagline"), ("linkedin", "your LinkedIn page"), ("founded", "the year you were founded"),
                  ("hires_for", "the kinds of roles you hire for"), ("perks", "your perks")]


def domain_match(email: str, website: str) -> str:
    """'match' | 'free' | 'other'."""
    ed = (email or "").rsplit("@", 1)[-1].lower()
    host = (urlparse(website or "").hostname or "").lower().removeprefix("www.")
    if ed in FREE_MAIL:
        return "free"
    if host and (ed == host or ed.endswith("." + host) or host.endswith("." + ed)):
        return "match"
    return "other"


# ---------- signals from the database ----------

def signals(conn, uid: int, now: float | None = None) -> dict:
    now = now or time.time()
    p = store.employer_profile(conn, uid) or {}
    u = store.row(conn, "SELECT email FROM users WHERE id = ?", (uid,)) or {"email": ""}
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    jobs = store.rows(conn, "SELECT review_status, review_label, scam_status FROM jobs WHERE employer_id = ?", (uid,))
    decided = [j for j in jobs if j["review_status"] in ("approved", "rejected", "removed")]
    threads = store.rows(conn, "SELECT id FROM conversations WHERE employer_id = ? AND started_by = student_id", (uid,))
    replied, hours = 0, []
    for t in threads:
        ms = store.rows(conn, "SELECT sender_id, created_at FROM messages WHERE conversation_id = ? AND status = 'delivered' ORDER BY id LIMIT 200", (t["id"],))
        first = next((m for m in ms if m["sender_id"] != uid), None)
        reply = next((m for m in ms if m["sender_id"] == uid and first and m["created_at"] >= first["created_at"]), None)
        if reply:
            replied += 1
            hours.append((reply["created_at"] - first["created_at"]) / 3600)
    profile = {k: p.get(k) for k, _ in PROFILE_FIELDS}
    for k in ("hires_for", "perks"):
        profile[k] = store.jload(profile.get(k), [])
    return {
        "status": p.get("status") or "draft", "domain": domain_match(u["email"], p.get("website") or ""),
        "days_approved": (now - p["reviewed_at"]) / 86400 if p.get("status") == "approved" and p.get("reviewed_at") else 0,
        "listings": len(decided), "approved": sum(1 for j in decided if j["review_status"] == "approved"),
        "clear": sum(1 for j in decided if j["scam_status"] == "clear"),
        "scam_rejections": sum(1 for j in decided if j["review_label"] == "scam"),
        "leadgen_rejections": sum(1 for j in decided if j["review_label"] == "lead_gen"),
        "sent": one("SELECT COUNT(*) FROM messages WHERE sender_id = ?", uid),
        "held": one("SELECT COUNT(*) FROM messages WHERE sender_id = ? AND (status = 'held' OR scan_band = 'block')", uid),
        "flagged": one("SELECT COUNT(*) FROM messages WHERE sender_id = ? AND scan_band = 'review' AND status = 'delivered'", uid),
        "cautioned": one("SELECT COUNT(*) FROM messages WHERE sender_id = ? AND scan_band = 'caution' AND status = 'delivered'", uid),
        "reports": one("SELECT COUNT(*) FROM reports r JOIN conversations c ON r.target_type = 'conversation' AND c.id = r.target_id "
                       "WHERE c.employer_id = ? AND r.reporter_id = c.student_id AND r.resolved = 0", uid)
                   + one("SELECT COUNT(*) FROM reports r JOIN posts p ON r.target_type = 'post' AND p.id = r.target_id WHERE p.author_id = ? AND r.resolved = 0", uid),
        "blocks": one("SELECT COUNT(*) FROM conversations WHERE employer_id = ? AND blocked_by = student_id", uid),
        "threads": len(threads), "replied": replied, "reply_hours": sorted(hours), "profile": profile,
    }


# ---------- the score (pure) ----------

def _pct(x: float) -> int:
    return max(0, min(100, int(round(100 * x))))


def trust_from_signals(s: dict) -> dict:
    parts, tips = {}, []
    # Verification
    approval = {"approved": 1.0, "pending": 0.35}.get(s["status"], 0.0)
    dom = {"match": 1.0, "other": 0.6, "free": 0.2}[s["domain"]]
    age = 1.0 if s["days_approved"] >= 180 else 0.8 if s["days_approved"] >= 30 else 0.6 if approval == 1 else 0.3
    parts["verification"] = (_pct(0.6 * approval + 0.25 * dom + 0.15 * age),
                             "; ".join(x for x in ({"approved": "Approved by a NoleCareerShield reviewer", "pending": "Waiting for a reviewer"}.get(s["status"], "Not approved"),
                                                   {"match": "email matches their website", "other": "email domain differs from their website",
                                                    "free": "uses a personal email address"}[s["domain"]]) if x))
    if s["domain"] == "free":
        tips.append("Sign up with an email on your company's domain instead of a personal address.")
    # Listings
    if s["listings"]:
        base = 0.6 * s["approved"] / s["listings"] + 0.4 * s["clear"] / s["listings"]
        if s["leadgen_rejections"]:
            base -= 0.25
        if s["scam_rejections"]:
            base = min(base, 0.1)
        parts["listings"] = (_pct(base), f'{s["approved"]} of {s["listings"]} listings approved'
                             + (f'; {s["scam_rejections"]} rejected as a scam' if s["scam_rejections"] else "")
                             + (f'; {s["leadgen_rejections"]} rejected as an aggregator' if s["leadgen_rejections"] else ""))
    else:
        parts["listings"] = (60, "No listings reviewed yet")
        tips.append("Post a listing. Each approved listing builds your record.")
    # Conduct
    c = 1.0 - 0.35 * s["held"] - 0.2 * s["flagged"] - 0.1 * s["cautioned"] - 0.3 * s["reports"] - 0.15 * s["blocks"]
    bad = [x for x in (s["held"] and f'{s["held"]} message{"s" if s["held"] != 1 else ""} held by the scam scanner',
                       s["flagged"] and f'{s["flagged"]} flagged', s["cautioned"] and f'{s["cautioned"]} with warning signs',
                       s["reports"] and f'{s["reports"]} open report{"s" if s["reports"] != 1 else ""} from students',
                       s["blocks"] and f'blocked by {s["blocks"]} student{"s" if s["blocks"] != 1 else ""}') if x]
    parts["conduct"] = (_pct(c), "; ".join(bad) if bad else ("No scanner flags, reports or blocks" if s["sent"] else "No messages sent yet"))
    # Responsiveness
    if s["threads"]:
        rate = s["replied"] / s["threads"]
        med = statistics.median(s["reply_hours"]) if s["reply_hours"] else None
        speed = 0.0 if med is None else 1.0 if med <= 24 else 0.7 if med <= 72 else 0.4 if med <= 168 else 0.1
        parts["responsiveness"] = (_pct(0.6 * rate + 0.4 * speed), f'Answered {s["replied"]} of {s["threads"]} student messages'
                                   + (f"; usually within {reply_time(med)}" if med is not None else ""))
        if rate < 0.8:
            tips.append("Answer every student who messages you, even with a quick no.")
    else:
        parts["responsiveness"] = (60, "No student messages yet")
    # Profile
    have = [k for k, _ in PROFILE_FIELDS if s["profile"].get(k) and (k != "about" or len(s["profile"]["about"]) >= 40)]
    parts["profile"] = (_pct(len(have) / len(PROFILE_FIELDS)), f"{len(have)} of {len(PROFILE_FIELDS)} details filled in")
    missing = [label for k, label in PROFILE_FIELDS if k not in have]
    if missing:
        tips.append("Add " + ", ".join(missing[:3]) + " to your company profile.")
    score = round(sum(WEIGHTS[k] * parts[k][0] for k in WEIGHTS) / 100)
    if s["status"] != "approved":
        score = min(score, 49)                     # nobody reads as trusted before a person has reviewed them
    if s["scam_rejections"]:
        score = min(score, 30)
    if s["reports"] or s["flagged"]:
        score = min(score, 69)                     # an open report or a flagged message keeps them below "Trusted"
    if s["held"]:
        score = min(score, 49)                     # a message that matched scam-only patterns
    label, tone = next((n, t) for cut, n, t in LABELS if score >= cut)
    history = bool(s["listings"] or s["threads"])
    return {"score": score, "label": label, "tone": tone, "new": not history,
            "parts": [{"key": k, "name": NAMES[k], "weight": WEIGHTS[k], "score": parts[k][0], "detail": parts[k][1]} for k in WEIGHTS],
            "tips": tips[:4]}


def reply_time(hours: float | None) -> str:
    if hours is None:
        return ""
    if hours < 1:
        return "an hour"
    if hours < 24:
        return f"{int(hours) + 1} hours"
    days = int(hours // 24) + (1 if hours % 24 else 0)
    return f"{days} day{'s' if days != 1 else ''}"


def trust(conn, uid: int) -> dict:
    return trust_from_signals(signals(conn, uid))


# ---------- rendering ----------

def trust_pill(t: dict, href: str = "") -> str:
    inner = f'Trust {t["score"]} · {esc(t["label"])}'
    pill = f'<span class="pill {t["tone"]}" title="Employer trust score: 100 is the most trustworthy">{inner}</span>'
    return f'<a href="{esc(href)}" style="text-decoration:none">{pill}</a>' if href else pill


def trust_card(t: dict, owner: bool = False) -> str:
    parts = "".join(f'<div class="cat"><span>{esc(p["name"])}</span><div class="meter{" ok" if p["score"] >= 75 else " warn" if p["score"] < 45 else ""}">'
                    f'<i style="width:{p["score"]}%"></i></div><span>{p["score"]}</span><div class="why2">{esc(p["detail"])}</div></div>' for p in t["parts"])
    new = '<p class="small muted" style="margin-top:6px">New on NoleCareerShield, so part of this score is a neutral starting point.</p>' if t["new"] else ""
    tips = ("<h4 class=\"small\" style=\"margin:14px 0 6px\">Raise your score</h4><ul class=\"small\" style=\"margin:0 0 0 18px\">"
            + "".join(f"<li>{esc(x)}</li>" for x in t["tips"]) + "</ul>") if owner and t["tips"] else ""
    return (f'<section class="card" id="trust"><div class="phead"><h2>Trust score</h2></div><div class="fit" style="grid-template-columns:auto minmax(0,1fr)">'
            f'<div class="ring sm" style="--p:{t["score"]}"><b>{t["score"]}</b></div><div><div class="fitlabel" style="font-size:19px">{esc(t["label"])}</div>'
            f'<p class="small muted">Out of 100. Higher is safer.</p></div></div>{new}<div class="fitparts tparts">{parts}</div>'
            '<p class="small faint" style="margin-top:10px">Worked out from what this site can check: reviewer approval, email and website, how their listings were reviewed, '
            'scanner flags and reports on their messages, and how they answer students. It isn\'t a guarantee; still verify an employer yourself.</p>'
            f'{tips}</section>')


def hiring_stats(conn, uid: int, s: dict) -> dict:
    open_n = conn.execute("SELECT COUNT(*) FROM jobs WHERE employer_id = ? AND review_status = 'approved'", (uid,)).fetchone()[0]
    med = statistics.median(s["reply_hours"]) if s["reply_hours"] else None
    return {"open": open_n, "posted": s["listings"], "reply_rate": round(100 * s["replied"] / s["threads"]) if s["threads"] else None,
            "reply_time": reply_time(med), "since": s["days_approved"]}


def company_html(conn, p: dict, uid: int, viewer: dict, notice: str = "") -> str:
    owner = viewer["id"] == uid
    sig = signals(conn, uid)
    t = trust_from_signals(sig)
    hs = hiring_stats(conn, uid, sig)
    jobs = store.rows(conn, "SELECT id, title, category, work_type, location FROM jobs WHERE employer_id = ? AND review_status = 'approved' "
                            "ORDER BY created_at DESC LIMIT 20", (uid,))
    hires_for, perks = store.jload(p.get("hires_for"), []), store.jload(p.get("perks"), [])
    status_pill = {"approved": '<span class="pill ok">✓ Approved employer</span>', "pending": '<span class="pill warn">Waiting for review</span>',
                   "rejected": '<span class="pill bad">Not approved</span>', "suspended": '<span class="pill bad">Suspended</span>',
                   "draft": '<span class="pill">Profile not finished</span>'}.get(p.get("status") or "draft", "")
    meta = " · ".join(esc(x) for x in (p.get("industry"), p.get("size") and f"{p['size']} people", p.get("location"),
                                        p.get("founded") and f"Founded {p['founded']}") if x)
    links = "".join(f'<a href="{esc(p[k])}" target="_blank" rel="noopener noreferrer nofollow">{lbl} ↗</a>' for k, lbl in (("website", "Website"), ("linkedin", "LinkedIn")) if p.get(k))
    if owner:
        actions = '<div class="row"><a class="b sm sec" href="/profile/setup/1">Edit profile</a><a class="b sm ghost" href="/hiring">Your listings</a></div>'
    elif viewer["role"] == "student" and p.get("status") == "approved":
        actions = (f'<div class="row"><a class="b sm" href="/messages/new?to={uid}">{ui.icon("chat", 14)} Message</a>'
                   f'{network.follow_button(uid, network.is_following(conn, viewer["id"], uid), f"/company/{uid}")}</div>')
    else:
        actions = ""
    hero = (f'<section class="card phero"><div class="pbanner emp ph" aria-hidden="true" style="--ph:url({ui.media_url("arch-060.webp")})"></div><div class="pinfo"><span class="avatar xl emp">{ui.initials(p.get("company") or "?")}</span>'
            f'<div class="row between" style="align-items:flex-end;gap:14px"><div style="min-width:0"><h1>{esc(p.get("company") or "Your organization")}</h1>'
            + (f'<p class="headline">{esc(p["tagline"])}</p>' if p.get("tagline") else "")
            + f'<p class="school">{meta}</p><p class="where"><span class="plinks">{links}</span></p>'
            f'<div class="row" style="margin-top:10px">{status_pill}{trust_pill(t, "#trust")}'
            + (f'<span class="pill">{web.plural(network.follower_count(conn, uid), "follower")}</span>' if p.get("status") == "approved" else "")
            + f'</div></div>{actions}</div></div></section>')
    rate = f'{hs["reply_rate"]}%' if hs["reply_rate"] is not None else "—"
    since = ("New" if hs["since"] < 30 else f'{int(hs["since"] // 30)} month{"s" if hs["since"] >= 60 else ""}') if p.get("status") == "approved" else "Not yet approved"
    glance = (f'<section class="card"><div class="phead"><h2>Hiring at a glance</h2></div><div class="stats sm two">'
              f'<div class="stat"><div class="n">{hs["open"]}</div><div class="l">open listings</div></div>'
              f'<div class="stat"><div class="n">{hs["posted"]}</div><div class="l">listings reviewed</div></div>'
              f'<div class="stat"><div class="n">{rate}</div><div class="l">student messages answered</div></div>'
              f'<div class="stat"><div class="n" style="font-size:17px">{esc(hs["reply_time"] or "—")}</div><div class="l">typical reply time</div></div></div>'
              f'<p class="small muted" style="margin-top:10px">On NoleCareerShield: {esc(since)}</p></section>')
    contact = (f'<section class="card"><div class="phead"><h2>Contact</h2></div>{web.person(p["contact_name"], p.get("contact_title") or "", "emp")}</section>'
               if p.get("contact_name") else "")
    side = trust_card(t, owner) + glance + contact
    about = f'<section class="card pcard"><div class="phead"><h2>About</h2></div><p class="desc">{esc(p["about"])}</p></section>' if p.get("about") else ""
    fsu = (f'<section class="card pcard"><div class="phead"><h2>Working with FSU students</h2></div><p class="desc">{esc(p["fsu_connection"])}</p></section>'
           if p.get("fsu_connection") else "")
    roles = (f'<section class="card pcard"><div class="phead"><h2>Hires for</h2></div><div class="chips">{"".join(f"<span class=pill>{esc(x)}</span>" for x in hires_for)}</div></section>'
             if hires_for else "")
    perk_html = (f'<section class="card pcard"><div class="phead"><h2>Perks for student hires</h2></div><div class="chips">{"".join(f"<span class=chip>✓ {esc(x)}</span>" for x in perks)}</div></section>'
                 if perks else "")
    cards = "".join(f'<a class="job" href="/job/{int(j["id"])}"><div class="job-title">{esc(j["title"])}</div>'
                    f'<div class="job-meta"><span class="chip">{esc(j["category"])}</span><span class="chip">{esc(j["work_type"].title())}</span>'
                    + (f'<span class="chip">{esc(j["location"])}</span>' if j["location"] else "") + '</div></a>' for j in jobs)
    cards = cards or '<p class="small muted">No open listings right now.</p>'
    listings = f'<section class="card pcard"><div class="phead"><h2>Open listings</h2><span class="small faint">{len(jobs)}</span></div>{cards}</section>'
    main = about + fsu + roles + perk_html + events.upcoming_for_employer(conn, uid) + listings
    return notice + hero + f'<div class="pgrid"><aside class="pside">{side}</aside><div class="pmain">{main}</div></div>'
