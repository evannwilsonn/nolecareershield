"""
The FSU feed: a community board where only verified FSU students and approved employers post.

  * Students (confirmed @fsu.edu) post questions, advice, wins, events and opportunities.
    Posts publish right away unless the scam scanner flags them, in which case a reviewer
    checks them first.
  * Approved employers post opportunities, advice, events and info sessions, and every
    employer post must be relevant to FSU students. A relevance check rejects ads and
    off-topic posts on the spot (with the reason), and the rest wait for a reviewer.
  * Anyone signed in can mark a post helpful, comment, or report it. Three reports from
    different people hide a post until a reviewer looks.
Visitors who aren't signed in see an explanation, not the posts.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import ai
import css_feed  # noqa: F401  (appends the feed styles to ui.CSS)
import events
import msgcheck
import network
import profiles
import security
import store
import ui
import web
from ui import esc

router = APIRouter()

KINDS = {"question": "Question", "advice": "Advice", "opportunity": "Opportunity", "event": "Event",
         "win": "Win", "info_session": "Info session"}
FILTER_LABELS = {"question": "Questions", "advice": "Advice", "opportunity": "Opportunities", "event": "Events",
                 "win": "Wins", "info_session": "Info sessions"}
STUDENT_KINDS = ["question", "advice", "opportunity", "event", "win"]
EMPLOYER_KINDS = ["opportunity", "advice", "event", "info_session"]
MAX_POST, MAX_COMMENT = 1500, 500
HIDE_AFTER_REPORTS = 3
MAX_SAVES = 300
PAGE = 20
PILLS = [("all", "All"), ("major", "My major"), ("employers", "Employers")]     # the f= filters behind the Showing menu
# The one "Showing:" menu: (key, label, hint, tab, f). Employers get no For you or My major.
SHOWS = [("everyone", "Everyone", "Every post, newest first", "feed", "all"),
         ("foryou", "For you", "Ranked by your major and skills", "foryou", "all"),
         ("major", "My major", "Students in your major", "feed", "major"),
         ("employers", "Employers", "Posts from approved employers", "feed", "employers"),
         ("saved", "Saved", "Posts you bookmarked", "saved", "all")]
EMPLOYER_GUIDELINES = ["Post opportunities, events or advice for FSU students.", "No ads, promotions or pay-to-apply offers.",
                       "A reviewer approves every employer post.", "Never ask students for passwords, SSNs or bank details."]
GUIDELINES = ["Be kind and specific. Help each other out.", "No ads, spam or pay-to-apply offers.",
              "Never share passwords, SSNs or bank details.", "Report anything that feels like a scam."]
_STOP = set("""about above after again also always another anyone around because before being between both come could does doing done down
each even ever every from get going good great have having here hello help how into just know like look make many more most much need only
other over please really should some someone something still such take than thank thanks that their them then there these they thing think
this those through today want week were what when where which while will with would year your students student fsu florida state
university apply hiring internship internships""".split())
_SAVE_NEXT = re.compile(r"^/feed(?:/\d{1,9})?(?:\?[A-Za-z0-9_=&%.+-]{0,150})?$")

FSU_SIGNALS = re.compile(
    r"\b(?:fsu|florida state|noles?|seminoles?|tallahassee|students?|interns?|internships?|new grads?|recent grads?|"
    r"entry[- ]level|career fair|career expo|info(?:rmation)? sessions?|on[- ]campus|campus|co-?ops?|graduat\w*|resumes?|"
    r"interview\w*|mentor\w*|scholarships?|apprentice\w*|part[- ]time|first job|early[- ]career|class of 20\d\d|"
    r"undergrad\w*|majors?|hiring|job shadow\w*|externships?|fellowships?|networking)\b", re.IGNORECASE)
PROMO = re.compile(
    r"\b(?:\d{1,2}\s?% off|discounts?|promo codes?|coupons?|sale ends|buy now|shop now|order now|limited[- ]time offer|"
    r"free trial|use code|deal of the|giveaway|dm to buy|link in bio|subscribe to|our newsletter|crypto|nft|forex|"
    r"be your own boss|unlimited income|residual income|financial freedom|passive income|side hustle that pays)\b", re.IGNORECASE)


def relevance(body: str, kind: str, link: str = "") -> dict:
    """Is an employer post for FSU students? ok only when it names who it's for and doesn't read like an ad."""
    text = f"{body}\n{link}"
    signals = sorted({m.group(0).lower() for m in FSU_SIGNALS.finditer(text)})
    promo = sorted({m.group(0).lower() for m in PROMO.finditer(text)})
    problems = []
    if promo:
        problems.append("It reads like an ad or promotion (" + ", ".join(promo[:3]) + "). The feed is for opportunities and advice, not marketing.")
    if not signals:
        problems.append("It doesn't say how it helps FSU students. Mention the role, internship, event or advice and who it's for.")
    if kind == "opportunity" and not re.search(r"\b(?:apply|application|role|position|job|intern\w*|hiring|opening|deadline|pay|paid|\$\d)", text, re.IGNORECASE):
        problems.append("An opportunity post should say what the role is and how to apply.")
    return {"ok": not problems, "signals": signals[:6], "problems": problems}


def ai_relevance(body: str, company: str) -> dict | None:
    schema = {"type": "object", "properties": {
        "relevant": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["relevant", "reason"]}
    system = ("You moderate a feed for Florida State University students. Employers may post only opportunities (jobs, internships, "
              "research, fellowships), events or info sessions for FSU students, or career advice for students. Not allowed: ads, product "
              "promotion, discounts, MLM or 'business opportunity' pitches, general company news, or anything unrelated to students' careers. "
              "Decide if the post is allowed. Reason in one sentence addressed to the employer.")
    try:
        return ai.structured(system, ai.tag("post", f"From: {company}\n\n{body}", 3000), "relevance", schema, max_tokens=300)
    except ai.AIUnavailable:
        return None


def can_view(conn, user: dict | None) -> bool:
    if not user:
        return False
    if user["role"] == "student":
        return True
    p = store.employer_profile(conn, user["id"])
    return bool(p and p["status"] == "approved")


def can_post(conn, user: dict) -> tuple[bool, str]:
    if user["role"] == "student":
        if not profiles.student_ready(store.student_profile(conn, user["id"])):
            return False, "Set up your profile (name and major) before posting, so people know who they're talking to."
        return True, ""
    if not store.employer_approved(conn, user["id"]):
        return False, "The feed opens to employers once a reviewer approves your organization."
    return True, ""


# ---------- rendering ----------

def bookmark_icon(filled: bool = False, size: int = 20) -> str:
    return (f'<svg class="ic" viewBox="0 0 24 24" width="{size}" height="{size}" fill="{"currentColor" if filled else "none"}" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4h12v17l-6-4.2L6 21z"/></svg>')


def safe_next(value: str, default: str = "/feed") -> str:
    v = (value or "").strip()
    return v if _SAVE_NEXT.fullmatch(v) else default


def saved_ids(conn, uid: int) -> set[int]:
    return {r[0] for r in conn.execute("SELECT post_id FROM post_saves WHERE user_id = ?", (uid,))}


def _link(link: str) -> str:
    if not link:
        return ""
    return (f'<p class="lnk">{ui.icon("jobs", 14)} <a href="{esc(link)}" target="_blank" rel="noopener noreferrer nofollow ugc">{esc(link[:90])}</a> '
            f'<span class="faint">(opens another site)</span></p>')


KIND_CLASS = {"opportunity": "k-opp", "event": "k-event", "info_session": "k-event", "question": "k-q", "win": "k-win", "advice": "k-adv"}


def post_html(conn, p: dict, user: dict, *, full: bool = False, saved: set[int] | None = None, next_: str = "/feed") -> str:
    """One post on the timeline: initials in the left gutter, name / major / time on one line, a subtle kind tag,
    small text actions and the bookmark at the right."""
    csrf = ui.user_csrf_input()
    if saved is None:
        saved = saved_ids(conn, user["id"])
    is_saved = p["id"] in saved
    kind = KINDS.get(p["kind"], p["kind"])
    mine = p["author_id"] == user["id"]
    helped = conn.execute("SELECT 1 FROM post_helpful WHERE post_id = ? AND user_id = ?", (p["id"], user["id"])).fetchone()
    status = ""
    if p["status"] != "published":
        status = {"pending": '<span class="pill warn">Waiting for review</span>', "held": '<span class="pill warn">Held for review</span>',
                  "rejected": '<span class="pill bad">Not approved</span>'}.get(p["status"], "")
    comments = ""
    if full:
        cs = store.rows(conn, "SELECT * FROM post_comments WHERE post_id = ? AND (status = 'published' OR author_id = ?) ORDER BY id LIMIT 200",
                        (p["id"], user["id"]))
        items = "".join(f'<div class="comment"><b>{esc(web.display_name(conn, c["author_id"])[0])}</b> <span class="faint small">{esc(web.ago(c["created_at"]))}</span>'
                        f'{" <span class=pill>held for review</span>" if c["status"] != "published" else ""}<div style="white-space:pre-wrap">{esc(c["body"])}</div></div>' for c in cs)
        ok, _ = can_post(conn, user)
        form = (f'<form method="post" action="/feed/{int(p["id"])}/comment" style="margin-top:10px">{csrf}<label for="cm" class="hp">Comment</label>'
                f'<textarea id="cm" name="body" required maxlength="{MAX_COMMENT}" style="min-height:60px" placeholder="Add a comment"></textarea>'
                '<button class="b sm" type="submit" style="margin-top:6px">Comment</button></form>') if ok and p["status"] == "published" else ""
        empty = '<p class="faint small">No comments yet.</p>'
        comments = f'<div class="comments">{items or empty}{form}</div>'
    acts = ""
    if p["status"] == "published":
        acts = (f'<form method="post" action="/feed/{int(p["id"])}/helpful">{csrf}<button type="submit"{" class=on" if helped else ""} aria-pressed="{"true" if helped else "false"}">'
                f'Helpful · {int(p["helpful_count"])}</button></form>'
                f'<a href="/feed/{int(p["id"])}">Comments · {int(p["comment_count"])}</a>')
        if not mine:
            acts += f'<form method="post" action="/feed/{int(p["id"])}/report">{csrf}<button type="submit">Report</button></form>'
            if user["role"] == "student" and _role(conn, p["author_id"]) == "employer" and store.employer_approved(conn, p["author_id"]):
                acts += f'<a href="/messages/new?to={int(p["author_id"])}">Message</a>'
    if mine:
        acts += f'<form method="post" action="/feed/{int(p["id"])}/delete">{csrf}<button type="submit">Delete</button></form>'
    flag = ""
    if p["scan_band"] in ("review", "caution") and p["status"] == "published":
        flag = ('<div class="scanbox fd-flag">Heads up: our scanner found something worth checking in this post. '
                'Verify before sharing personal details.</div>')
    save = ""
    if p["status"] == "published":
        action, label = ("unsave", "Remove from saved posts") if is_saved else ("save", "Save post")
        save = (f'<form method="post" action="/feed/{int(p["id"])}/{action}" class="fd-save">{csrf}<input type="hidden" name="next" value="{esc(next_)}">'
                f'<button type="submit" aria-label="{label}" title="{label}" aria-pressed="{"true" if is_saved else "false"}">{bookmark_icon(is_saved, 18)}</button></form>')
    name, sub, who = web.display_name(conn, p["author_id"])
    href = f"/company/{int(p['author_id'])}" if who == "emp" else f"/u/{int(p['author_id'])}"
    emp = " emp" if who == "emp" else ""
    badge = '<span class="fd-emp">Employer</span>' if who == "emp" else ""
    return f"""<article class="fd-post" id="post-{int(p["id"])}"><div class="fd-gut"><a class="avatar{emp}" href="{esc(href)}" aria-hidden="true" tabindex="-1">{ui.initials(name)}</a></div>
<div class="fd-body"><div class="fd-line"><span class="fd-who"><a class="fd-nm" href="{esc(href)}">{esc(name)}</a>{badge}<span class="fd-sub">{esc(sub)}</span><span class="fd-time">· {esc(web.ago(p["created_at"]))}</span></span>
<span class="fd-kind {KIND_CLASS.get(p["kind"], "")}">{esc(kind)}</span>{status}{save}</div>{flag}<div class="fd-text">{esc(p["body"])}</div>{_link(p["link"])}
<div class="fd-acts">{acts}</div>{comments}</div></article>"""


def _role(conn, uid: int) -> str:
    r = conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
    return r[0] if r else ""


def _composer(conn, user: dict, values: dict | None = None, error: str = "") -> str:
    """The "Write a post" button: a <details> whose summary sits in the header row and whose form opens below it."""
    ok, why = can_post(conn, user)
    if not ok:
        return ui.banner("info", why)
    v = values or {}
    kinds = STUDENT_KINDS if user["role"] == "student" else EMPLOYER_KINDS
    opts = "".join(f'<option value="{k}"{" selected" if v.get("kind") == k else ""}>{KINDS[k]}</option>' for k in kinds)
    rule = ("Share a question, advice, a win, or an opportunity with other Noles."
            if user["role"] == "student" else
            "Employer posts must be opportunities, events or advice for FSU students. Ads and promotions are declined. A reviewer approves each post.")
    err = ui.banner("warning", error) if error else ""
    name = web.display_name(conn, user["id"])[0]
    av = f'<span class="avatar{" emp" if user["role"] == "employer" else ""}" aria-hidden="true">{ui.initials(name)}</span>'
    form = f"""<form method="post" action="/feed/post" class="fd-form">{ui.user_csrf_input()}{err}<div class="fd-form-top">{av}
<label for="f-body" class="hp">Post</label><textarea id="f-body" name="body" required maxlength="{MAX_POST}" data-count placeholder="{esc(rule)}">{esc(v.get('body', ''))}</textarea></div>
<div class="row fd-form-row"><label for="f-kind" class="hp">Type</label><select id="f-kind" name="kind">{opts}</select>
<label for="f-link" class="hp">Link</label><input id="f-link" name="link" maxlength="300" placeholder="Link (optional)" value="{esc(v.get('link', ''))}">
<button class="b" type="submit">Post</button></div>{f'<p class="small faint" style="margin-top:6px">{esc(rule)}</p>' if user["role"] == "employer" else ""}</form>"""
    return (f'<details class="fd-comp"{" open" if (error or v.get("body")) else ""}><summary class="b sm fd-write">'
            f'<span class="fd-w-o">{ui.icon("plus", 15)} Write a post</span><span class="fd-w-c">Close</span></summary>{form}</details>')


def _bar(show_menu: str, composer: str, extra: str = "") -> str:
    """The slim header row: title, the Showing menu, and the Write a post button (the composer's summary)."""
    return f'<div class="fd-top"><div class="fd-bar"><h1>Feed</h1></div>{show_menu}{composer}{extra}</div>'


def _teaser() -> HTMLResponse:
    body = (ui.page_head("The FSU feed", "Questions, advice and opportunities from verified FSU students and employers our reviewers approved.", num="Community") +
            '<div class="bento"><div class="tile w3"><h3>Students</h3><p>Sign in with your @fsu.edu account to read and post.</p>'
            '<div class="foot"><a class="b" href="/login/student?next=/feed">Student log in</a></div></div>'
            '<div class="tile w3"><h3>Employers</h3><p>Approved employers can share internships, info sessions and advice for FSU students.</p>'
            '<div class="foot"><a class="b sec" href="/login/employer">Employer log in</a></div></div></div>')
    return web.page(body, "FSU feed", active="/feed")


# ---------- routes ----------

# ---------- feed queries ----------

_VISIBLE = "(p.status = 'published' OR (p.author_id = ? AND p.status IN ('pending','held','rejected')))"
_WORD = re.compile(r"#?[A-Za-z][A-Za-z+#.-]{3,24}")


def _viewer_profile(conn, user: dict) -> dict:
    return (store.student_profile(conn, user["id"]) or {}) if user["role"] == "student" else {}


def _filter_sql(conn, user: dict, f: str, q: str) -> tuple[str, list]:
    """Extra WHERE clauses for the pills and the topic search."""
    sql, params = "", []
    if f == "employers":
        sql += " AND p.author_id IN (SELECT id FROM users WHERE role = 'employer')"
    elif f == "major":
        major = (_viewer_profile(conn, user).get("major") or "").strip()
        sql += " AND p.author_id IN (SELECT user_id FROM student_profiles WHERE LOWER(major) = LOWER(?) AND ? != '')"
        params += [major, major]
    if q:
        sql += " AND LOWER(p.body) LIKE ? ESCAPE '\\'"
        params.append("%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return sql, params


def _mentions(text: str, terms) -> int:
    t = text.lower()
    return sum(1 for w in terms if w and re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", t))


def for_you_score(post: dict, viewer: dict, author: dict | None, now: float | None = None) -> float:
    """Ranks a post for one student: the author's major (+4) and skills (up to +3) that overlap with theirs, their skills
    or major named in the post (up to +3 and +2), and recency (up to +4, halving every 3 days)."""
    now = now or time.time()
    pts = 0.0
    vmajor = (viewer.get("major") or "").strip().lower()
    vskills = [s for s in viewer.get("skills") or [] if s]
    if author and vmajor and (author.get("major") or "").strip().lower() == vmajor:
        pts += 4
    if author:
        theirs = {s.lower() for s in author.get("skills") or []}
        pts += min(3, len(theirs & {s.lower() for s in vskills}))
    pts += min(3, _mentions(post["body"], vskills))
    if vmajor and vmajor in post["body"].lower():
        pts += 2
    age_days = max(0.0, now - post["created_at"]) / 86400
    return pts + 4 * math.pow(0.5, age_days / 3)


def trending(conn, limit: int = 5) -> list[tuple[str, int]]:
    """Words and #tags that show up in at least two recent published posts."""
    since = time.time() - 30 * 86400
    seen: Counter = Counter()
    for (body,) in conn.execute("SELECT body FROM posts WHERE status = 'published' AND created_at > ? ORDER BY id DESC LIMIT 300", (since,)):
        seen.update({w.lower().lstrip("#") for w in _WORD.findall(body) if w.lower().lstrip("#") not in _STOP})
    return [(w, n) for w, n in seen.most_common(40) if n >= 2][:limit]


def _url(tab: str = "feed", f: str = "all", q: str = "", before: int = 0) -> str:
    parts = []
    if tab != "feed":
        parts.append("tab=" + tab)
    if f != "all":
        parts.append("f=" + f)
    if q:
        parts.append("q=" + quote(q))
    if before:
        parts.append(f"before={int(before)}")
    return "/feed" + ("?" + "&".join(parts) if parts else "")


def _mini(conn, uid: int, kind: str, action: str = "") -> str:
    """A compact person/company row for the circle column: initials, name, one line of detail, an optional button."""
    name, sub, k = web.display_name(conn, uid, kind)
    href = f"/company/{int(uid)}" if k == "emp" else f"/u/{int(uid)}"
    return (f'<div class="fd-row"><a class="fd-mini" href="{esc(href)}"><span class="avatar{" emp" if k == "emp" else ""}" aria-hidden="true">{ui.initials(name)}</span>'
            f'<span class="fd-mini-t"><b>{esc(name)}</b><small>{esc(sub)}</small></span></a>{action}</div>')


def _sec(title: str, inner: str, count: str = "", more: str = "") -> str:
    c = f' <span class="fd-count">{esc(count)}</span>' if count else ""
    return f'<section class="fd-sec"><h3>{esc(title)}{c}</h3>{inner}{more}</section>'


def _approved_employers(conn, exclude: list[int], limit: int) -> list[int]:
    ex = list(exclude) or [0]
    return [r[0] for r in conn.execute(
        f"SELECT user_id FROM employer_profiles WHERE status = 'approved' AND user_id NOT IN ({','.join('?' * len(ex))}) "
        "ORDER BY updated_at DESC LIMIT ?", (*ex, limit))]


def _circle(conn, user: dict, next_: str) -> str:
    """The right column, "Your circle". Students: connections, classmates in their major, companies they follow and
    suggested ones. Employers: who is engaging with their posts and which companies are active. Then topics and rules."""
    secs = ""
    if user["role"] == "student":
        me = user["id"]
        cids = [i for i in network.connection_ids(conn, me) if (store.student_profile(conn, i) or {}).get("display_name")]
        rows = "".join(_mini(conn, i, "student") for i in cids[:5])
        secs += _sec("Your connections", rows or '<p class="fd-quiet">No connections yet. Classmates below are a good start.</p>',
                     str(len(cids)) if cids else "",
                     f'<a class="fd-more" href="/network">{"See all on Network" if len(cids) > 5 else "Open Network"} →</a>')
        major = (_viewer_profile(conn, user).get("major") or "").strip()
        sugg = network.suggestions(conn, me, 12)
        same = [s for s in sugg if major and "Same major" in s[1]]
        pick = (same + [s for s in sugg if s not in same])[:3]
        if pick:
            rows = "".join(_mini(conn, int(p["user_id"]), "student", network.connect_button(int(p["user_id"]), "none", next_)) for p, _ in pick)
            secs += _sec(f"In {major}" if same else "People you may know", rows, "",
                         '<a class="fd-more" href="/network?tab=discover">More classmates →</a>')
        followed = [e for e in network.followed_ids(conn, me) if store.employer_approved(conn, e)]
        rows = "".join(_mini(conn, e, "employer") for e in followed[:4])
        rows = (f'<p class="fd-sub-h">Following</p>{rows}' if rows else "")
        sug = _approved_employers(conn, followed, 2)
        if sug:
            rows += '<p class="fd-sub-h">Suggested</p>' + "".join(_mini(conn, e, "employer", network.follow_button(e, False, next_)) for e in sug)
        if rows:
            secs += _sec("Companies", rows, str(len(followed)) if followed else "",
                         '<a class="fd-more" href="/network?tab=following">Companies you follow →</a>')
    else:
        me = user["id"]
        stats = conn.execute(
            "SELECT (SELECT COUNT(*) FROM posts WHERE author_id = ? AND status = 'published'),"
            " (SELECT COUNT(DISTINCT t.uid) FROM (SELECT h.user_id AS uid FROM post_helpful h JOIN posts p ON p.id = h.post_id WHERE p.author_id = ?"
            "   UNION SELECT c.author_id FROM post_comments c JOIN posts p ON p.id = c.post_id WHERE p.author_id = ? AND c.status = 'published') t"
            "   JOIN users u ON u.id = t.uid WHERE u.role = 'student'),"
            " (SELECT COUNT(DISTINCT author_id) FROM posts p JOIN users u ON u.id = p.author_id WHERE u.role = 'student' AND p.status = 'published' AND p.created_at > ?)",
            (me, me, me, time.time() - 7 * 86400)).fetchone()
        nums = (f'<div class="fd-stats"><div><b>{network.follower_count(conn, me)}</b><small>followers</small></div>'
                f'<div><b>{int(stats[0])}</b><small>posts live</small></div><div><b>{int(stats[1])}</b><small>students engaged</small></div></div>'
                f'<p class="fd-quiet">{web.plural(int(stats[2]), "student")} posted on the feed this week.</p>')
        secs += _sec("Your reach", nums)
        active = [r[0] for r in conn.execute(
            "SELECT p.author_id FROM posts p JOIN employer_profiles e ON e.user_id = p.author_id WHERE e.status = 'approved' AND p.status = 'published' "
            "AND p.author_id != ? GROUP BY p.author_id ORDER BY MAX(p.id) DESC LIMIT 4", (me,))]
        if active:
            secs += _sec("Employers posting", "".join(_mini(conn, e, "employer") for e in active))
    topics = trending(conn)
    if topics:
        chips = "".join(f'<a href="{esc(_url(q=w))}">#{esc(w)}<small>{n}</small></a>' for w, n in topics)
        secs += _sec("Trending topics",f'<div class="fd-topics">{chips}</div>')
    rules = "".join(f"<li>{esc(g)}</li>" for g in (GUIDELINES if user["role"] == "student" else EMPLOYER_GUIDELINES))
    secs += _sec("Community guidelines", f'<ul class="fd-rules">{rules}</ul>')
    return f'<aside class="fd-rail" aria-labelledby="fd-circle-h"><h2 id="fd-circle-h" class="fd-rail-h">Your circle</h2>{secs}</aside>'


def _show_key(tab: str, f: str) -> str:
    if tab in ("saved", "foryou"):
        return tab
    return f if f in ("major", "employers") else "everyone"


def _show_menu(user: dict, cur: str, q: str) -> str:
    """The feed's views as a visible tab strip: Everyone, For you, My major, Employers, Saved."""
    items = ""
    for key, lab, hint, tab, f in SHOWS:
        if user["role"] != "student" and key in ("foryou", "major"):
            continue
        href = _url(tab, f, "" if key == "saved" else q)
        cur_attr = ' aria-current="true"' if key == cur else ""
        icon = ui.icon("bookmark", 14) if key == "saved" and "bookmark" in ui._ICON_PATHS else ""
        items += f'<a href="{esc(href)}"{cur_attr} title="{esc(hint)}">{icon}{esc(lab)}</a>'
    return f'<nav class="fd-views" aria-label="Show posts from">{items}</nav>'


# ---------- routes ----------

@router.get("/feed", response_class=HTMLResponse)
def feed(request: Request, tab: str = "feed", f: str = "all", q: str = "", before: int = 0):
    user = web.current_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "feed")
    if not user:
        return _teaser()
    tab = tab if tab in ("feed", "foryou", "saved") else "feed"
    f = f if f in dict(PILLS) and not (f == "major" and user["role"] != "student") else "all"
    q = q.strip()[:40]
    q = q if re.fullmatch(r"[A-Za-z0-9+#. -]{1,40}", q) else ""
    with store.db() as conn:
        if not can_view(conn, user):
            body = ui.page_head("The FSU feed", num="Community") + ui.banner(
                "info", "The feed opens to employers once a reviewer approves your organization.") + '<a class="b" href="/profile">Company profile</a>'
            return web.page(body, "FSU feed", active="/feed")
        saved = saved_ids(conn, user["id"])
        here = _url(tab, f, q)
        nxt = ""
        note = ""
        if tab == "saved":
            posts = store.rows(conn, "SELECT p.* FROM posts p JOIN post_saves s ON s.post_id = p.id WHERE s.user_id = ? AND p.status = 'published' "
                                     "ORDER BY s.created_at DESC, p.id DESC LIMIT 100", (user["id"],))
            here = "/feed?tab=saved"
            empty = ('<div class="fd-empty">' + bookmark_icon(False, 44) + '<h2>No saved posts yet</h2>'
                     '<p>Tap the bookmark on any post to save it here for later.</p>'
                     f'<a class="b sec" href="/feed">Browse the feed</a></div>')
        else:
            fsql, fparams = _filter_sql(conn, user, f, q)
            base = f"SELECT p.* FROM posts p WHERE {_VISIBLE}{fsql}"
            if tab == "foryou":
                cand = store.rows(conn, base + " ORDER BY p.id DESC LIMIT 150", [user["id"]] + fparams)
                viewer = _viewer_profile(conn, user)
                authors: dict = {}
                now = time.time()
                for p in cand:
                    if p["author_id"] not in authors:
                        authors[p["author_id"]] = store.student_profile(conn, p["author_id"])
                cand.sort(key=lambda p: (for_you_score(p, viewer, authors[p["author_id"]], now), p["id"]), reverse=True)
                posts = cand[:30]
                note = ('<p class="fd-note">Ranked by how much each post overlaps with your major and skills, then by how recent it is.'
                        + ("" if viewer.get("major") else " Add your major and skills to your profile to sharpen it.") + "</p>") if user["role"] == "student" else \
                       '<p class="fd-note">Newest first. Students see posts ranked by their major and skills.</p>'
            else:
                params = [user["id"]] + fparams
                sql = base
                if before > 0:
                    sql += " AND p.id < ?"
                    params.append(before)
                posts = store.rows(conn, sql + f" ORDER BY p.id DESC LIMIT {PAGE + 1}", params)
                if len(posts) > PAGE:
                    posts = posts[:PAGE]
                    nxt = f'<p style="text-align:center"><a class="b sec" href="{esc(_url(tab, f, q, posts[-1]["id"]))}">Older posts</a></p>'
            if f == "major" and user["role"] == "student" and not (_viewer_profile(conn, user).get("major") or "").strip():
                empty = '<div class="fd-empty"><h2>Add your major</h2><p>Add your major to your profile and posts from students in it will show up here.</p><a class="b sec" href="/profile/setup">Update profile</a></div>'
            elif f == "major":
                empty = '<div class="fd-empty"><h2>No posts from your major yet</h2><p>When students in your major share something, it will show up here.</p></div>'
            elif f == "employers":
                empty = '<div class="fd-empty"><h2>No employer posts yet</h2><p>Approved employers share opportunities and advice for FSU students here.</p></div>'
            else:
                empty = '<div class="fd-empty"><h2>Nothing here yet</h2><p>Start the conversation.</p></div>'
        items = events.feed_mix(conn, user, tab if (f == "all" and not q and not before) else "", posts,
                                lambda p: post_html(conn, p, user, saved=saved, next_=here))
        topic = (f'<p class="fd-topic">Topic: {esc(q)} <a href="{esc(_url(tab, f))}" aria-label="Clear topic">✕ Clear</a></p>'
                 if q and tab != "saved" else "")
        top = _bar(_show_menu(user, _show_key(tab, f), q), _composer(conn, user), topic + note)
        rail = _circle(conn, user, "/feed")
    main = f'<div class="fd-main">{top}<div class="fd-list">{items or empty}</div>{nxt}</div>'
    body = f'<div class="fd"><div class="fd-grid">{main}{rail}</div></div>'
    return web.page(body, "FSU feed", active="/feed", js=True)


@router.get("/feed/{pid}", response_class=HTMLResponse)
def one_post(pid: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        p = store.row(conn, "SELECT * FROM posts WHERE id = ?", (pid,))
        if not can_view(conn, user) or not p or (p["status"] != "published" and p["author_id"] != user["id"]):
            return web.page('<p class="empty" style="margin:40px 0">That post isn\'t available.</p>', "Post", active="/feed", status=404)
        body = ('<div class="fd fd-one"><a class="back" href="/feed">← Feed</a><div class="fd-list">'
                + post_html(conn, p, user, full=True, next_=f"/feed/{int(pid)}") + "</div></div>")
    return web.page(body, "Post", active="/feed", js=True)


@router.post("/feed/post", response_class=HTMLResponse)
def create(request: Request, body: str = Form(""), kind: str = Form(""), link: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request)
    security.enforce_key_limit(security.post_limiter, f"u{user['id']}", "posting")
    values = {"body": body[:MAX_POST], "kind": kind, "link": link[:300]}

    def again(msg: str, status: int = 400):
        with store.db() as conn:
            page = '<div class="fd">' + _bar("", _composer(conn, user, values, msg)) + "</div>"
        return web.page(page, "FSU feed", active="/feed", js=True, status=status)

    if not web.csrf_ok(request, csrf):
        return again("That page had been open too long. Your post is still here; press Post again.")
    text = security._CONTROL_CHARS_RE.sub("", body or "").strip()
    if len(text) < 10:
        return again("Write a little more (at least 10 characters).")
    if len(text) > MAX_POST:
        return again(f"Posts can be up to {MAX_POST:,} characters.")
    link = link.strip()
    if link:
        if not link.lower().startswith(("http://", "https://")):
            link = "https://" + link
        if len(link) > 300 or not re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?$", link):
            return again("That link doesn't look like a web address.")
    with store.db() as conn:
        ok, why = can_post(conn, user)
        if not ok:
            return again(why, 403)
        allowed = STUDENT_KINDS if user["role"] == "student" else EMPLOYER_KINDS
        if kind not in allowed:
            return again("Pick a post type.")
        scan = msgcheck.check(text + ("\n" + link if link else ""))
        rel = {}
        if user["role"] == "employer":
            rel = relevance(text, kind, link)
            if not rel["ok"]:
                return again("This can't go on the FSU feed yet. " + " ".join(rel["problems"]))
            if ai.enabled() and store.ai_take(conn, user["id"], ai.daily_limit()):
                company = (store.employer_profile(conn, user["id"]) or {}).get("company", "")
                o = ai_relevance(text, company)
                if o is not None:
                    rel["ai"] = o
                    if o.get("relevant") is False:
                        return again("This can't go on the FSU feed: " + str(o.get("reason", ""))[:300])
            status = "pending"
        else:
            status = "held" if scan["band"] in ("review", "block") else "published"
        findings = [{"title": f["title"], "severity": f["severity"]} for f in scan["findings"][:5]]
        conn.execute("INSERT INTO posts (author_id, kind, body, link, status, scan_band, scan_json, relevance_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (user["id"], kind, text, link, status, scan["band"], json.dumps(findings), json.dumps(rel), time.time()))
    return RedirectResponse("/feed", status_code=303)


def _post_action(request: Request, pid: int, csrf: str, fn):
    user = web.require_user(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/feed", status_code=303)
    with store.db() as conn:
        p = store.row(conn, "SELECT * FROM posts WHERE id = ?", (pid,))
        if p and can_view(conn, user):
            out = fn(conn, p, user)
            if out is not None:
                return out
    back = request.headers.get("referer", "")
    return RedirectResponse(f"/feed/{pid}" if back.endswith(f"/feed/{pid}") else "/feed", status_code=303)


@router.post("/feed/{pid}/helpful")
def helpful(pid: int, request: Request, csrf: str = Form("")):
    def fn(conn, p, user):
        if p["status"] != "published":
            return None
        cur = conn.execute("INSERT OR IGNORE INTO post_helpful (post_id, user_id) VALUES (?,?)", (pid, user["id"]))
        if cur.rowcount == 0:
            conn.execute("DELETE FROM post_helpful WHERE post_id = ? AND user_id = ?", (pid, user["id"]))
        conn.execute("UPDATE posts SET helpful_count = (SELECT COUNT(*) FROM post_helpful WHERE post_id = ?) WHERE id = ?", (pid, pid))
    return _post_action(request, pid, csrf, fn)


@router.post("/feed/{pid}/save")
def save(pid: int, request: Request, csrf: str = Form(""), next: str = Form("")):
    def fn(conn, p, user):
        if p["status"] == "published":
            have = conn.execute("SELECT COUNT(*) FROM post_saves WHERE user_id = ?", (user["id"],)).fetchone()[0]
            if have < MAX_SAVES:
                conn.execute("INSERT OR IGNORE INTO post_saves (user_id, post_id, created_at) VALUES (?,?,?)", (user["id"], pid, time.time()))
        return RedirectResponse(safe_next(next), status_code=303)
    return _post_action(request, pid, csrf, fn)


@router.post("/feed/{pid}/unsave")
def unsave(pid: int, request: Request, csrf: str = Form(""), next: str = Form("")):
    def fn(conn, p, user):
        conn.execute("DELETE FROM post_saves WHERE user_id = ? AND post_id = ?", (user["id"], pid))
        return RedirectResponse(safe_next(next), status_code=303)
    return _post_action(request, pid, csrf, fn)


@router.post("/feed/{pid}/comment", response_class=HTMLResponse)
def comment(pid: int, request: Request, body: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request)
    security.enforce_key_limit(security.comment_limiter, f"u{user['id']}", "commenting")

    def fn(conn, p, user):
        ok, _ = can_post(conn, user)
        text = security._CONTROL_CHARS_RE.sub("", body or "").strip()
        if not ok or p["status"] != "published" or not (1 <= len(text) <= MAX_COMMENT):
            return RedirectResponse(f"/feed/{pid}", status_code=303)
        scan = msgcheck.check(text)
        status = "held" if scan["band"] in ("review", "block") else "published"
        conn.execute("INSERT INTO post_comments (post_id, author_id, body, status, scan_band, created_at) VALUES (?,?,?,?,?,?)",
                     (pid, user["id"], text, status, scan["band"], time.time()))
        conn.execute("UPDATE posts SET comment_count = (SELECT COUNT(*) FROM post_comments WHERE post_id = ? AND status = 'published') WHERE id = ?", (pid, pid))
        return RedirectResponse(f"/feed/{pid}", status_code=303)
    return _post_action(request, pid, csrf, fn)


@router.post("/feed/{pid}/report", response_class=HTMLResponse)
def report(pid: int, request: Request, csrf: str = Form("")):
    def fn(conn, p, user):
        if p["author_id"] == user["id"]:
            return None
        conn.execute("INSERT OR IGNORE INTO reports (reporter_id, target_type, target_id, reason, created_at) VALUES (?,?,?,?,?)",
                     (user["id"], "post", pid, "reported from feed", time.time()))
        n = conn.execute("SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE target_type = 'post' AND target_id = ? AND resolved = 0", (pid,)).fetchone()[0]
        if n >= HIDE_AFTER_REPORTS and p["status"] == "published":
            conn.execute("UPDATE posts SET status = 'held' WHERE id = ?", (pid,))
        return web.page(ui.page_head("Thanks for reporting", "A reviewer will look at the post. Posts reported by several people are hidden until then.") +
                        '<a class="b sec" href="/feed">Back to the feed</a>', "Reported", active="/feed")
    return _post_action(request, pid, csrf, fn)


@router.post("/feed/{pid}/delete")
def delete(pid: int, request: Request, csrf: str = Form("")):
    def fn(conn, p, user):
        if p["author_id"] == user["id"]:
            conn.execute("UPDATE posts SET status = 'removed' WHERE id = ?", (pid,))
        return RedirectResponse("/feed", status_code=303)
    return _post_action(request, pid, csrf, fn)
