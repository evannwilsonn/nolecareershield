"""
Connections and follows.

  * Students connect with other FSU students: send a request (with an optional one-line note), the other side accepts
    or declines. Connections show up on profiles as counts and mutuals, and power "people you may know".
  * Students follow approved employers. Followed companies' listings get their own filter on the jobs page.
    Employers see how many students follow them, never who.

There are no student-to-student messages: this is a network, not another inbox, so nobody gets a new place to be
contacted by strangers. Requests are limited, the note goes through the same scam scan as every message, a declined
request can't be re-sent, and students can turn requests off entirely (Profile setup, "Let other students connect").
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import msgcheck
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

NOTE_LEN = 200
PENDING_CAP = 50           # outgoing requests waiting at once
SUGGEST_POOL = 300
SUGGEST_SHOW = 12
TABS = [("connections", "Connections"), ("requests", "Requests"), ("discover", "People you may know"), ("following", "Following")]


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _next(value: str, default: str) -> str:
    v = (value or "").strip()
    return v if v.startswith("/") and not v.startswith("//") and "\\" not in v and len(v) < 200 else default


# ---------- queries ----------

def state(conn, me: int, other: int) -> str:
    """none | sent | received | connected | declined (they turned my request down) | self."""
    if me == other:
        return "self"
    a, b = _pair(me, other)
    r = conn.execute("SELECT status, requested_by FROM connections WHERE user_a = ? AND user_b = ?", (a, b)).fetchone()
    if not r:
        return "none"
    if r[0] == "accepted":
        return "connected"
    if r[0] == "declined":
        return "declined" if r[1] == me else "none"       # the decliner may still reach out themselves
    return "sent" if r[1] == me else "received"


def connection_ids(conn, uid: int) -> list[int]:
    out = []
    for a, b in conn.execute("SELECT user_a, user_b FROM connections WHERE status = 'accepted' AND (user_a = ? OR user_b = ?)", (uid, uid)):
        out.append(b if a == uid else a)
    return out


def connection_count(conn, uid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM connections WHERE status = 'accepted' AND (user_a = ? OR user_b = ?)", (uid, uid)).fetchone()[0]


def mutual_ids(conn, a: int, b: int) -> list[int]:
    return sorted(set(connection_ids(conn, a)) & set(connection_ids(conn, b)))


def incoming_count(conn, uid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM connections WHERE status = 'pending' AND requested_by != ? AND (user_a = ? OR user_b = ?)",
                        (uid, uid, uid)).fetchone()[0]


def is_following(conn, student_id: int, employer_id: int) -> bool:
    return bool(conn.execute("SELECT 1 FROM follows WHERE student_id = ? AND employer_id = ?", (student_id, employer_id)).fetchone())


def follower_count(conn, employer_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM follows WHERE employer_id = ?", (employer_id,)).fetchone()[0]


def followed_ids(conn, student_id: int) -> list[int]:
    return [r[0] for r in conn.execute("SELECT employer_id FROM follows WHERE student_id = ? ORDER BY created_at DESC", (student_id,))]


def _ready(p: dict | None) -> bool:
    import profiles
    return bool(p and profiles.student_ready(p))


def can_receive(conn, uid: int) -> bool:
    r = conn.execute("SELECT 1 FROM users WHERE id = ? AND role = 'student' AND verified = 1", (uid,)).fetchone()
    p = store.student_profile(conn, uid) if r else None
    return bool(r and _ready(p) and p.get("allow_connections", 1))


def suggestions(conn, me: int, limit: int = SUGGEST_SHOW) -> list[tuple[dict, list[str]]]:
    """Students you may know: same major or minor, same graduation term, shared skills, mutual connections. (profile, reasons)."""
    mine = store.student_profile(conn, me)
    if not mine:
        return []
    known = {me}
    for a, b in conn.execute("SELECT user_a, user_b FROM connections WHERE user_a = ? OR user_b = ?", (me, me)):
        known.update((a, b))
    my_conn = set(connection_ids(conn, me))
    my_skills = {s.lower() for s in mine.get("skills") or []}
    ids = [r[0] for r in conn.execute(
        "SELECT s.user_id FROM student_profiles s JOIN users u ON u.id = s.user_id WHERE u.verified = 1 AND u.role = 'student' "
        "AND s.display_name != '' AND s.major != '' AND s.allow_connections = 1 ORDER BY s.updated_at DESC LIMIT ?", (SUGGEST_POOL,))]
    scored = []
    for uid in ids:
        if uid in known:
            continue
        p = store.student_profile(conn, uid)
        if not p:
            continue
        why, pts = [], 0
        if mine.get("major") and p["major"] == mine["major"]:
            why.append("Same major"); pts += 3
        if mine.get("grad_term") and p["grad_term"] and p["grad_term"].split()[-1] == mine["grad_term"].split()[-1]:
            why.append("Class of " + p["grad_term"].split()[-1]); pts += 2
        shared = my_skills & {s.lower() for s in p.get("skills") or []}
        if shared:
            why.append(f"{len(shared)} shared skill{'s' if len(shared) != 1 else ''}"); pts += min(3, len(shared))
        mutual = my_conn & set(connection_ids(conn, uid))
        if mutual:
            why.append(f"{len(mutual)} mutual"); pts += 2 * len(mutual)
        scored.append((pts, p, why))
    scored.sort(key=lambda x: (-x[0], x[1]["display_name"].lower()))
    picked = [(p, why) for pts, p, why in scored if pts > 0][:limit]
    if len(picked) < 6:                                     # a young network: fill with the newest profiles
        seen = {p["user_id"] for p, _ in picked}
        picked += [(p, ["New on the network"]) for pts, p, why in scored if pts == 0 and p["user_id"] not in seen][:6 - len(picked)]
    return picked


# ---------- small pieces other pages use ----------

def follow_button(employer_id: int, following: bool, next_: str = "", small: bool = True) -> str:
    sz = " sm" if small else ""
    action, label = ("unfollow", "Following ✓") if following else ("follow", "Follow")
    cls = "sec" if following else "ghost"
    return (f'<form method="post" action="/network/{action}" class="navform">{ui.user_csrf_input()}<input type="hidden" name="employer" value="{int(employer_id)}">'
            f'<input type="hidden" name="next" value="{esc(next_)}"><button class="b{sz} {cls}" type="submit"{" aria-pressed=true" if following else ""}>{label}</button></form>')


def connect_button(other: int, st: str, next_: str = "", note_field: bool = False) -> str:
    csrf, nxt = ui.user_csrf_input(), f'<input type="hidden" name="next" value="{esc(next_)}">'
    if st == "connected":
        return (f'<span class="pill ok">✓ Connected</span><form method="post" action="/network/remove" class="navform">{csrf}{nxt}<input type="hidden" name="other" value="{other}">'
                '<button class="b sm ghost" type="submit">Remove</button></form>')
    if st == "sent":
        return (f'<span class="pill">Request sent</span><form method="post" action="/network/remove" class="navform">{csrf}{nxt}<input type="hidden" name="other" value="{other}">'
                '<button class="b sm ghost" type="submit">Withdraw</button></form>')
    if st == "received":
        return (f'<form method="post" action="/network/respond" class="navform">{csrf}{nxt}<input type="hidden" name="other" value="{other}">'
                '<button class="b sm" name="action" value="accept" type="submit">Accept</button> '
                '<button class="b sm ghost" name="action" value="decline" type="submit">Decline</button></form>')
    if st == "declined":
        return '<span class="pill">Not available</span>'
    note = (f'<input name="note" maxlength="{NOTE_LEN}" placeholder="Add a note (optional)" aria-label="Note" class="cnote">' if note_field else "")
    return (f'<form method="post" action="/network/connect" class="navform cform2">{csrf}{nxt}<input type="hidden" name="to" value="{other}">{note}'
            f'<button class="b sm" type="submit">{ui.icon("plus", 14)} Connect</button></form>')


def profile_strip(conn, viewer_id: int, other: int, next_: str) -> str:
    """The Connect button plus counts, for another student's profile page (blank if they don't take requests)."""
    n = connection_count(conn, other)
    mutual = len(mutual_ids(conn, viewer_id, other))
    st = state(conn, viewer_id, other)
    counts = f'<span class="small faint">{web.plural(n, "connection")}{f" · {mutual} mutual" if mutual else ""}</span>'
    btn = connect_button(other, st, next_, note_field=True) if (st != "none" or can_receive(conn, other)) else ""
    return f'<div class="row netstrip">{btn}{counts}</div>'


def connections_section(conn, uid: int, viewer_id: int, limit: int = 8) -> str:
    """The Connections card on a student's profile: count, mutual count and the most recent connections."""
    ids = [i for i in connection_ids(conn, uid)
           if (lambda p: p and p.get("display_name"))(store.student_profile(conn, i))]
    own = uid == viewer_id
    mutual = set() if own else set(mutual_ids(conn, viewer_id, uid))
    if not ids:
        body = ('<p class="small muted" style="margin:0">No connections yet. <a href="/network?tab=discover">Find classmates</a></p>'
                if own else '<p class="small muted" style="margin:0">No connections yet.</p>')
    else:
        ids.sort(key=lambda i: (i not in mutual,))
        people = "".join(
            f'<a class="pconn" href="/u/{i}"><span class="av" aria-hidden="true">{ui.initials(web.display_name(conn, i, "student")[0])}</span>'
            f'<span class="pc-t"><b>{esc(web.display_name(conn, i, "student")[0])}</b><small>{esc(web.display_name(conn, i, "student")[1])}</small>'
            f'{"<em>Mutual</em>" if i in mutual else ""}</span></a>' for i in ids[:limit])
        more = f'<a class="small" href="/network?tab=connections">See all {len(ids)}</a>' if own and len(ids) > limit else ""
        body = f'<div class="pconns">{people}</div>{more}'
    head = f'{web.plural(len(ids), "connection")}' + (f" · {len(mutual)} mutual" if mutual else "")
    return f'<section class="psec pconn-sec"><h3 class="sec">Connections <span class="faint">{esc(head)}</span></h3><div class="card">{body}</div></section>'


# ---------- pages ----------

def _tab_bar(tab: str, counts: dict) -> str:
    return '<div class="seg" role="tablist" style="margin:18px 0">' + "".join(
        f'<a href="/network?tab={k}"{" class=on aria-current=page" if k == tab else ""}>{esc(v)}'
        f'{f" <span class=faint>({counts[k]})</span>" if counts.get(k) else ""}</a>' for k, v in TABS) + "</div>"


def _person_card(conn, uid: int, extra: str = "", why: list[str] | None = None) -> str:
    name, sub, kind = web.display_name(conn, uid, "student")
    chips = "".join(f'<span class="chip">{esc(w)}</span>' for w in (why or []))
    return (f'<div class="card ncard"><div class="row between" style="align-items:center;gap:12px">'
            f'<div style="min-width:0">{web.person(name, sub, kind, f"/u/{uid}")}{f"<div class=chips style=margin-top:8px>{chips}</div>" if chips else ""}</div>'
            f'<div class="row">{extra}</div></div></div>')


@router.get("/network", response_class=HTMLResponse)
def network_page(request: Request, tab: str = "", msg: str = ""):
    user = web.require_user(request, "student")
    security.enforce_rate_limit(request, security.general_limiter, "network")
    notes = {"sent": ("verified", "Request sent."), "accepted": ("verified", "You're connected."), "declined": ("info", "Request declined."),
             "removed": ("info", "Done."), "followed": ("verified", "You're following that company."), "unfollowed": ("info", "Unfollowed."),
             "cap": ("warning", f"You have {PENDING_CAP} requests waiting. Let some get answered first."),
             "scam": ("warning", "That note looks like a scam signal, so it wasn't sent. Keep it to a sentence about who you are."),
             "off": ("warning", "That student isn't taking connection requests."), "limit": ("warning", "Too many requests just now. Try again later.")}
    top = ui.banner(*notes[msg]) if msg in notes else ""
    with store.db() as conn:
        me = user["id"]
        incoming = store.rows(conn, "SELECT * FROM connections WHERE status = 'pending' AND requested_by != ? AND (user_a = ? OR user_b = ?) ORDER BY created_at DESC", (me, me, me))
        outgoing = store.rows(conn, "SELECT * FROM connections WHERE status = 'pending' AND requested_by = ? ORDER BY created_at DESC", (me,))
        conns = connection_ids(conn, me)
        follows = followed_ids(conn, me)
        counts = {"connections": len(conns), "requests": len(incoming), "following": len(follows)}
        tab = tab if tab in dict(TABS) else ("requests" if incoming else "connections")
        head = ui.page_head("Your network", "Students you're connected with and companies you follow. Nobody here can message you: connecting is how you see each other on the network.", num="Network")
        if tab == "connections":
            body = ("".join(_person_card(conn, uid, connect_button(uid, "connected", "/network")) for uid in sorted(conns, key=lambda u: web.display_name(conn, u, "student")[0].lower()))
                    or '<div class="empty">No connections yet. <a href="/network?tab=discover">See people you may know</a>, or open a classmate\'s profile from the Feed.</div>')
        elif tab == "requests":
            inc = "".join(_person_card(conn, r["requested_by"], connect_button(r["requested_by"], "received", "/network?tab=requests"))
                          + (f'<p class="small muted rnote">“{esc(r["note"])}”</p>' if r["note"] else "") for r in incoming)
            out = "".join(_person_card(conn, (r["user_b"] if r["user_a"] == me else r["user_a"]), connect_button(r["user_b"] if r["user_a"] == me else r["user_a"], "sent", "/network?tab=requests")) for r in outgoing)
            body = ((f'<h3 class="sec">Waiting for you</h3>{inc}' if inc else '<div class="empty">No requests waiting for you.</div>')
                    + (f'<h3 class="sec">You sent</h3>{out}' if out else ""))
        elif tab == "discover":
            sug = suggestions(conn, me)
            body = ("".join(_person_card(conn, p["user_id"], connect_button(p["user_id"], "none", "/network?tab=discover", note_field=False), why) for p, why in sug)
                    or '<div class="empty">Nobody new to suggest yet. As more students set up their profiles, people from your major and class show up here.</div>')
            body = '<p class="small muted" style="margin-bottom:12px">Ranked by shared major, graduation year, skills and mutual connections. Students can switch this off in their profile.</p>' + body
        else:
            cards = ""
            for eid in follows:
                p = store.employer_profile(conn, eid)
                if not p or p["status"] != "approved":
                    continue
                n = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE employer_id = ? AND {store.live_where()}", (eid,)).fetchone()[0]
                cards += (f'<div class="card ncard"><div class="row between" style="align-items:center;gap:12px"><div style="min-width:0">'
                          f'{web.person(p["company"], p["industry"] or "Approved employer", "emp", f"/company/{eid}")}'
                          f'<p class="small muted" style="margin-top:6px">{web.plural(n, "open listing")}</p></div>'
                          f'<div class="row">{follow_button(eid, True, "/network?tab=following")}</div></div></div>')
            body = cards or '<div class="empty">You aren\'t following any companies yet. Open a company profile or a listing and press Follow to get their new jobs in one filter.</div>'
    return web.page(head + top + _tab_bar(tab, counts) + body, "Network", active="/network")


def _back(request_next: str, msg: str) -> RedirectResponse:
    base = _next(request_next, "/network")
    if base.startswith("/network"):
        sep = "&" if "?" in base else "?"
        return RedirectResponse(f"{base}{sep}msg={msg}", status_code=303)
    return RedirectResponse(base, status_code=303)


@router.post("/network/connect")
def connect(request: Request, to: int = Form(0), note: str = Form(""), next: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return _back(next, "removed")
    me = user["id"]
    try:
        security.enforce_key_limit(security.profile_limiter, f"c{me}", "connection requests")
    except Exception:
        return _back(next or "/network", "limit")
    note = security._CONTROL_CHARS_RE.sub("", (note or "").replace("\n", " ")).strip()[:NOTE_LEN]
    with store.db() as conn:
        st = state(conn, me, to)
        if st == "self" or not can_receive(conn, to) and st not in ("received",):
            return _back(next or "/network", "off")
        if st == "received":                                # they already asked me: connecting back is accepting
            a, b = _pair(me, to)
            conn.execute("UPDATE connections SET status = 'accepted', updated_at = ? WHERE user_a = ? AND user_b = ?", (time.time(), a, b))
            return _back(next or "/network", "accepted")
        if st != "none":
            return _back(next or "/network", "removed")
        pending = conn.execute("SELECT COUNT(*) FROM connections WHERE status = 'pending' AND requested_by = ?", (me,)).fetchone()[0]
        if pending >= PENDING_CAP:
            return _back(next or "/network", "cap")
        if note and msgcheck.check(note)["band"] in ("block", "review"):
            return _back(next or "/network", "scam")
        a, b = _pair(me, to)
        now = time.time()
        conn.execute("INSERT OR REPLACE INTO connections (user_a, user_b, requested_by, status, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (a, b, me, "pending", note, now, now))
    return _back(next or "/network", "sent")


@router.post("/network/respond")
def respond(request: Request, other: int = Form(0), action: str = Form(""), next: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return _back(next, "removed")
    me = user["id"]
    with store.db() as conn:
        if state(conn, me, other) == "received" and action in ("accept", "decline"):
            a, b = _pair(me, other)
            conn.execute("UPDATE connections SET status = ?, updated_at = ? WHERE user_a = ? AND user_b = ?",
                         ("accepted" if action == "accept" else "declined", time.time(), a, b))
            return _back(next or "/network?tab=requests", "accepted" if action == "accept" else "declined")
    return _back(next or "/network?tab=requests", "removed")


@router.post("/network/remove")
def remove(request: Request, other: int = Form(0), next: str = Form(""), csrf: str = Form("")):
    """Removes a connection, or withdraws a request you sent."""
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return _back(next, "removed")
    me = user["id"]
    with store.db() as conn:
        if state(conn, me, other) in ("connected", "sent"):
            a, b = _pair(me, other)
            conn.execute("DELETE FROM connections WHERE user_a = ? AND user_b = ?", (a, b))
    return _back(next or "/network", "removed")


@router.post("/network/follow")
def follow(request: Request, employer: int = Form(0), next: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return _back(next, "removed")
    security.enforce_key_limit(security.profile_limiter, f"f{user['id']}", "follows")
    with store.db() as conn:
        if store.employer_approved(conn, employer):
            conn.execute("INSERT OR IGNORE INTO follows (student_id, employer_id, created_at) VALUES (?,?,?)", (user["id"], store.org_of(conn, employer), time.time()))
    return _back(next or f"/company/{int(employer)}", "followed")


@router.post("/network/unfollow")
def unfollow(request: Request, employer: int = Form(0), next: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return _back(next, "removed")
    with store.db() as conn:
        conn.execute("DELETE FROM follows WHERE student_id = ? AND employer_id = ?", (user["id"], employer))
    return _back(next or f"/company/{int(employer)}", "unfollowed")
