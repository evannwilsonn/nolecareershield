"""
Employer hiring tools, per listing:

  * Ranked matches: every student who is visible to employers, scored against the listing with
    the same whole-profile fit score students see (fit.py), with the evidence behind it.
  * Invite to apply: a prefilled first message about the listing (normal messaging rules apply:
    approved employers only, students who accept messages, every message scanned).
  * Candidates: a simple tracker. Students land in it when they message about the listing, when
    the employer invites them, or when the employer saves them from the matches. Stages and
    private notes are the employer's own and aren't shown to students.
  * Stats: unique students who viewed the listing, Apply clicks, students who messaged, and
    candidates by stage. Views and clicks are totals only; employers never see who clicked.
  * Applicant table (/hiring/applicants): every candidate across all the employer's listings in one
    filterable, sortable table with bulk stage moves and archive, plus an employer-private 1-5 rating
    and note. Only students the employer may already see (they applied, are talking with them, or are
    visible to approved employers); resumes are never shown in the table.
  * Listing controls: pause / resume, close, duplicate, edit (app.py, because it re-scans) and expiry
    (7-120 days, default 60 from approval; a reminder email 5 days before, app.send_expiry_reminders).
    What students can see is decided in one place: store.live_where() / store.visible_listing().
"""

from __future__ import annotations

import calendar
import re
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import css_hiring  # noqa: F401  (appends the applicant table and listing-control styles to ui.CSS)
import easyapply
import fit
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

STAGES = [("new", "New"), ("reviewing", "Reviewing"), ("interviewing", "Interviewing"), ("offer", "Offer"),
          ("hired", "Hired"), ("declined", "Not moving forward")]
STAGE_NAME = dict(STAGES)
SOURCES = {"applied": ("Applied", "ok"), "messaged": ("Messaged you", "accent"), "invited": ("You invited", "gold"), "saved": ("Saved from matches", "")}
MATCH_POOL = 400          # most recently updated visible students scored per listing
MATCH_SHOW = 40
NOTE_MAX = 300

# Tables: job_views, job_apply_clicks and candidates, created in store.SCHEMA.


# ---------- recording (called from the job page and messaging) ----------

def record_view(conn, job_id: int, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO job_views (job_id, user_id, day) VALUES (?,?,?)",
                  (job_id, user_id, time.strftime("%Y-%m-%d", time.gmtime())))


def record_apply_click(conn, job_id: int, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO job_apply_clicks (job_id, user_id, created_at) VALUES (?,?,?)", (job_id, user_id, time.time()))


def add_candidate(conn, job_id: int, student_id: int, employer_id: int, source: str) -> bool:
    """Adds the student to the listing's tracker if they aren't in it yet. Returns True if added."""
    if not job_id or source not in SOURCES:
        return False
    now = time.time()
    cur = conn.execute("INSERT OR IGNORE INTO candidates (job_id, student_id, employer_id, stage, source, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?)", (job_id, student_id, employer_id, "new", source, now, now))
    return cur.rowcount > 0


# ---------- queries ----------

def own_job(conn, user: dict, job_id: int) -> dict | None:
    return store.row(conn, "SELECT * FROM jobs WHERE id = ? AND employer_id = ?", (job_id, user["id"]))


def ranked_matches(conn, job: dict, limit: int = MATCH_SHOW) -> list[tuple[dict, dict]]:
    """(fit result, profile) for visible students, best first."""
    ids = conn.execute("SELECT s.user_id FROM student_profiles s JOIN users u ON u.id = s.user_id "
                       "WHERE s.visible_to_employers = 1 AND s.display_name != '' AND s.major != '' AND u.verified = 1 "
                       "ORDER BY s.updated_at DESC LIMIT ?", (MATCH_POOL,)).fetchall()
    out = []
    for (uid,) in ids:
        p = store.student_profile(conn, uid)
        if not p or not (p["skills"] or p["resume_text"] or p["items"]):
            continue
        out.append((fit.fit_score(job, p), p))
    out.sort(key=lambda x: (-x[0]["score"], x[1]["display_name"].lower()))
    return out[:limit]


def job_stats(conn, job: dict) -> dict:
    jid = job["id"]
    week = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    stages = {r["stage"]: r["n"] for r in store.rows(conn, "SELECT stage, COUNT(*) AS n FROM candidates WHERE job_id = ? GROUP BY stage", (jid,))}
    return {"views": one("SELECT COUNT(DISTINCT user_id) FROM job_views WHERE job_id = ?", jid),
            "views_week": one("SELECT COUNT(DISTINCT user_id) FROM job_views WHERE job_id = ? AND day >= ?", jid, week),
            "clicks": one("SELECT COUNT(*) FROM job_apply_clicks WHERE job_id = ?", jid),
            "messaged": one("SELECT COUNT(*) FROM conversations WHERE job_id = ? AND employer_id = ? AND started_by = student_id", jid, job["employer_id"] or 0),
            "candidates": sum(stages.values()), "stages": stages}


# ---------- pages ----------

STATUS_PILL = {"approved": ("ok", "Live"), "pending": ("warn", "In review"), "rejected": ("bad", "Not approved"), "removed": ("bad", "Removed")}
# What the employer sees for each store.listing_state().
STATE_PILL = {"live": ("ok", "Live"), "pending": ("warn", "In review"), "rejected": ("bad", "Not approved"), "removed": ("bad", "Removed"),
              "paused": ("gold", "Paused"), "closed": ("", "Closed"), "expired": ("bad", "Expired")}
EXPIRY_CHOICES = (7, 14, 30, 45, 60, 90, 120)
DONE = {"paused": ("info", "Paused. Students can't see it; everyone who applied stays in your tracker."),
        "resumed": ("verified", "Back on the board."),
        "closed": ("info", "Closed. It's off the board, and students who applied see that it's closed."),
        "extended": ("verified", "Expiry date updated."),
        "badexpiry": ("warning", f"Pick {store.LISTING_DAYS_MIN} to {store.LISTING_DAYS_MAX} days, or a date in that range."),
        "copied": ("verified", "Copied. The new listing is scanned and waiting for a reviewer, like any new listing. Edit it before it's approved if you like."),
        "saved": ("verified", "Saved. Those changes are live now."),
        "review": ("info", "Saved and sent back for review: the listing was scanned again and is off the board until a reviewer approves it.")}


def _day(ts: float) -> str:
    return time.strftime("%b %d, %Y", time.gmtime(ts)).replace(" 0", " ")


def expiry_line(j: dict) -> str:
    state = store.listing_state(j)
    exp = store.expires_ts(j)
    if state == "pending":
        return f"Runs {int(j.get('expiry_days') or store.LISTING_DAYS_DEFAULT)} days once approved"
    if state in ("rejected", "removed") or exp is None:
        return ""
    if state == "expired":
        return f"Expired {_day(exp)}"
    days = max(0, round((exp - time.time()) / 86400))
    return f"{'Was due to end' if state == 'closed' else 'Ends'} {_day(exp)}" + ("" if state == "closed" else f" · {days} day{'s' if days != 1 else ''} left")


def _btn(jid: int, action: str, label: str, cls: str = "sec", **extra) -> str:
    hidden = "".join(f'<input type="hidden" name="{k}" value="{esc(v)}">' for k, v in extra.items())
    return (f'<form method="post" action="/hiring/{jid}/{action}" class="navform">{ui.user_csrf_input()}{hidden}'
            f'<button class="b sm {cls}" type="submit">{esc(label)}</button></form>')


def listing_controls(j: dict, full: bool = False) -> str:
    """Pause / resume / close / extend / edit / duplicate for one listing, as plain forms (no JS).
    On Your listings (full=False) the forms come back to that page."""
    jid, state = int(j["id"]), store.listing_state(j)
    back = {} if full else {"back": "list"}
    out = []
    if state == "live":
        out.append(_btn(jid, "status", "Pause", do="pause", **back))
    if state == "paused":
        out.append(_btn(jid, "status", "Resume", "", do="resume", **back))
    if state in ("live", "paused", "expired"):
        out.append(_btn(jid, "status", "Close", "ghost", do="close", **back))
    if state == "expired":
        out.append(_btn(jid, "expiry", "Extend 30 days", "", days="30", **back))
    if state in ("pending", "live", "paused", "expired"):
        out.append(f'<a class="b sm ghost" href="/hiring/{jid}/edit">Edit</a>')
    if state != "removed":
        out.append(_btn(jid, "duplicate", "Duplicate", "ghost"))
    row = f'<div class="lc-row">{"".join(out)}</div>'
    if not full or state in ("closed", "rejected", "removed"):
        return row
    opts = "".join(f'<option value="{d}"{" selected" if d == (30 if state != "pending" else int(j.get("expiry_days") or 60)) else ""}>{d} days</option>'
                   for d in EXPIRY_CHOICES)
    if state == "pending":
        label, date = "Keep it up for (from approval)", ""
    else:
        label = "Extend or shorten: keep it up for" if state != "expired" else "Put it back up for"
        date = (f'<span class="lc-or">or until</span><label class="sr" for="lc-date">End date</label>'
                f'<input id="lc-date" type="date" name="date" min="{time.strftime("%Y-%m-%d", time.gmtime(time.time() + store.LISTING_DAYS_MIN * 86400))}" '
                f'max="{time.strftime("%Y-%m-%d", time.gmtime(time.time() + store.LISTING_DAYS_MAX * 86400))}">')
    exp = (f'<form method="post" action="/hiring/{jid}/expiry" class="lc-exp">{ui.user_csrf_input()}'
           f'<label for="lc-days">{esc(label)}</label><select id="lc-days" name="days">{opts}</select>{date}'
           f'<button class="b sm sec" type="submit">Set</button></form>')
    return row + exp


def _stat(n, label: str, sub: str = "", of: int | None = None) -> str:
    """One number. With `of` (the students who viewed), a thin bar shows it as a share of them: a funnel."""
    bar = f'<span class="fb" style="--f:{min(1, n / of):.3f}"><i></i></span>' if of else ('<span class="fb"><i></i></span>' if of == 0 else "")
    return f'<div class="stat"><div class="n">{n}</div><div class="l">{esc(label)}</div>{f"<div class=s>{esc(sub)}</div>" if sub else ""}{bar}</div>'


def _funnel(s: dict, subs: tuple = ("", "", "", ""), cls: str = "") -> str:
    v = s["views"]
    return (f'<div class="stats funnel {cls}">{_stat(v, "students viewed", subs[0], v)}{_stat(s["clicks"], "clicked Apply", subs[1], v)}'
            f'{_stat(s["messaged"], "messaged you", subs[2], v)}{_stat(s["candidates"], "candidates", subs[3], v)}</div>')


def _pipeline(cands: list[dict]) -> str:
    cells = "".join(f'<div class="pstep{" has" if n else ""}"><span class="n">{n}</span><span class="l">{esc(label)}</span></div>'
                    for label, n in ((v, sum(1 for c in cands if c["stage"] == k)) for k, v in STAGES))
    return f'<div class="pipe" aria-label="Candidates by stage">{cells}</div>'


@router.get("/hiring", response_class=HTMLResponse)
def overview(request: Request, done: str = ""):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "hiring")
    with store.db() as conn:
        jobs = store.rows(conn, "SELECT * FROM jobs WHERE employer_id = ? ORDER BY id DESC LIMIT 100", (user["id"],))
        stats = {j["id"]: job_stats(conn, j) for j in jobs}
    head = ui.page_head("Your listings", "Views, Apply clicks, ranked student matches and a candidate tracker for every listing you post.", num="Hiring")
    head += ui.banner(*DONE[done]) if done in DONE else ""
    if not jobs:
        return web.page(head + '<div class="empty">No listings yet. <a href="/post">Post your first job</a> and it shows up here once it\'s submitted.</div>',
                        "Your listings", active="/hiring")
    rows_html = ""
    for j in jobs:
        s, state = stats[j["id"]], store.listing_state(j)
        tone, label = STATE_PILL.get(state, ("", state))
        when = expiry_line(j)
        rows_html += (f'<div class="card hjob2 st-{state}"><div class="row between" style="align-items:flex-start">'
                      f'<a class="hj-main" href="/hiring/{int(j["id"])}"><div class="job-title">{esc(j["title"])}</div><div class="job-co">{esc(j["company"])} · {esc(j["work_type"].title())}'
                      f'{" · " + esc(j["location"]) if j["location"] else ""}</div></a><div class="hj-state"><span class="pill {tone}">{esc(label)}</span>'
                      f'{f"<span class=hj-when>{esc(when)}</span>" if when else ""}</div></div>'
                      f'<a class="hj-stats" href="/hiring/{int(j["id"])}" aria-label="Stats for {esc(j["title"])}">{_funnel(s, cls="sm")}</a>{listing_controls(j)}</div>')
    n_app = sum(x["candidates"] for x in stats.values())
    body = (head + f'<div class="row" style="margin-bottom:14px"><a class="b" href="/post">{ui.icon("plus", 16)} Post a job</a>'
            f'<a class="b sec" href="/hiring/applicants">{ui.icon("user", 16)} All applicants ({n_app})</a></div>{rows_html}')
    return web.page(body, "Your listings", active="/hiring")


def _tabs(jid: int, tab: str, n_cand: int) -> str:
    items = [("matches", "Ranked matches"), ("candidates", f"Candidates ({n_cand})")]
    return ('<div class="seg" role="tablist" style="margin:18px 0">' + "".join(
        f'<a href="/hiring/{jid}?tab={k}"{" class=on aria-current=page" if k == tab else ""}>{esc(v)}</a>' for k, v in items) + "</div>")


def _evidence(f: dict) -> str:
    bits = []
    for m in f["matched"][:3]:
        where = m["where"][0].replace("Your skills list", "skills list").replace("Your resume", "resume").replace("Your headline and about", "about")
        bits.append(f"<b>{esc(m['skill'])}</b> <span class=faint>({esc(where)})</span>")
    met = sum(1 for c in f["checklist"] if c["status"] == "met")
    tail = f'<span class="faint">{met} of {len(f["checklist"])} requirements met</span>' if f["checklist"] else ""
    return " · ".join(bits + ([tail] if tail else []))


def _reqs(f: dict, short: bool = False) -> str:
    """Which of the listing's requirements this student meets, item by item (employer view).
    short: the summary is just "N/M" (the applicant table)."""
    if not f["checklist"]:
        return '<span class="faint">None set</span>' if short else ""
    mark = {"met": ("✓", "met", "Met"), "missing": ("⊘", "miss", "Not met"), "unknown": ("?", "unk", "Not on profile")}
    rows = "".join(f'<li class="rq {mark[c["status"]][1]}"><span aria-hidden="true">{mark[c["status"]][0]}</span>'
                   f'<span class="sr">{mark[c["status"]][2]}: </span>{esc(c["text"].replace(" (preferred)", ""))}'
                   f'{"<em>Required</em>" if c.get("must") else ("<em class=p>Preferred</em>" if "(preferred)" in c["text"] else "")}</li>'
                   for c in f["checklist"])
    summary = (f'<b>{f["met"]}/{f["total"]}</b><span class="sr"> requirements met</span>' if short
               else f'Meets {f["met"]} of {f["total"]} of your requirements')
    return f'<details class="rqs{" short" if short else ""}"><summary>{summary}</summary><ul>{rows}</ul></details>'



def _match_card(conn, jid: int, f: dict, p: dict, can_invite: bool, saved: bool) -> str:
    uid = int(p["user_id"])
    sub = " · ".join(x for x in (p["major"], p["grad_term"] and "Graduating " + p["grad_term"]) if x)
    tone = "ok" if f["score"] >= 65 else "warn" if f["score"] < 45 else ""
    parts = "".join(f'<span class="chip" title="{esc(x["detail"])}">{esc(x["name"])} {x["score"]}</span>' for x in f["parts"])
    csrf = ui.user_csrf_input()
    save = ('<span class="pill ok">In candidates</span>' if saved else
            f'<form method="post" action="/hiring/{jid}/save" class="navform">{csrf}<input type="hidden" name="student" value="{uid}">'
            '<button class="b sm sec" type="submit">Save to candidates</button></form>')
    headline = f'<p style="margin-top:8px">{esc(p["headline"])}</p>' if p["headline"] else ""
    invite = (f'<a class="b sm" href="/messages/new?to={uid}&amp;job={jid}&amp;invite=1">{ui.icon("chat", 14)} Invite to apply</a>'
              if can_invite and p["allow_messages"] else "")
    return (f'<div class="card mcard"><div class="row between" style="align-items:flex-start;gap:12px">'
            f'<div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:{f["score"]}"><b>{f["score"]}%</b></div>'
            f'<div style="min-width:0">{web.person(p["display_name"], sub, "stu", f"/u/{uid}")}</div></div>'
            f'<span class="pill {tone}">{f["percent"]}% match</span></div>'
            f'{headline}'
            f'<p class="small" style="margin-top:8px">{_evidence(f)}</p>{_reqs(f)}<div class="chips" style="margin-top:8px">{parts}</div>'
            f'<div class="row" style="margin-top:12px">{invite}{save}<a class="b sm ghost" href="/u/{uid}">View profile</a></div></div>')


# ---------- one applicant table across every listing ----------

PAGE_SIZE = 25
MAX_ROWS = 2000
SORTS = {"match": "Best match", "date": "Newest", "rating": "Your rating", "name": "Name"}
MIN_MATCH = (0, 25, 50, 65, 75, 90)
STARS = ["No rating"] + ["★" * n + "☆" * (5 - n) for n in range(1, 6)]
BULK_MAX = 200


def _class_of(p: dict) -> str:
    m = re.search(r"(20\d\d)", p.get("grad_term") or "")
    return f"Class of {m.group(1)}" if m else ""


def applicant_rows(conn, eid: int, archived: bool = False) -> list[dict]:
    """Every candidate on this employer's listings that the employer may see, with fit worked out.
    Same rule as profiles.can_view_student: the student applied to this employer, is talking with them,
    or is visible to approved employers. Anyone who has since hidden their profile (and never applied or
    talked) drops out of the table."""
    jobs = {j["id"]: j for j in store.rows(conn, "SELECT * FROM jobs WHERE employer_id = ?", (eid,))}
    if not jobs:
        return []
    # Every quick-apply application is in the tracker; this only matters for rows made before that rule.
    conn.execute("INSERT OR IGNORE INTO candidates (job_id, student_id, employer_id, stage, source, created_at, updated_at) "
                 "SELECT a.job_id, a.student_id, a.employer_id, 'new', 'applied', a.created_at, a.created_at FROM applications a "
                 "JOIN jobs j ON j.id = a.job_id WHERE a.employer_id = ? AND j.employer_id = ?", (eid, eid))
    applied = {(r["job_id"], r["student_id"]): r["created_at"] for r in
               store.rows(conn, "SELECT job_id, student_id, created_at FROM applications WHERE employer_id = ?", (eid,))}
    applied_to = {sid for _, sid in applied}
    talking = {r[0] for r in conn.execute("SELECT DISTINCT student_id FROM conversations WHERE employer_id = ? AND blocked_by IS NULL", (eid,))}
    cands = store.rows(conn, "SELECT c.* FROM candidates c JOIN jobs j ON j.id = c.job_id WHERE c.employer_id = ? AND j.employer_id = ? "
                             "AND c.archived = ? ORDER BY c.updated_at DESC LIMIT ?", (eid, eid, 1 if archived else 0, MAX_ROWS))
    profs: dict[int, dict | None] = {}
    out = []
    for c in cands:
        sid = c["student_id"]
        if sid not in profs:
            profs[sid] = store.student_profile(conn, sid)
        p = profs[sid]
        if not (p and p.get("display_name") and p.get("major")):
            continue
        if not (p["visible_to_employers"] or sid in talking or sid in applied_to):
            continue
        j = jobs[c["job_id"]]
        f = fit.fit_score(j, p)
        at = applied.get((c["job_id"], sid))
        out.append({"c": c, "p": p, "j": j, "f": f, "applied": at is not None, "at": at or c["created_at"],
                    "req_ok": all(x["status"] == "met" for x in f["checklist"] if x.get("must"))})
    return out


def _params(q) -> dict:
    def num(k, lo, hi, d=0):
        try:
            return max(lo, min(hi, int(q.get(k) or d)))
        except (TypeError, ValueError):
            return d
    return {"job": num("job", 0, 2 ** 31), "stage": q.get("stage") if q.get("stage") in STAGE_NAME else "",
            "source": q.get("source") if q.get("source") in SOURCES else "", "min": num("min", 0, 100),
            "req": "1" if q.get("req") == "1" else "", "sort": q.get("sort") if q.get("sort") in SORTS else "match",
            "show": "archived" if q.get("show") == "archived" else "", "page": num("page", 1, 10 ** 6, 1)}


def filter_rows(rows: list[dict], q: dict) -> list[dict]:
    r = [x for x in rows if (not q["job"] or x["j"]["id"] == q["job"]) and (not q["stage"] or x["c"]["stage"] == q["stage"])
         and (not q["source"] or x["c"]["source"] == q["source"]) and x["f"]["percent"] >= q["min"] and (not q["req"] or x["req_ok"])]
    name = lambda x: x["p"]["display_name"].lower()                           # noqa: E731
    key = {"match": lambda x: (-x["f"]["percent"], name(x)), "date": lambda x: (-x["at"], name(x)),
           "rating": lambda x: (-(x["c"].get("rating") or 0), -x["f"]["percent"], name(x)), "name": lambda x: (name(x), -x["f"]["percent"])}[q["sort"]]
    return sorted(r, key=key)


def _qs(q: dict, **over) -> str:
    d = {k: v for k, v in dict(q, **over).items() if v not in ("", 0, None) and not (k == "sort" and v == "match") and not (k == "page" and v == 1)}
    return "/hiring/applicants" + ("?" + urlencode(d) if d else "")


def _opts(items, cur) -> str:
    return "".join(f'<option value="{esc(k)}"{" selected" if str(k) == str(cur) else ""}>{esc(v)}</option>' for k, v in items)


def _applicant_row(i: int, x: dict, back: str) -> tuple[str, str]:
    c, p, j, f = x["c"], x["p"], x["j"], x["f"]
    sid, jid = int(c["student_id"]), int(j["id"])
    fid = f"rf{i}"
    who = " · ".join(v for v in (p["major"], _class_of(p)) if v)
    src, src_tone = SOURCES.get(c["source"], (c["source"], ""))
    state = store.listing_state(j)
    st_note = "" if state == "live" else f' <span class="at-st">{esc(STATE_PILL.get(state, ("", state))[1])}</span>'
    pct = f["percent"]
    tone = "hi" if pct >= 75 else "mid" if pct >= 50 else "lo"
    label = f'{esc(p["display_name"])} for {esc(j["title"])}'
    req_all = ('<span class="at-all" title="Meets every required qualification">✓ all required</span>'
               if x["req_ok"] and any(y.get("must") for y in f["checklist"]) else "")
    row = (f'<tr id="a{jid}-{sid}"><td class="at-sel" data-l="Select"><input type="checkbox" form="bulk" name="sel" value="{jid}:{sid}" aria-label="Select {label}"></td>'
           f'<td class="at-stu" data-l="Student">{web.person(p["display_name"], who, "stu", f"/u/{sid}")}</td>'
           f'<td class="at-lst" data-l="Listing"><a class="at-job" href="/hiring/{jid}?tab=candidates#c{sid}">{esc(j["title"])}</a>{st_note}'
           f'<span class="at-src"><span class="sr">Source: </span><span class="pill {src_tone}">{esc(src)}</span></span></td>'
           f'<td data-l="Stage"><label class="sr" for="{fid}s">Stage for {label}</label><select id="{fid}s" form="{fid}" name="stage">{_opts(STAGES, c["stage"])}</select></td>'
           f'<td data-l="Match"><span class="at-pct {tone}">{pct}%</span></td>'
           f'<td data-l="Requirements">{_reqs(f, short=True)}{req_all}</td>'
           f'<td data-l="{"Applied" if x["applied"] else "Added"}"><span class="at-date" title="{esc(_day(x["at"]))}">{esc(_day(x["at"]).rsplit(",", 1)[0])}</span><span class="at-how">{"Applied" if x["applied"] else "Added"}</span></td>'
           f'<td class="at-priv" data-l="Your rating and note"><div class="at-pv"><label class="sr" for="{fid}r">Your rating for {label}</label>'
           f'<select id="{fid}r" form="{fid}" name="rating" class="at-stars">{_opts(enumerate(STARS), int(c.get("rating") or 0))}</select>'
           f'<label class="sr" for="{fid}n">Private note on {label}</label><input id="{fid}n" form="{fid}" name="note" maxlength="{NOTE_MAX}" value="{esc(c["note"])}" placeholder="Private note">'
           f'<button class="b sm" form="{fid}" type="submit">Save</button></div></td></tr>')
    form = (f'<form id="{fid}" method="post" action="/hiring/applicants/row">{ui.user_csrf_input()}<input type="hidden" name="job" value="{jid}">'
            f'<input type="hidden" name="student" value="{sid}"><input type="hidden" name="back" value="{esc(back)}#a{jid}-{sid}"></form>')
    return row, form


APPLICANT_DONE = {"moved": "Moved {n} to {stage}.", "archived": "Archived {n}. They're under Show: Archived.", "restored": "Restored {n}.",
                  "saved": "Saved.", "none": "Tick at least one applicant first."}


@router.get("/hiring/applicants", response_class=HTMLResponse)
def applicants(request: Request):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "hiring_applicants")
    raw = dict(request.query_params)
    q = _params(raw)
    head = (f'<a class="back" href="/hiring">← Your listings</a>' + ui.page_head(
        "Applicants", "Everyone in your candidate trackers, across all your listings. Stages, ratings and notes are private to your organization.", num="Hiring"))
    with store.db() as conn:
        if not store.employer_approved(conn, user["id"]):
            return web.page(head + ui.banner("info", "The applicant table opens once a reviewer approves your organization."), "Applicants", active="/hiring")
        jobs = store.rows(conn, "SELECT * FROM jobs WHERE employer_id = ? ORDER BY id DESC", (user["id"],))
        rows = applicant_rows(conn, user["id"], archived=q["show"] == "archived")
    shown = filter_rows(rows, q)
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    q["page"] = min(q["page"], pages)
    page_rows = shown[(q["page"] - 1) * PAGE_SIZE: q["page"] * PAGE_SIZE]
    back = _qs(q)
    done = ""
    if raw.get("done") in APPLICANT_DONE:
        n = raw.get("n", "")
        done = ui.banner("info" if raw["done"] == "none" else "verified", APPLICANT_DONE[raw["done"]].format(
            n=int(n) if n.isdigit() else 0, stage=STAGE_NAME.get(raw.get("to", ""), "that stage")))

    job_opts = [(0, "All listings")] + [(j["id"], j["title"] + ("" if store.listing_state(j) == "live" else f' ({STATE_PILL.get(store.listing_state(j), ("", ""))[1].lower()})'))
                                        for j in jobs]
    filters = (f'<form method="get" action="/hiring/applicants" class="at-filters card" role="search" aria-label="Filter applicants">'
               f'<div class="form-field"><label for="af-job">Listing</label><select id="af-job" name="job">{_opts(job_opts, q["job"])}</select></div>'
               f'<div class="form-field"><label for="af-stage">Stage</label><select id="af-stage" name="stage">{_opts([("", "Any stage")] + STAGES, q["stage"])}</select></div>'
               f'<div class="form-field"><label for="af-src">Source</label><select id="af-src" name="source">{_opts([("", "Any source")] + [(k, v[0]) for k, v in SOURCES.items()], q["source"])}</select></div>'
               f'<div class="form-field"><label for="af-min">Match</label><select id="af-min" name="min">{_opts([(m, "Any match" if not m else f"{m}% or more") for m in MIN_MATCH], q["min"])}</select></div>'
               f'<div class="form-field"><label for="af-sort">Sort by</label><select id="af-sort" name="sort">{_opts(SORTS.items(), q["sort"])}</select></div>'
               f'<div class="form-field"><label for="af-show">Show</label><select id="af-show" name="show">{_opts([("", "Active"), ("archived", "Archived")], q["show"])}</select></div>'
               f'<label class="toggle at-req" for="af-req"><input id="af-req" type="checkbox" name="req" value="1"{" checked" if q["req"] else ""}><span>Meets all required qualifications</span></label>'
               f'<div class="at-fbtn"><button class="b sm" type="submit">Apply filters</button><a class="b sm ghost" href="/hiring/applicants">Clear</a></div></form>')
    if not rows:
        empty = ("No archived applicants." if q["show"] else
                 "No applicants yet. Students appear here when they apply with Quick apply, message you about a listing, or when you invite them or save them from ranked matches.")
        return web.page(head + done + filters + f'<div class="empty">{esc(empty)}</div>', "Applicants", active="/hiring")
    if not shown:
        return web.page(head + done + filters + f'<div class="empty">No applicants match those filters. <a href="{esc(_qs({**q, "job": q["job"], "stage": "", "source": "", "min": 0, "req": "", "page": 1}))}">Loosen them</a> or <a href="/hiring/applicants">clear all</a>.</div>',
                        "Applicants", active="/hiring")
    archived = q["show"] == "archived"
    start = (q["page"] - 1) * PAGE_SIZE
    range_note = f" · showing {start + 1}–{start + len(page_rows)}" if pages > 1 else ""
    bulk = (f'<form id="bulk" method="post" action="/hiring/applicants/bulk" class="at-bulk">{ui.user_csrf_input()}<input type="hidden" name="back" value="{esc(back)}">'
            f'<span class="at-count"><b>{len(shown)}</b> applicant{"s" if len(shown) != 1 else ""}'
            f'{range_note}</span>'
            f'<span class="at-bact"><label for="bk-stage">Move selected to</label><select id="bk-stage" name="stage">{_opts(STAGES, "reviewing")}</select>'
            f'<button class="b sm" type="submit" name="do" value="stage">Move</button>'
            f'<button class="b sm ghost" type="submit" name="do" value="{"restore" if archived else "archive"}">{"Restore selected" if archived else "Archive selected"}</button></span></form>')
    built = [_applicant_row(i, x, back) for i, x in enumerate(page_rows)]
    table = ('<div class="at-wrap"><table class="at"><caption class="sr">Applicants across your listings</caption><thead><tr>'
             '<th scope="col" class="at-sel"><span class="sr">Select</span></th><th scope="col">Student</th><th scope="col">Listing &amp; source</th>'
             '<th scope="col">Stage</th><th scope="col">Match</th><th scope="col">Req. met</th><th scope="col">Date</th><th scope="col">Your rating &amp; note</th>'
             '</tr></thead><tbody>' + "".join(r for r, _ in built) + '</tbody></table></div>' + "".join(f for _, f in built))
    nav = ""
    if pages > 1:
        prev = f'<a class="b sm sec" href="{esc(_qs(q, page=q["page"] - 1))}" rel="prev">← Previous</a>' if q["page"] > 1 else '<span></span>'
        nxt = f'<a class="b sm sec" href="{esc(_qs(q, page=q["page"] + 1))}" rel="next">Next →</a>' if q["page"] < pages else '<span></span>'
        nav = f'<nav class="at-pages" aria-label="Pages">{prev}<span class="small muted">Page {q["page"]} of {pages}</span>{nxt}</nav>'
    tip = ('<p class="small faint at-tip">Match % is the same whole-profile fit students see. Ratings and notes are yours alone: students never see them. '
           'Open a student\'s profile for anything they chose to share.</p>')
    return web.page(head + done + filters + bulk + table + nav + tip, "Applicants", active="/hiring")


def _safe_back(back: str) -> str:
    back = (back or "").split("#")[0]
    return back if back.startswith("/hiring/applicants") and "//" not in back and "\\" not in back else "/hiring/applicants"


def _with(url: str, **extra) -> str:
    return url + ("&" if "?" in url else "?") + urlencode(extra)


def _own_pairs(conn, eid: int, sel: list[str]) -> list[tuple[int, int]]:
    out = []
    for v in sel[:BULK_MAX]:
        m = re.fullmatch(r"(\d{1,10}):(\d{1,10})", v or "")
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    mine = {r[0] for r in conn.execute("SELECT id FROM jobs WHERE employer_id = ?", (eid,))}
    return [(j, s) for j, s in dict.fromkeys(out) if j in mine]


@router.post("/hiring/applicants/bulk")
def applicants_bulk(request: Request, sel: list[str] = Form([]), do: str = Form(""), stage: str = Form(""),
                    back: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    back = _safe_back(back)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(back, status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    with store.db() as conn:
        if not store.employer_approved(conn, user["id"]):
            return RedirectResponse("/hiring/applicants", status_code=303)
        pairs = _own_pairs(conn, user["id"], sel)
        if not pairs or do not in ("stage", "archive", "restore") or (do == "stage" and stage not in STAGE_NAME):
            return RedirectResponse(_with(back, done="none"), status_code=303)
        sets = {"stage": ("stage = ?", [stage]), "archive": ("archived = 1", []), "restore": ("archived = 0", [])}[do]
        n = 0
        for jid, sid in pairs:
            n += conn.execute(f"UPDATE candidates SET {sets[0]}, updated_at = ? WHERE job_id = ? AND student_id = ? AND employer_id = ?",
                              sets[1] + [time.time(), jid, sid, user["id"]]).rowcount
    done = {"stage": "moved", "archive": "archived", "restore": "restored"}[do]
    return RedirectResponse(_with(back, done=done, n=n, **({"to": stage} if do == "stage" else {})), status_code=303)


@router.post("/hiring/applicants/row")
def applicants_row(request: Request, job: int = Form(0), student: int = Form(0), stage: str = Form(""), rating: str = Form("0"),
                   note: str = Form(""), back: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    frag = f"#a{int(job)}-{int(student)}"
    back = _safe_back(back)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(back, status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    note = security._CONTROL_CHARS_RE.sub("", note or "").strip()[:NOTE_MAX]
    r = int(rating) if (rating or "").isdigit() and 0 <= int(rating) <= 5 else None
    if stage in STAGE_NAME and r is not None:
        with store.db() as conn:
            if own_job(conn, user, job) and store.employer_approved(conn, user["id"]):
                conn.execute("UPDATE candidates SET stage = ?, rating = ?, note = ?, updated_at = ? WHERE job_id = ? AND student_id = ? AND employer_id = ?",
                             (stage, r, note, time.time(), job, student, user["id"]))
    return RedirectResponse(_with(back, done="saved") + frag, status_code=303)


@router.get("/hiring/{job_id}", response_class=HTMLResponse)
def listing(job_id: int, request: Request, tab: str = "matches", done: str = ""):
    user = web.require_user(request, "employer")
    security.enforce_rate_limit(request, security.general_limiter, "hiring_listing")
    tab = tab if tab in ("matches", "candidates") else "matches"
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        if not j:
            return web.page(ui.page_head("Listing not found") + '<a class="b sec" href="/hiring">Your listings</a>', "Not found", active="/hiring", status=404)
        approved_emp = store.employer_approved(conn, user["id"])
        s = job_stats(conn, j)
        cands = store.rows(conn, "SELECT * FROM candidates WHERE job_id = ? AND archived = 0 ORDER BY updated_at DESC", (job_id,))
        if tab == "matches" and approved_emp:
            matches = ranked_matches(conn, j)
            content = _matches_html(conn, j, matches, {c["student_id"] for c in cands})
        elif tab == "candidates" and approved_emp:
            content = _candidates_html(conn, j, cands)
        else:
            content = ui.banner("info", "Ranked matches and student profiles open once a reviewer approves your organization. "
                                        "Your listing's stats are already counting.")
    state = store.listing_state(j)
    tone, label = STATE_PILL.get(state, ("", state))
    when = expiry_line(j)
    note = ui.banner(*DONE[done]) if done in DONE else ""
    rate = f'{round(100 * s["clicks"] / s["views"])}% of viewers' if s["views"] else ""
    stage_bits = " · ".join(f'{n} {STAGE_NAME.get(k, k).lower()}' for k, n in sorted(s["stages"].items(), key=lambda kv: [x[0] for x in STAGES].index(kv[0]) if kv[0] in STAGE_NAME else 99))
    week_note = f"{s['views_week']} this week"
    view_link = f'<a class="b sm sec" href="/job/{int(j["id"])}">View listing</a>' if state == "live" else ""
    body = (f'<a class="back" href="/hiring">← Your listings</a>{note}<div class="row between" style="align-items:flex-start;margin-top:6px">'
            f'<div><h2 class="page" style="margin:0">{esc(j["title"])}</h2><p class="job-co">{esc(j["company"])} · {esc(j["work_type"].title())}'
            f'{" · " + esc(j["location"]) if j["location"] else ""}</p></div><div class="row"><span class="pill {tone}">{esc(label)}</span>{view_link}</div></div>'
            f'<div class="lc card"><div class="lc-top"><b>Listing</b>{f"<span class=hj-when>{esc(when)}</span>" if when else ""}</div>{listing_controls(j, full=True)}</div>'
            f'{_funnel(s, (week_note, rate, "", stage_bits))}'
            f'<p class="small faint">Views and Apply clicks are totals. You see who a student is only when they message you, you invite them, or you save them from matches.</p>'
            + _tabs(job_id, tab, len(cands)) + content)
    return web.page(body, j["title"], active="/hiring")


def _matches_html(conn, j: dict, matches: list, saved: set[int]) -> str:
    live = store.visible_listing(j)
    note = ("" if live else ui.banner("info", "Invites open once this listing is approved. You can already see who fits and save them."))
    if not matches:
        return note + '<div class="empty">No students match yet. Matches come from students who made their profile visible to approved employers.</div>'
    strong = sum(1 for f, _ in matches if f["score"] >= 65)
    intro = (f'<p class="small muted" style="margin-bottom:12px"><b>{strong}</b> good or strong fit{"s" if strong != 1 else ""} among {len(matches)} students ranked. '
             'Each score uses the student\'s whole profile: skills, experience, projects, education, certifications and what they\'re looking for.</p>')
    return note + intro + "".join(_match_card(conn, j["id"], f, p, live, int(p["user_id"]) in saved) for f, p in matches)


def _candidates_html(conn, j: dict, cands: list[dict]) -> str:
    if not cands:
        return ('<div class="empty">No candidates yet. Students appear here when they apply here, when they message you about this listing, '
                'when you invite them, or when you save them from the ranked matches.</div>')
    csrf = ui.user_csrf_input()
    out = []
    apps = easyapply.applications_for(conn, j["id"])
    for c in cands:
        p = store.student_profile(conn, c["student_id"])
        if not p:
            continue
        f = fit.fit_score(j, p)
        convo = store.row(conn, "SELECT id FROM conversations WHERE student_id = ? AND employer_id = ? ORDER BY last_at DESC LIMIT 1",
                          (c["student_id"], j["employer_id"]))
        src, src_tone = SOURCES.get(c["source"], (c["source"], ""))
        opts = "".join(f'<option value="{k}"{" selected" if k == c["stage"] else ""}>{esc(v)}</option>' for k, v in STAGES)
        sub = " · ".join(x for x in (p["major"], p["grad_term"] and "Graduating " + p["grad_term"]) if x)
        msg = (f'<a class="b sm ghost" href="/messages/{int(convo["id"])}">Open conversation</a>' if convo else
               (f'<a class="b sm ghost" href="/messages/new?to={int(c["student_id"])}&amp;job={int(j["id"])}{"" if c["source"] == "applied" else "&amp;invite=1"}">'
                f'{"Message" if c["source"] == "applied" else "Invite to apply"}</a>'
                if store.visible_listing(j) and p["allow_messages"] else ""))
        out.append(f'<div class="card mcard" id="c{int(c["student_id"])}"><div class="row between" style="align-items:flex-start;gap:12px">'
                   f'<div class="row" style="gap:12px;align-items:center;min-width:0"><div class="ring sm" style="--p:{f["score"]}"><b>{f["score"]}%</b></div>'
                   f'<div style="min-width:0">{web.person(p["display_name"], sub, "stu", "/u/" + str(int(c["student_id"])))}</div></div>'
                   f'<div class="row"><span class="pill {src_tone}">{esc(src)}</span><span class="small faint">{esc(web.ago(c["created_at"]))}</span></div></div>'
                   f'<p class="small" style="margin-top:8px">{_evidence(f)}</p>{_reqs(f)}'
                   + (easyapply.application_html(apps[c["student_id"]], p) if c["student_id"] in apps else "") +
                   f'<form method="post" action="/hiring/{int(j["id"])}/stage" class="cform">{csrf}<input type="hidden" name="student" value="{int(c["student_id"])}">'
                   f'<div class="form-field"><label for="st{int(c["student_id"])}">Stage</label><select id="st{int(c["student_id"])}" name="stage">{opts}</select></div>'
                   f'<div class="form-field"><label for="nt{int(c["student_id"])}">Private note</label><input id="nt{int(c["student_id"])}" name="note" maxlength="{NOTE_MAX}" value="{esc(c["note"])}" placeholder="Only your team sees this"></div>'
                   f'<button class="b sm" type="submit">Update</button></form><div class="row" style="margin-top:8px">{msg}<a class="b sm ghost" href="/u/{int(c["student_id"])}">View profile</a></div></div>')
    return (_pipeline(cands) + '<p class="small muted" style="margin-bottom:12px">Stages and notes are private to your organization. '
            f'Archived candidates are in <a href="/hiring/applicants?job={int(j["id"])}&amp;show=archived">the applicant table</a>.</p>'
            + "".join(out))


@router.post("/hiring/{job_id}/save")
def save_match(job_id: int, request: Request, student: int = Form(0), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/hiring/{job_id}", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        p = store.row(conn, "SELECT visible_to_employers FROM student_profiles WHERE user_id = ?", (student,))
        if j and p and p["visible_to_employers"] and store.employer_approved(conn, user["id"]):
            add_candidate(conn, job_id, student, user["id"], "saved")
    return RedirectResponse(f"/hiring/{job_id}?tab=matches", status_code=303)


@router.post("/hiring/{job_id}/stage")
def set_stage(job_id: int, request: Request, student: int = Form(0), stage: str = Form(""), note: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/hiring/{job_id}?tab=candidates", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "hiring updates")
    note = security._CONTROL_CHARS_RE.sub("", note or "").strip()[:NOTE_MAX]
    if stage in STAGE_NAME:
        with store.db() as conn:
            if own_job(conn, user, job_id):
                conn.execute("UPDATE candidates SET stage = ?, note = ?, updated_at = ? WHERE job_id = ? AND student_id = ? AND employer_id = ?",
                             (stage, note, time.time(), job_id, student, user["id"]))
    return RedirectResponse(f"/hiring/{job_id}?tab=candidates#c{int(student)}", status_code=303)


# ---------- listing controls: pause, resume, close, expiry (edit and duplicate are in app.py; they re-scan) ----------

@router.post("/hiring/{job_id}/status")
def listing_status(job_id: int, request: Request, do: str = Form(""), back: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request, "employer")
    to = "/hiring" if back == "list" else f"/hiring/{int(job_id)}"
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(to, status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "listing changes")
    moves = {"pause": (("live",), "paused", "paused"), "resume": (("paused",), "open", "resumed"),
             "close": (("live", "paused", "expired"), "closed", "closed")}
    done = ""
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        if j and do in moves and store.listing_state(j) in moves[do][0]:
            conn.execute("UPDATE jobs SET listing_status = ? WHERE id = ? AND employer_id = ?", (moves[do][1], job_id, user["id"]))
            done = moves[do][2]
    return RedirectResponse(to + (f"?done={done}" if done else ""), status_code=303)


def _parse_date(v: str) -> float | None:
    try:
        return calendar.timegm(time.strptime((v or "").strip()[:10], "%Y-%m-%d")) + 86399      # the end of that day (UTC)
    except ValueError:
        return None


@router.post("/hiring/{job_id}/expiry")
def listing_expiry(job_id: int, request: Request, days: str = Form(""), date: str = Form(""), back: str = Form(""), csrf: str = Form("")):
    """Set how long a listing stays up: 7-120 days (from approval while it's in review, from now once it's live), or an end date."""
    user = web.require_user(request, "employer")
    to = "/hiring" if back == "list" else f"/hiring/{int(job_id)}"
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(to, status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "listing changes")
    now = time.time()
    lo, hi = store.LISTING_DAYS_MIN, store.LISTING_DAYS_MAX
    with store.db() as conn:
        j = own_job(conn, user, job_id)
        state = store.listing_state(j)
        if not j or state in ("closed", "rejected", "removed"):
            return RedirectResponse(to, status_code=303)
        ts = _parse_date(date) if date and state != "pending" else None
        if ts is not None:
            if not (now + (lo - 1) * 86400 < ts <= now + (hi + 1) * 86400):
                return RedirectResponse(to + "?done=badexpiry", status_code=303)
        else:
            d = int(days) if (days or "").isdigit() else 0
            if not lo <= d <= hi:
                return RedirectResponse(to + "?done=badexpiry", status_code=303)
            if state == "pending":
                conn.execute("UPDATE jobs SET expiry_days = ? WHERE id = ? AND employer_id = ?", (d, job_id, user["id"]))
                return RedirectResponse(to + "?done=extended", status_code=303)
            ts = now + d * 86400
        # A new date re-arms the reminder: expiry_reminded holds the date a reminder was sent for.
        conn.execute("UPDATE jobs SET expires_at = ? WHERE id = ? AND employer_id = ?", (ts, job_id, user["id"]))
    return RedirectResponse(to + "?done=extended", status_code=303)


def invite_text(conn, employer_id: int, student: dict, job: dict) -> str:
    e = store.employer_profile(conn, employer_id) or {}
    first = (student.get("display_name") or "").split(" ")[0]
    me = f"I'm {e['contact_name']}, {e['contact_title']} at {e['company']}. " if e.get("contact_name") and e.get("company") else ""
    return (f"Hi {first}! {me}Your profile looks like a strong fit for our {job['title']} role, and we'd love for you to apply. "
            "You'll find the listing and the Apply link on NoleCareerShield. Happy to answer any questions here.")
