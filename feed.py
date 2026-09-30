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
import re
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import ai
import msgcheck
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

def _author(conn, uid: int) -> str:
    name, sub, kind = web.display_name(conn, uid)
    href = f"/company/{uid}" if kind == "emp" else f"/u/{uid}"
    return web.person(name, sub, kind, href)


def _link(link: str) -> str:
    if not link:
        return ""
    return (f'<p class="lnk">{ui.icon("jobs", 14)} <a href="{esc(link)}" target="_blank" rel="noopener noreferrer nofollow ugc">{esc(link[:90])}</a> '
            f'<span class="faint">(opens another site)</span></p>')


def post_html(conn, p: dict, user: dict, *, full: bool = False) -> str:
    csrf = ui.user_csrf_input()
    kind = KINDS.get(p["kind"], p["kind"])
    kcls = {"opportunity": "accent", "event": "gold", "info_session": "gold", "question": "info", "win": "ok"}.get(p["kind"], "")
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
                f'{ui.icon("check", 14) if helped else ""}Helpful · {int(p["helpful_count"])}</button></form>'
                f'<a href="/feed/{int(p["id"])}">Comments · {int(p["comment_count"])}</a>')
        if not mine:
            acts += f'<form method="post" action="/feed/{int(p["id"])}/report">{csrf}<button type="submit">Report</button></form>'
            if user["role"] == "student" and _role(conn, p["author_id"]) == "employer" and store.employer_approved(conn, p["author_id"]):
                acts += f'<a href="/messages/new?to={int(p["author_id"])}">Message</a>'
    if mine:
        acts += f'<form method="post" action="/feed/{int(p["id"])}/delete">{csrf}<button type="submit">Delete</button></form>'
    flag = ""
    if p["scan_band"] in ("review", "caution") and p["status"] == "published":
        flag = ('<div class="scanbox" style="max-width:none;margin-bottom:8px">Heads up: our scanner found something worth checking in this post. '
                'Verify before sharing personal details.</div>')
    return f"""<article class="post"><div class="head">{_author(conn, p["author_id"])}<div class="row" style="gap:6px">{status}<span class="pill {kcls}">{esc(kind)}</span>
<span class="faint small">{esc(web.ago(p["created_at"]))}</span></div></div>{flag}<div class="body">{esc(p["body"])}</div>{_link(p["link"])}
<div class="acts">{acts}</div>{comments}</article>"""


def _role(conn, uid: int) -> str:
    r = conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
    return r[0] if r else ""


def _composer(conn, user: dict, values: dict | None = None, error: str = "") -> str:
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
    return f"""<form method="post" action="/feed/post" class="composer-card">{ui.user_csrf_input()}{err}
<label for="f-body" class="hp">Post</label><textarea id="f-body" name="body" required maxlength="{MAX_POST}" data-count placeholder="{esc(rule)}">{esc(v.get('body', ''))}</textarea>
<div class="row" style="margin-top:8px"><label for="f-kind" class="hp">Type</label><select id="f-kind" name="kind" style="width:auto">{opts}</select>
<label for="f-link" class="hp">Link</label><input id="f-link" name="link" maxlength="300" placeholder="Link (optional)" value="{esc(v.get('link', ''))}" style="flex:1;min-width:180px">
<button class="b" type="submit">Post</button></div>{f'<p class="small faint" style="margin-top:6px">{esc(rule)}</p>' if user["role"] == "employer" else ""}</form>"""


def _teaser() -> HTMLResponse:
    body = (ui.page_head("The FSU feed", "Questions, advice and opportunities from verified FSU students and employers our reviewers approved.", num="Community") +
            '<div class="bento"><div class="tile w3"><h3>Students</h3><p>Sign in with your @fsu.edu account to read and post.</p>'
            '<div class="foot"><a class="b" href="/login/student?next=/feed">Student log in</a></div></div>'
            '<div class="tile w3"><h3>Employers</h3><p>Approved employers can share internships, info sessions and advice for FSU students.</p>'
            '<div class="foot"><a class="b sec" href="/login/employer">Employer log in</a></div></div></div>')
    return web.page(body, "FSU feed", active="/feed")


# ---------- routes ----------

@router.get("/feed", response_class=HTMLResponse)
def feed(request: Request, kind: str = "all", before: int = 0):
    user = web.current_user(request)
    security.enforce_rate_limit(request, security.general_limiter, "feed")
    if not user:
        return _teaser()
    kind = kind if kind in KINDS or kind == "all" else "all"
    with store.db() as conn:
        if not can_view(conn, user):
            body = ui.page_head("The FSU feed", num="Community") + ui.banner(
                "info", "The feed opens to employers once a reviewer approves your organization.") + '<a class="b" href="/profile">Company profile</a>'
            return web.page(body, "FSU feed", active="/feed")
        q = "SELECT * FROM posts WHERE (status = 'published' OR (author_id = ? AND status IN ('pending','held','rejected')))"
        params: list = [user["id"]]
        if kind != "all":
            q += " AND kind = ?"; params.append(kind)
        if before > 0:
            q += " AND id < ?"; params.append(before)
        q += " ORDER BY id DESC LIMIT 21"
        posts = store.rows(conn, q, params)
        more = len(posts) > 20
        posts = posts[:20]
        items = "".join(post_html(conn, p, user) for p in posts)
        composer = _composer(conn, user)
    seg = '<div class="seg" style="margin-bottom:14px">' + "".join(
        f'<a href="/feed{"" if k == "all" else "?kind=" + k}"{" class=on" if k == kind else ""}>{label}</a>'
        for k, label in [("all", "All")] + list(FILTER_LABELS.items())) + "</div>"
    nxt = f'<p style="text-align:center"><a class="b sec" href="/feed?kind={esc(kind)}&before={int(posts[-1]["id"])}">Older posts</a></p>' if more else ""
    body = (ui.page_head("The FSU feed", "Only verified FSU students and approved employers can post here. Employer posts must be opportunities or advice for FSU students.", num="Community")
            + composer + seg + (items or '<div class="empty">Nothing here yet. Start the conversation.</div>') + nxt)
    return web.page(body, "FSU feed", active="/feed", js=True)


@router.get("/feed/{pid}", response_class=HTMLResponse)
def one_post(pid: int, request: Request):
    user = web.require_user(request)
    with store.db() as conn:
        p = store.row(conn, "SELECT * FROM posts WHERE id = ?", (pid,))
        if not can_view(conn, user) or not p or (p["status"] != "published" and p["author_id"] != user["id"]):
            return web.page('<p class="empty" style="margin:40px 0">That post isn\'t available.</p>', "Post", active="/feed", status=404)
        body = '<a class="back" href="/feed">← Feed</a>' + post_html(conn, p, user, full=True)
    return web.page(body, "Post", active="/feed", js=True)


@router.post("/feed/post", response_class=HTMLResponse)
def create(request: Request, body: str = Form(""), kind: str = Form(""), link: str = Form(""), csrf: str = Form("")):
    user = web.require_user(request)
    security.enforce_key_limit(security.post_limiter, f"u{user['id']}", "posting")
    values = {"body": body[:MAX_POST], "kind": kind, "link": link[:300]}

    def again(msg: str, status: int = 400):
        with store.db() as conn:
            page = (ui.page_head("The FSU feed", num="Community") + _composer(conn, user, values, msg))
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
