"""The job board: a filter rail beside one column of wide result cards, and a full page per listing.

  * /jobs             a search box ("Describe a job you want") with a compact Jobs / Saved / Resume optimizer switch beside
                      it, a sticky filter rail of collapsible no-JS <details> sections (one "Filters" fold on phones), and
                      the results as cards whose left edge is coloured by the scam-check verdict. Every card opens /job/ID.
                      Old /jobs?job=ID links are redirected to /job/ID by app.py.
  * /job/ID           the listing: header, actions and the description on the left; a sticky column with the scam check,
                      the match card (with the per-job AI actions), "What they're looking for" and Meet the poster.
  * /job/ID/save      bookmark a job (students only). Saved jobs are private to the student (table saved_jobs).

Every card and listing keep the scam check: the risk pill, the verdict banner and the findings. Students also get a
match percentage and an Indeed-style "What they're looking for" list built from the employer's qualifications (quals.py)
and the requirements parsed from the description (fit.py). demo/app.js has a twin of everything here; change both.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import easyapply
import fit
import hiring
import matching
import network
import quals
import security
import defense
import store
import ui
import web
from ui import esc

router = APIRouter()

MAX_SAVED = 200
MAX_LIST = 60
KINDS = [("full-time", "Full-time"), ("internship", "Internship"), ("part-time", "Part-time")]
KIND_LABEL = {"full-time": "Full-time", "internship": "Internship", "part-time": "Part-time", "on-campus": "On-campus"}
WHEN = [(0, "Any time"), (1, "Past 24 hours"), (7, "Past week"), (30, "Past month")]
SORTS = [("relevant", "Most relevant"), ("recent", "Most recent")]
LEVEL_NAME = {"high": "High", "medium": "Medium", "low": "Low"}
_NEXT = re.compile(r"^/jobs(?:\?[A-Za-z0-9_=&%.+\-]{0,500})?$|^/job/\d{1,9}$")


def safe_next(value: str, default: str = "/jobs") -> str:
    v = (value or "").strip()
    return v if _NEXT.fullmatch(v) else default


# ---------- saved jobs ----------

def saved_ids(conn, uid: int) -> list[int]:
    return [r[0] for r in conn.execute("SELECT job_id FROM saved_jobs WHERE user_id = ? ORDER BY created_at DESC", (uid,))]


def bookmark(filled: bool = False, size: int = 20) -> str:
    return (f'<svg class="ic" viewBox="0 0 24 24" width="{size}" height="{size}" fill="{"currentColor" if filled else "none"}" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4h12v17l-6-4.2L6 21z"/></svg>')


def save_button(job_id: int, saved: bool, next_: str, label: bool = False) -> str:
    action, text = ("unsave", "Remove from saved jobs") if saved else ("save", "Save job")
    inner = bookmark(saved, 18) + (f'<span>{"Saved" if saved else "Save"}</span>' if label else "")
    return (f'<form method="post" action="/job/{int(job_id)}/{action}" class="navform jc-sv">{ui.user_csrf_input()}<input type="hidden" name="next" value="{esc(next_)}">'
            f'<button type="submit" class="{"sv-l" if label else "sv-i"}{" on" if saved else ""}" aria-label="{text}" title="{text}" aria-pressed="{"true" if saved else "false"}">{inner}</button></form>')


@router.post("/job/{job_id}/save")
def save(job_id: int, request: Request, next: str = Form(""), csrf: str = Form("")):
    return _toggle(job_id, request, next, csrf, True)


@router.post("/job/{job_id}/unsave")
def unsave(job_id: int, request: Request, next: str = Form(""), csrf: str = Form("")):
    return _toggle(job_id, request, next, csrf, False)


def _toggle(job_id: int, request: Request, next_: str, csrf: str, on: bool):
    user = web.require_user(request, "student")
    back = RedirectResponse(safe_next(next_, f"/job/{int(job_id)}"), status_code=303)
    if not web.csrf_ok(request, csrf):
        return back
    security.enforce_key_limit(security.profile_limiter, f"s{user['id']}", "saving jobs")
    with store.db() as conn:
        if on:
            row = conn.execute(f"SELECT 1 FROM jobs WHERE id = ? AND {store.live_where()}", (job_id,)).fetchone()
            have = conn.execute("SELECT COUNT(*) FROM saved_jobs WHERE user_id = ?", (user["id"],)).fetchone()[0]
            if row and have < MAX_SAVED:
                conn.execute("INSERT OR IGNORE INTO saved_jobs (user_id, job_id, created_at) VALUES (?,?,?)", (user["id"], job_id, time.time()))
        else:
            conn.execute("DELETE FROM saved_jobs WHERE user_id = ? AND job_id = ?", (user["id"], job_id))
    return back


# ---------- what a listing is (twins in demo/app.js) ----------

def kinds_of(j: dict) -> list[str]:
    low = " " + f"{j.get('title', '')}\n{j.get('description', '')}".lower() + " "
    return [k for k, words in matching.KIND_WORDS.items() if any(w in low for w in words)]


def days_old(j: dict) -> float:
    return matching._days_old(j.get("created_at", ""))


def posted(j: dict) -> str:
    d = int(days_old(j))
    return "Posted today" if d < 1 else "Posted yesterday" if d < 2 else f"Posted {d} days ago" if d < 14 else f"Posted {d // 7} weeks ago"


def where(j: dict) -> str:
    return j.get("location") or ("Remote" if j.get("work_type") == "remote" else "")


def parse_params(q: dict, is_student: bool) -> dict:
    """Query string to filters. Anything unexpected is dropped, never trusted."""
    def pick(name, allowed, default=""):
        v = (q.get(name) or "").strip()
        return v if v in allowed else default
    p = {"search": (q.get("search") or "").strip()[:200],
         "category": pick("category", matching.CATEGORIES), "work_type": pick("work_type", matching.WORK_TYPES),
         "kind": pick("kind", [k for k, _ in KINDS]), "loc": (q.get("loc") or "").strip()[:60],
         "when": int(q["when"]) if str(q.get("when", "")) in ("1", "7", "30") else 0,
         "quick": 1 if str(q.get("quick", "")) == "1" else 0,
         "following": 1 if (is_student and str(q.get("following", "")) == "1") else 0,
         "sort": pick("sort", [s for s, _ in SORTS], "relevant"),
         "tab": "saved" if (is_student and q.get("tab") == "saved") else "jobs"}
    return p


def old_pane_link(q: dict) -> int:
    """/jobs?job=ID was the old two-pane address; app.py sends it on to /job/ID. 0 when there's no usable id."""
    v = str(q.get("job") or "").strip()
    return int(v) if v.isdigit() and 0 < len(v) <= 9 else 0


def board_url(p: dict, **over) -> str:
    """The board's address for these filters, with some overridden (None or 0 or '' removes one)."""
    cur = {**p, **over}
    qs = {}
    for k in ("tab", "search", "category", "work_type", "kind", "loc", "when", "quick", "following", "sort"):
        v = cur.get(k)
        if v in (None, "", 0) or (k == "tab" and v == "jobs") or (k == "sort" and v == "relevant"):
            continue
        qs[k] = v
    return "/jobs" + ("?" + urlencode(qs) if qs else "")


def filter_jobs(jobs: list[dict], p: dict, followed: set | None) -> list[dict]:
    out = []
    for j in jobs:
        if p["category"] and j["category"] != p["category"]:
            continue
        if p["work_type"] and j["work_type"] != p["work_type"]:
            continue
        if p["kind"] and p["kind"] not in kinds_of(j):
            continue
        if p["when"] and days_old(j) > p["when"]:
            continue
        if p["quick"] and not easyapply.is_easy(j):
            continue
        if p["loc"] and (j.get("location") or "").lower() != p["loc"].lower():
            continue
        if followed is not None and j.get("employer_id") not in followed:
            continue
        out.append(j)
    return out


def rank(jobs: list[dict], p: dict, profile: dict | None) -> list[dict]:
    """[{job, fit (percent or None)}] in the order shown. A search is read as a description of the job wanted
    (matching.parse_query); a plain phrase that appears in the title, company or description also counts."""
    search = p["search"]
    ranked = matching.rank_jobs(jobs, profile, search, 999)
    seen = {r["job"]["id"] for r in ranked}
    if search:
        term = search.lower()
        extra = [j for j in jobs if j["id"] not in seen and any(term in (j.get(f) or "").lower() for f in ("title", "company", "description"))]
        ranked += [{"job": j, "score": 0} for j in extra]
    if p["sort"] == "recent":
        ranked.sort(key=lambda r: r["job"].get("created_at", ""), reverse=True)
    return [{"job": r["job"], "fit": r["fit"]["score"] if r.get("fit") else None} for r in ranked]


def has_profile(profile: dict | None) -> bool:
    return bool(profile and (profile.get("skills") or profile.get("resume_text") or profile.get("items")))


def level_of(pct: int) -> str:
    return "high" if pct >= 75 else "medium" if pct >= 50 else "low"


# ---------- the list ----------

def verdict_class(j: dict) -> str:
    """Card edge colour: the scam-check verdict (v-clear / v-flagged / v-held) plus the gauge zone (z0-z3), so a flagged
    listing high on the gauge reads orange or red rather than amber. Twin: jbVerdict in demo/app.js."""
    lead_gen = any(f.get("rule_id") == "lead_gen" for f in json.loads(j.get("findings_json") or "[]"))
    zone = ui.risk_position(int(j.get("score") or 0), j.get("scam_status", ""), aggregator=lead_gen)[0]
    status = j.get("scam_status") if j.get("scam_status") in ("clear", "flagged", "held") else "flagged"
    return f"v-{status} z{zone}"


def card(j: dict, p: dict, *, fitpct, saved: bool | None, pill: str) -> str:
    jid = int(j["id"])
    match = f'<span class="jc-match {level_of(fitpct)}">{fitpct}% match</span>' if fitpct is not None else ""
    tags = pill + match + ('<span class="jc-tag q">Quick apply</span>' if easyapply.is_easy(j) else "") + ('<span class="jc-tag n">New</span>' if days_old(j) < 7 else "")
    place, setting = where(j), j["work_type"].title()
    facts = " · ".join(x for x in (place, "" if place == setting else setting, ", ".join(KIND_LABEL[k] for k in kinds_of(j)[:2])) if x)
    sv = save_button(jid, bool(saved), board_url(p)) if saved is not None else ""
    return (f'<article class="jc {verdict_class(j)}"><span class="jc-logo" aria-hidden="true">{ui.initials(j["company"])}</span>'
            f'<div class="jc-body"><h3 class="jc-title"><a class="jc-link" href="/job/{jid}">{esc(j["title"])}</a></h3>'
            f'<div class="jc-co">{esc(j["company"])} <span class="jc-cat">· {esc(j["category"])}</span></div>'
            f'<div class="jc-facts">{esc(facts)}</div><div class="jc-tags">{tags}</div></div>{sv}</article>')


def _opt(label: str, href: str, on: bool, kind: str = "check") -> str:
    """One rail option: a plain link drawn as a checkbox (toggles) or a radio (pick one)."""
    return (f'<a class="jb-opt {kind}{" on" if on else ""}" href="{esc(href)}"{" aria-current=true" if on else ""}>'
            f'<i aria-hidden="true"></i><span>{esc(label)}</span></a>')


def _sec(title: str, opts: list[str], open_: bool) -> str:
    return (f'<details class="jb-sec"{" open" if open_ else ""}><summary>{esc(title)}<i class="car" aria-hidden="true"></i></summary>'
            f'<div class="jb-opts">{"".join(opts)}</div></details>')


def active_filters(p: dict) -> int:
    return sum(1 for k in ("category", "work_type", "kind", "loc", "when", "quick", "following") if p[k])


def rail_sections(p: dict, jobs_all: list[dict], is_student: bool) -> str:
    """The filter sections. Every option is a link to the board with that filter toggled: nothing needs JavaScript."""
    locs: dict[str, int] = {}
    for j in jobs_all:
        if j.get("location"):
            locs[j["location"]] = locs.get(j["location"], 0) + 1
    top = [l for l, _ in sorted(locs.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:8]]
    cats = sorted({j["category"] for j in jobs_all})
    more = [_opt("Quick apply", board_url(p, quick=0 if p["quick"] else 1), bool(p["quick"]))]
    if is_student:
        more.append(_opt("From companies I follow", board_url(p, following=0 if p["following"] else 1), bool(p["following"])))
    secs = [
        _sec("Job type", [_opt(label, board_url(p, kind=None if p["kind"] == k else k), p["kind"] == k) for k, label in KINDS], True),
        _sec("Date posted", [_opt(t, board_url(p, when=d), p["when"] == d, "radio") for d, t in WHEN], True),
        _sec("Location", [_opt("Any location", board_url(p, loc=None), not p["loc"], "radio")]
             + [_opt(l, board_url(p, loc=None if p["loc"].lower() == l.lower() else l), p["loc"].lower() == l.lower(), "radio") for l in top]
             + [_opt("Remote only", board_url(p, work_type="remote" if p["work_type"] != "remote" else None), p["work_type"] == "remote")], True),
        _sec("Work setting", [_opt(w.title(), board_url(p, work_type=None if p["work_type"] == w else w), p["work_type"] == w) for w in matching.WORK_TYPES],
             bool(p["work_type"])),
        _sec("Category", [_opt("All categories", board_url(p, category=None), not p["category"], "radio")]
             + [_opt(c, board_url(p, category=None if p["category"] == c else c), p["category"] == c, "radio") for c in cats], bool(p["category"])),
        _sec("More", more, True),
    ]
    return "".join(secs)


def rail(p: dict, jobs_all: list[dict], is_student: bool) -> str:
    """Wide screens: a sticky rail. Phones and narrow windows: the same sections folded into one "Filters" <details>
    above the results (two copies because CSS can't force a closed <details> open; only one is ever displayed)."""
    n = active_filters(p)
    clear = '<a class="jb-clear" href="/jobs">Clear all</a>' if (n or p["search"]) else ""
    secs = rail_sections(p, jobs_all, is_student)
    badge = f'<span class="jb-n">{n}</span>' if n else ""
    return (f'<aside class="jb-rail" aria-label="Filters"><div class="jb-rail-h"><h2>Filters{badge}</h2>{clear}</div>{secs}</aside>'
            f'<details class="jb-mf"><summary><span>Filters{badge}</span><i class="car" aria-hidden="true"></i></summary>'
            f'<div class="jb-mf-b">{secs}{f"<div class=jb-mf-c>{clear}</div>" if clear else ""}</div></details>')


def search_box(p: dict) -> str:
    hidden = "".join(f'<input type="hidden" name="{k}" value="{esc(p[k])}">' for k in ("category", "work_type", "kind", "loc", "when", "quick", "following", "sort") if p[k])
    return (f'<form class="jb-search" method="get" action="/jobs" role="search"><label class="sr" for="jb-q">Describe a job you want</label>'
            f'<input id="jb-q" name="search" value="{esc(p["search"])}" placeholder="Describe a job you want" maxlength="200" autocomplete="off">{hidden}'
            f'<button type="submit">Search</button></form>')


def tabs(p: dict, is_student: bool, n_saved: int) -> str:
    """Jobs / Saved / Resume optimizer as a compact segmented control. Employers only have the board, so they get none."""
    if not is_student:
        return ""
    items = [("Jobs", "/jobs", p["tab"] == "jobs"), (f"Saved{f' ({n_saved})' if n_saved else ''}", "/jobs?tab=saved", p["tab"] == "saved"),
             ("Resume optimizer", "/resume", False)]
    return '<nav class="jb-seg" aria-label="Jobs">' + "".join(f'<a href="{h}"{" class=on aria-current=page" if on else ""}>{esc(t)}</a>' for t, h, on in items) + "</nav>"


def _menu(label: str, items: list[tuple[str, str, bool]], active: bool, cls: str = "") -> str:
    links = "".join(f'<a href="{esc(h)}"{" class=on aria-current=true" if on else ""}>{esc(t)}</a>' for t, h, on in items)
    return f'<details class="jb-dd {cls}"><summary class="jb-chip{" on" if active else ""}">{esc(label)}<i class="car"></i></summary><div class="jb-menu">{links}</div></details>'


def board(conn, viewer: dict, q: dict, jobs_all: list[dict], *, pill, risk=None) -> str:
    """The whole /jobs body. jobs_all: every live approved listing. pill(j) is the app's scam-check pill."""
    is_student = viewer["role"] == "student"
    p = parse_params(q, is_student)
    profile = store.student_profile(conn, viewer["id"]) if is_student else None
    rich = has_profile(profile)
    saved = saved_ids(conn, viewer["id"]) if is_student else []
    followed = set(network.followed_ids(conn, viewer["id"])) if (is_student and p["following"]) else None
    if p["tab"] == "saved":
        by_id = {j["id"]: j for j in jobs_all}
        pool = [by_id[i] for i in saved if i in by_id]
        ranked = [{"job": j, "fit": None} for j in pool]
        if rich:
            fm = {r["job"]["id"]: r["fit"] for r in rank(pool, {**p, "search": "", "sort": "relevant"}, profile)}
            ranked = [{"job": j, "fit": fm.get(j["id"])} for j in pool]
    else:
        ranked = rank(filter_jobs(jobs_all, p, followed), p, profile if rich else None)
    ranked = ranked[:MAX_LIST]
    saved_set = set(saved)
    cards = "".join(card(r["job"], p, fitpct=r["fit"] if rich else None,
                         saved=(r["job"]["id"] in saved_set) if is_student else None, pill=pill(r["job"])) for r in ranked)
    n = len(ranked)
    if p["tab"] == "saved":
        head = f'<div class="jb-count"><span>{n} saved job{"s" if n != 1 else ""}</span></div>'
        empty = ('<div class="empty">' + bookmark(False, 36) + '<p style="margin:10px 0 12px">No saved jobs yet. Tap the bookmark on any job to keep it here.</p>'
                 '<a class="b sec" href="/jobs">Browse jobs</a></div>')
    else:
        sort = _menu("Sort by " + dict(SORTS)[p["sort"]], [(t, board_url(p, sort=s), p["sort"] == s) for s, t in SORTS], False, "sort")
        forq = f" for “{esc(p['search'])}”" if p["search"] else ""
        head = f'<div class="jb-count"><span>{n} job{"s" if n != 1 else ""}{forq}</span>{sort}</div>'
        empty = ('<div class="empty">Nothing from companies you follow right now. <a href="/network?tab=following">Who you follow</a></div>' if p["following"] else
                 '<div class="empty">No listings match. Try clearing filters or describing the job differently.</div>')
    side = rail(p, jobs_all, is_student) if p["tab"] == "jobs" else ""
    return (f'<div class="jb"><div class="jb-top">{search_box(p)}{tabs(p, is_student, len(saved))}</div>'
            f'<div class="jb-grid{"" if side else " solo"}">{side}<section class="jb-list" id="jb-list" aria-label="Results">{head}{cards or empty}</section></div></div>')


# ---------- the detail ----------

def marker(item: dict, chosen: dict) -> str:
    """Required or Preferred. The employer's own ticks win; otherwise what the description says."""
    t = item["text"].lower().replace(" (preferred)", "")
    for k in (t, t.split(":", 1)[-1].strip()):
        if k in chosen:
            return "Required" if chosen[k] else "Preferred"
    for k, must in chosen.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"s?(?![a-z0-9])", t):
            return "Required" if must else "Preferred"
    if "(preferred)" in item["text"].lower():
        return "Preferred"
    return "Required"


def quals_block(job: dict, f: dict | None, personal: bool) -> str:
    """Indeed-style 'What they're looking for'. personal: the viewer is a student with a profile, so each line is marked
    met, missing or unknown; otherwise it lists the same qualifications without judging anyone."""
    chosen = {q["label"].lower(): bool(q.get("must")) for q in quals.of(job)}
    base = f if f is not None else fit.fit_score(job, {})
    items = base["checklist"]
    if not items:
        return ('<section class="jq"><h3>What they’re looking for</h3><p class="jq-sum muted">The employer hasn’t listed specific qualifications, and the description doesn’t name any.</p></section>')
    marks = {"met": ("✓", "met", "You have this"), "missing": ("⊘", "missing", "Not on your profile yet"), "unknown": ("?", "unknown", "Not enough on your profile to tell")}
    rows = ""
    for c in items:
        st, cls, tip = marks[c["status"]] if personal else ("•", "plain", "")
        text = re.sub(r"\s*\(preferred\)$", "", c["text"])
        rows += (f'<li class="{cls}"><span class="mk" aria-hidden="true">{st}</span><div><span class="sr">{esc(tip)}: </span>{esc(text)}'
                 f'<em class="rq {marker(c, chosen).lower()}">{marker(c, chosen)}</em></div></li>')
    met = sum(1 for c in items if c["status"] == "met")
    summ = (f'<p class="jq-sum"><b>You match {met} of {len(items)} qualifications</b></p>' if personal else
            f'<p class="jq-sum muted">{len(items)} qualification{"s" if len(items) != 1 else ""} from the employer and the description.</p>')
    note = '<p class="jq-note">Matching is based on your profile. <a href="/profile">Update profile</a></p>' if personal else ""
    return f'<section class="jq"><h3>What they’re looking for</h3>{summ}<ul class="jq-list">{rows}</ul>{note}</section>'


CONF = {"low": "Your profile is thin, so this is a rough estimate. Add experience, projects and a resume to sharpen it.",
        "medium": "Based on part of your profile. Adding more sections makes it more accurate.",
        "high": "Based on your whole profile: skills, resume, experience, projects, education and what you're looking for."}


def match_panel(job: dict, f: dict | None) -> str:
    if f is None:
        return ('<section class="jm"><h3>Job match</h3><p class="muted small">Add your skills, experience or resume and every listing shows how well you match, built from your whole profile.</p>'
                '<div class="row" style="margin-top:10px"><a class="b sm" href="/profile">Build my profile</a><a class="b sm sec" href="/resume">Add my resume</a></div></section>')
    pct, lvl = f["percent"], f["level"]
    parts = "".join(f'<div class="cat"><span>{esc(x["name"])}</span><div class="meter{" ok" if x["score"] >= 75 else " warn" if x["score"] < 40 else ""}">'
                    f'<i style="width:{x["score"]}%"></i></div><span>{x["score"]}%</span><div class="why2">{esc(x["detail"])}</div></div>' for x in f["parts"])
    found = "".join(f'<li><b>{esc(m["skill"])}</b><span class="ev">Found in {esc(", ".join(w.replace("Your ", "your ", 1) for w in m["where"][:2]))}</span></li>' for m in f["matched"][:6])
    spark = ui.icon("spark", 15)
    more = (f'<details class="jm-more"><summary class="jm-ai-b">{spark}<span>Show match details</span></summary><div class="jm-more-b"><div class="fitparts">{parts}</div>'
            + (f'<h4 class="small" style="margin:12px 0 6px">Where your profile backs it up</h4><ul class="jm-found">{found}</ul>' if found else "") + '</div></details>')
    return (f'<section class="jm" id="fit"><div class="jm-head"><h3>Job match is <span class="jm-lvl {lvl}">{LEVEL_NAME[lvl]}</span></h3><span class="jm-pct">{pct}%</span></div>'
            f'<div class="jm-meter {lvl}" style="--pos:{pct}%" role="img" aria-label="Job match {pct} percent, {LEVEL_NAME[lvl].lower()}"><i></i><i></i><i></i><b></b></div>'
            f'<div class="jm-scale" aria-hidden="true"><span>Low</span><span>Medium</span><span>High</span></div><p class="jm-conf">{esc(CONF[f["confidence"]])}</p>'
            f'{ai_actions(job, more)}</section>')


def ai_actions(job: dict, more: str) -> str:
    """The per-job helper row in the match card: match details (a <details>), then links to the tailoring pages that
    resume_tools.py serves for this listing."""
    jid = int(job["id"])
    spark = ui.icon("spark", 15)
    links = [(f"/job/{jid}/tailor", "Tailor my resume"), (f"/job/{jid}/standout", "Help me stand out"),
             (f"/job/{jid}/tailor?mode=note", "Draft a note to the poster")]
    return ('<div class="jm-ai" role="group" aria-label="Help with this job">' + more
            + "".join(f'<a class="jm-ai-b" href="{esc(h)}">{spark}<span>{esc(t)}</span></a>' for h, t in links) + "</div>")


def glance(j: dict) -> str:
    kinds = ", ".join(KIND_LABEL[k] for k in kinds_of(j)) or "Not stated"
    how = "Quick apply on NoleCareerShield" if easyapply.is_easy(j) else ("Employer’s site" if j.get("apply_url") else "Contact the employer")
    rows = [("Posted", posted(j).replace("Posted ", "").capitalize()), ("Job type", kinds), ("Work setting", j["work_type"].title()),
            ("Location", where(j) or "Not stated"), ("Category", j["category"]), ("How to apply", how)]
    return ('<section class="jg"><h3>At a glance</h3><dl>' + "".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in rows) + "</dl></section>")


def scam_block(j: dict, pill: str, risk: str) -> str:
    findings = json.loads(j.get("findings_json") or "[]")
    if j["scam_status"] == "clear":
        banner = '<div class="banner verified">✓ This listing passed the scam check and was approved by a reviewer. Still verify the employer through their own website before sharing personal information.</div>'
    else:
        banner = '<div class="banner warning">⚠ This listing was approved but tripped some scam signals. Read the notes below and verify the employer independently before responding.</div>'
    items = ""
    if j["scam_status"] != "clear":
        items = "".join(f'<div class="finding {f["severity"]}"><b>{esc(f["title"])}</b><br>{esc(f["why"])}</div>' for f in findings if f["severity"] in ("critical", "warning"))
        items = f'<div class="jd-find"><b style="font-size:14px">Signals to be aware of:</b>{items}</div>' if items else ""
    return f'<section class="js"><div class="js-top"><h3>Scam check</h3>{pill}</div>{risk}{banner}{items}</section>'


QUICK_NOTE = ('<p class="qa-note">Quick apply makes job applications short and sweet. However, experts recommend '
              'applying directly on company websites.</p>')


def applied(conn, job_id: int, student_id: int) -> bool:
    """Has this student applied: through Quick apply, or by opening the employer's own application link."""
    return bool(conn.execute("SELECT 1 FROM applications WHERE job_id = ? AND student_id = ?", (job_id, student_id)).fetchone()
                or conn.execute("SELECT 1 FROM job_apply_clicks WHERE job_id = ? AND user_id = ?", (job_id, student_id)).fetchone())


_HONORIFIC = {"dr", "mr", "mrs", "ms", "mx", "prof", "professor"}


def short_name(name: str) -> str:
    """'Dana Whitfield' -> 'Dana'; 'Dr. Priya Shah' -> 'Dr. Shah'."""
    w = name.split()
    return f"{w[0]} {w[-1]}" if len(w) > 1 and w[0].rstrip(".").lower() in _HONORIFIC else w[0]


def poster_block(conn, viewer: dict, j: dict, emp_ok: bool) -> str:
    """Who posted the listing. Students who applied can message them; the email shows only if the poster chose that."""
    if not j.get("employer_id"):
        return ""
    ep = store.employer_profile(conn, j["employer_id"]) or {}
    name = (j.get("poster_name") or ep.get("contact_name") or "").strip()
    title = (j.get("poster_title") or ep.get("contact_title") or "").strip()
    if not name:
        name = "The hiring team"
    email = ""
    if j.get("show_email"):
        r = conn.execute("SELECT email FROM users WHERE id = ?", (j.get("posted_by") or j["employer_id"],)).fetchone()
        if r:
            email = f'<a class="jp-mail" href="mailto:{esc(r[0])}">{ui.icon("mail", 14)} {esc(r[0])}</a>'
    first = "the hiring team" if name == "The hiring team" else esc(short_name(name))
    act = ""
    if viewer["role"] == "student" and emp_ok:
        if applied(conn, int(j["id"]), viewer["id"]):
            act = f'<a class="b" href="/messages/new?to={int(j["employer_id"])}&amp;job={int(j["id"])}">{ui.icon("chat", 16)} Message {first}</a>'
        else:
            act = f'<p class="jp-hint">You can message {first} once you apply.</p>'
    who = esc(title + (" at " if title else "") + j["company"])
    return (f'<section class="jp"><h3>Meet the poster</h3><div class="jp-row"><span class="jc-logo" aria-hidden="true">{ui.initials(name)}</span>'
            f'<div class="jp-who"><b>{esc(name)}</b><span>{who}</span>{email}</div>{act}</div></section>')


def detail(conn, viewer: dict, j: dict, profile: dict | None, *, pill, risk, next_: str, record: bool, saved: bool | None, extra: str = "") -> str:
    """The /job/ID page. Left: header and actions, About the job, At a glance, then extra (the tailoring kit). Right, sticky:
    scam check, match card, What they're looking for, Meet the poster. Phones: one column, the right column after the header."""
    jid = int(j["id"])
    is_student = viewer["role"] == "student"
    emp_ok = bool(j.get("employer_id")) and store.employer_approved(conn, j["employer_id"])
    trust = ""
    co = esc(j["company"])
    if emp_ok:
        import employer_page
        trust = employer_page.trust_pill(employer_page.trust(conn, j["employer_id"]), "/company/%d#trust" % int(j["employer_id"]))
        co = f'<a href="/company/{int(j["employer_id"])}">{co}</a>'
    apply = ""
    banner = ""
    following = False
    done = None
    if is_student:
        if record:
            hiring.record_view(conn, jid, viewer["id"])
        if easyapply.is_easy(j):
            done = easyapply.application(conn, jid, viewer["id"])
        following = network.is_following(conn, viewer["id"], j["employer_id"]) if emp_ok else False
        if easyapply.is_easy(j):
            if done:
                banner = f'<div class="banner verified">✓ You applied {esc(web.ago(done["created_at"]))}. <a href="/applications">Your applications</a></div>'
            elif emp_ok:
                apply = f'<a class="apply-btn" href="/job/{jid}/easy">Quick apply →</a>'
                if j["apply_url"]:
                    apply += f'<a class="b ghost" href="/job/{jid}/apply" target="_blank" rel="noopener noreferrer nofollow ugc">Apply on company site</a>'
            elif j["contact"]:
                banner = f'<p style="font-size:14px;color:var(--muted)">Contact: {esc(j["contact"])}</p>'
        elif j["apply_url"]:
            apply = f'<a class="apply-btn" href="/job/{jid}/apply" target="_blank" rel="noopener noreferrer nofollow ugc">Apply →</a>'
        elif j["contact"]:
            banner = f'<p style="font-size:14px;color:var(--muted)">Contact: {esc(j["contact"])}</p>'
    else:
        apply = (f'<a class="apply-btn" href="/login/student?next=/job/{jid}">Log in as an FSU student to apply</a>')
    acts = apply
    if saved is not None:
        acts += save_button(jid, saved, next_, label=True)
    if is_student and emp_ok:
        acts += network.follow_button(int(j["employer_id"]), following, next_=f"/job/{jid}", small=False)
    own = ""
    if viewer["role"] == "employer" and j.get("employer_id") == store.org_id(viewer):
        own = f'<div class="banner info">This is your listing. <a href="/hiring/{jid}">See ranked student matches, candidates and stats →</a></div>'
    f = fit.fit_score(j, profile) if (is_student and has_profile(profile)) else None
    match = match_panel(j, f) if is_student else ""
    q = quals_block(j, f, personal=f is not None)
    sub = " · ".join(x for x in (where(j), "" if where(j) == j["work_type"].title() else j["work_type"].title(), posted(j)) if x)
    note = QUICK_NOTE if (is_student and easyapply.is_easy(j) and not done) else ""
    top = (f'<div class="jd-top"><div class="jd-head"><span class="jc-logo lg" aria-hidden="true">{ui.initials(j["company"])}</span><div class="jd-h">'
           f'<div class="jd-co">{co}</div><h1 class="jd-title">{esc(j["title"])}</h1><div class="jd-sub">{esc(sub)}</div>'
           f'{f"<div class=jd-trust>{trust}</div>" if trust else ""}</div></div>{own}<div class="jd-acts">{acts}</div>{note}{banner}</div>')
    side = f'<aside class="jd-side" aria-label="Scam check and fit">{scam_block(j, pill(j), risk(j))}{match}{q}{poster_block(conn, viewer, j, emp_ok)}</aside>'
    body = (f'<div class="jd-body"><section class="jd-desc"><h2>About the job</h2><div class="detail-desc">{esc(defense.with_fingerprint(j["description"], j["id"]))}</div></section>'
            f'{glance(j)}{extra}</div>')
    return (f'<a class="back jd-back" href="/jobs">← All jobs</a><article class="jd {verdict_class(j)}">{top}{side}{body}</article>')
