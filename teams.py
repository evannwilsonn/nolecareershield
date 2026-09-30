"""
Team accounts for employers: one company, several recruiters.

The company ("org") keeps the id it always had: its owner's user id. Every company-scoped row (jobs.employer_id,
conversations.employer_id, candidates, applications, follows, events, templates, interviews, company views) holds
that id, so nothing about the data changed. What's new:

  * org_members (store.SCHEMA): who else acts for the company, with a role and their own name and title.
    store.org_of(user_id) gives the org for any account; app.py resolves it once per request into user["org_id"]
    (and user["org_role"]), and employer code paths use store.org_id(user) for company data.
  * Roles: recruiter (post and manage listings, message, schedule, manage candidates), admin (also the team and the
    company profile), owner (everything, including deleting the company).
  * org_invites: an owner or admin invites someone by email. The address must be on the company's own domain (its
    website's, or the owner's email domain) and never a free-mail one. The email carries a one-time link
    (/team/join?token=...); only a hash of the token is stored, it lasts 7 days, and emails.py redacts it in the
    in-site copy. The invitee signs up or logs in as an employer with that exact address and accepts.
  * An employer that already runs its own company (listings, conversations, events or a team) can't join another.
  * Students writing to a company reach the org, so any member can read and reply; each message keeps the member who
    sent it, and threads show "Pat Lee · Garnet Analytics".
  * Deleting a member's account removes only their membership (their sent messages are blanked, as for anyone).
    The owner can't delete their account while others are on the team: they transfer ownership first. A transfer
    moves the company to the new owner's id (every company-scoped table is re-keyed in one transaction) and the
    old owner stays on as an admin.
"""

from __future__ import annotations

import re
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import accounts
import css_team  # noqa: F401  (appends the team page styles to ui.CSS)
import mailer
import security
import store
import ui
import web
from scam_detector.rules import FREE_MAIL
from ui import esc

router = APIRouter()

ROLES = {"owner": "Owner", "admin": "Admin", "recruiter": "Recruiter"}
ROLE_HELP = {"owner": "Everything, including deleting the company.",
             "admin": "Manages the team and the company profile, plus everything a recruiter does.",
             "recruiter": "Posts and manages listings, messages students, schedules interviews and manages candidates."}
INVITE_DAYS = 7
MAX_PENDING = 25
MAX_MEMBERS = 50
NAME_MAX = 80
RECRUITER_PROFILE_NOTE = "Only your company's owner or an admin can edit the company profile. Ask them on the Team page."
_NAME_OK = re.compile(r"^[^<>@{}\n]{2,80}$")

# Every table (and column) that holds a company's org id. transfer_ownership re-keys all of them.
ORG_COLUMNS = [("jobs", "employer_id"), ("conversations", "employer_id"), ("conversations", "blocked_by"), ("candidates", "employer_id"),
               ("applications", "employer_id"), ("follows", "employer_id"), ("company_views", "employer_id"), ("events", "employer_id"),
               ("interview_proposals", "employer_id"), ("message_templates", "employer_id"), ("template_seeds", "employer_id"),
               ("employer_profiles", "user_id"), ("org_members", "org_id"), ("org_invites", "org_id")]


# ---------- who may do what ----------

def role_of(user: dict) -> str:
    return user.get("org_role") or "owner"


def can_manage(user: dict) -> bool:
    """Owners and admins manage the team and the company profile."""
    return user.get("role") == "employer" and role_of(user) in ("owner", "admin")


def is_owner(user: dict) -> bool:
    return user.get("role") == "employer" and role_of(user) == "owner"


def ensure_owner_row(conn, org: int) -> None:
    """The owner gets a row (role owner, their contact name) the first time the team is used."""
    if conn.execute("SELECT 1 FROM org_members WHERE user_id = ?", (org,)).fetchone():
        return
    p = store.row(conn, "SELECT contact_name, contact_title FROM employer_profiles WHERE user_id = ?", (org,)) or {}
    conn.execute("INSERT INTO org_members (org_id, user_id, role, name, title, invited_by, created_at) VALUES (?,?,?,?,?,?,?)",
                 (org, org, "owner", p.get("contact_name") or "", p.get("contact_title") or "", None, time.time()))


def members(conn, org: int) -> list[dict]:
    """The team, owner first: user_id, email, role, name, title, created_at."""
    out = store.rows(conn, "SELECT m.user_id, m.role, m.name, m.title, m.created_at, u.email FROM org_members m "
                           "JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY m.role = 'owner' DESC, m.created_at", (org,))
    if not any(m["user_id"] == org for m in out):
        u = store.row(conn, "SELECT email, created_at FROM users WHERE id = ?", (org,)) or {"email": "", "created_at": 0}
        card = store.member_card(conn, org)
        out.insert(0, {"user_id": org, "role": "owner", "name": card["name"], "title": card["title"],
                       "created_at": u["created_at"], "email": u["email"]})
    return out


def pending_invites(conn, org: int) -> list[dict]:
    return store.rows(conn, "SELECT id, email, role, expires_at, created_at FROM org_invites WHERE org_id = ? ORDER BY created_at DESC", (org,))


def team_size(conn, org: int) -> int:
    return len(store.org_user_ids(conn, org))


# ---------- the company's email domain ----------

def _domain(email: str) -> str:
    return (email or "").rsplit("@", 1)[-1].lower().strip()


def invite_domain_problem(conn, org: int, email: str) -> str:
    """"" when the address may be invited: on the company website's domain or the owner's own domain, never free mail."""
    import employer_page
    ed = _domain(email)
    if not ed or ed in FREE_MAIL:
        return "Invite people at their work address on your company's domain. Personal email addresses (Gmail, Outlook, Yahoo and similar) can't join a team."
    p = store.employer_profile(conn, org) or {}
    owner = store.row(conn, "SELECT email FROM users WHERE id = ?", (org,)) or {"email": ""}
    od = _domain(owner["email"])
    if employer_page.domain_match(email, p.get("website") or "") == "match" or (od and od not in FREE_MAIL and ed == od):
        return ""
    allowed = sorted({d for d in (od if od not in FREE_MAIL else "", (p.get("website") or "").split("//")[-1].split("/")[0].lower().removeprefix("www.")) if d})
    where = " or ".join("@" + d for d in allowed) if allowed else "your company's domain"
    return f"Team members need an email address on your company's domain ({where}). This keeps impostors off your team."


# ---------- what an account that wants to join already owns ----------

def runs_own_company(conn, uid: int) -> bool:
    """True when this employer account runs a company of its own: listings, conversations, events or teammates."""
    one = lambda sql: conn.execute(sql, (uid,)).fetchone()[0]      # noqa: E731
    return bool(one("SELECT COUNT(*) FROM jobs WHERE employer_id = ?") or one("SELECT COUNT(*) FROM conversations WHERE employer_id = ?")
                or one("SELECT COUNT(*) FROM events WHERE employer_id = ?")
                or one("SELECT COUNT(*) FROM org_members WHERE org_id = ? AND user_id != org_id"))


def _drop_own_shell(conn, uid: int) -> None:
    """A joining account's own empty company (a draft profile, default templates) goes: they act for the team now."""
    for t, col in (("employer_profiles", "user_id"), ("message_templates", "employer_id"), ("template_seeds", "employer_id"),
                   ("follows", "employer_id"), ("company_views", "employer_id"), ("org_invites", "org_id")):
        conn.execute(f"DELETE FROM {t} WHERE {col} = ?", (uid,))


# ---------- changes ----------

def _clean_name(v: str, label: str, required: bool = True) -> tuple[str, str]:
    v = " ".join(security._CONTROL_CHARS_RE.sub("", v or "").split())
    if not v:
        return v, (f"Add your {label}." if required else "")
    if len(v) > NAME_MAX or not _NAME_OK.match(v) or re.search(r"https?:|www\.", v, re.I):
        return v, f"Use plain text for your {label} (no links or email addresses)."
    return v, ""


def create_invite(conn, org: int, email: str, role: str, by: int) -> str:
    """Stores the invite (replacing any earlier one to the same address) and returns the raw one-time token."""
    raw = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute("INSERT INTO org_invites (org_id, email, role, token_hash, invited_by, expires_at, created_at) VALUES (?,?,?,?,?,?,?) "
                 "ON CONFLICT(org_id, email) DO UPDATE SET role = excluded.role, token_hash = excluded.token_hash, "
                 "invited_by = excluded.invited_by, expires_at = excluded.expires_at, created_at = excluded.created_at",
                 (org, email, role, accounts._h(raw), by, now + INVITE_DAYS * 86400, now))
    return raw


def invite_link(raw: str) -> str:
    return f"{security.BASE_URL}/team/join?token={raw}"


def invite_mail(conn, org: int, by: int, email: str, role: str, raw: str) -> tuple[str, str, str]:
    company = (store.employer_profile(conn, org) or {}).get("company") or "a company"
    who = store.member_card(conn, by)["name"] or "Someone"
    subject = f"{who} invited you to join {company} on NoleCareerShield"
    body = (f"{who} invited you to join {company}'s hiring team on NoleCareerShield as {'an' if role == 'admin' else 'a'} {ROLES[role]}.\n\n"
            f"Accept the invite (this link works once and expires in {INVITE_DAYS} days):\n{invite_link(raw)}\n\n"
            f"No employer account yet? Sign up at {security.BASE_URL}/signup/employer with this address ({email}), confirm it, "
            "then open the link again.\n\n"
            "If you weren't expecting this, ignore it: nothing happens unless you accept. We never ask for passwords, "
            "bank details or ID numbers by email.")
    return email, subject, body


def join(conn, user: dict, invite: dict, name: str, title: str) -> None:
    _drop_own_shell(conn, user["id"])
    ensure_owner_row(conn, invite["org_id"])
    conn.execute("INSERT INTO org_members (org_id, user_id, role, name, title, invited_by, created_at) VALUES (?,?,?,?,?,?,?)",
                 (invite["org_id"], user["id"], invite["role"] if invite["role"] in ("admin", "recruiter") else "recruiter",
                  name, title, invite["invited_by"], time.time()))
    conn.execute("DELETE FROM org_invites WHERE id = ?", (invite["id"],))


def remove_member(conn, org: int, uid: int) -> None:
    """The member leaves: their listings stay the company's (the email on them goes), their messages stay in threads."""
    conn.execute("DELETE FROM org_members WHERE org_id = ? AND user_id = ? AND role != 'owner'", (org, uid))
    conn.execute("UPDATE jobs SET show_email = 0, posted_by = ? WHERE employer_id = ? AND posted_by = ?", (org, org, uid))


def transfer_ownership(conn, org: int, new_owner: int) -> None:
    """Moves the company to new_owner's id: every company-scoped row is re-keyed; the old owner stays as an admin."""
    ensure_owner_row(conn, org)
    for t, col in ORG_COLUMNS:
        conn.execute(f"UPDATE {t} SET {col} = ? WHERE {col} = ?", (new_owner, org))
    conn.execute("UPDATE org_members SET role = 'admin' WHERE user_id = ?", (org,))
    conn.execute("UPDATE org_members SET role = 'owner' WHERE user_id = ?", (new_owner,))
    # The new owner's own email is now the company's sign-up email; jobs they didn't post keep their poster.
    conn.execute("UPDATE jobs SET posted_by = ? WHERE employer_id = ? AND posted_by IS NULL", (org, new_owner))


# ---------- account page hooks (profiles.py) ----------

def delete_blocker(conn, user: dict) -> str:
    if user.get("role") != "employer":
        return ""
    if store.org_of(conn, user["id"]) == user["id"] and team_size(conn, user["id"]) > 1:
        return ("You own this company's account and others are on its team. Transfer ownership to someone on the Team page first "
                "(you stay on as an admin and can then delete your account), or remove the other members.")
    return ""


def delete_note(user: dict) -> str:
    if user.get("role") != "employer":
        return ""
    if role_of(user) == "owner":
        return " As the owner, this also deletes your company, its listings and its team."
    return " You leave your company's team; its listings and conversations stay with the company."


def export_data(conn, user: dict) -> dict:
    """Membership for anyone on a team; the whole team and its pending invites for the owner (invite tokens never)."""
    if user.get("role") != "employer":
        return {}
    org = store.org_of(conn, user["id"])
    m = store.row(conn, "SELECT org_id, role, name, title, invited_by, created_at FROM org_members WHERE user_id = ?", (user["id"],))
    out = {"team_membership": dict(m, company=(store.employer_profile(conn, org) or {}).get("company", "")) if m else None}
    if org == user["id"]:
        out["team"] = [{k: x[k] for k in ("user_id", "email", "role", "name", "title", "created_at")} for x in members(conn, org)]
        out["team_invites"] = pending_invites(conn, org)
    return out


# ---------- the company page's Team card (signed-in viewers only; the page itself needs a sign-in) ----------

def team_card(conn, org: int) -> str:
    try:
        team = [m for m in members(conn, org) if m["name"]]
    except Exception:                          # noqa: BLE001 - a database from before team accounts
        return ""
    if len(team) < 2:
        return ""
    rows = "".join(f'<li>{web.person(m["name"], m["title"] or ROLES.get(m["role"], ""), "emp")}</li>' for m in team[:12])
    return (f'<section class="card tm-card"><div class="phead"><h2>Team</h2><span class="small faint">{len(team)}</span></div>'
            f'<ul class="tm-people">{rows}</ul><p class="small faint">The people who post listings and answer messages for this company.</p></section>')


# ---------- pages ----------

DONE = {"invited": "Invite sent. It works for 7 days.", "resent": "Invite sent again with a new link.", "revoked": "Invite revoked.",
        "role": "Role updated.", "removed": "Removed from the team.", "saved": "Your details are saved.",
        "joined": "Welcome to the team. You can post and manage listings, message students and manage candidates for your company.",
        "transferred": "Ownership transferred. You're an admin now."}


def _when(ts: float) -> str:
    return time.strftime("%b %-d", time.localtime(ts))


def _role_select(name: str, fid: str, current: str, owner_ok: bool = False) -> str:
    opts = [("recruiter", "Recruiter"), ("admin", "Admin")]
    return (f'<select id="{fid}" name="{name}">' + "".join(f'<option value="{k}"{" selected" if k == current else ""}>{v}</option>' for k, v in opts)
            + "</select>")


def _page(conn, user: dict, error: str = "", notice: str = "", draft: dict | None = None, status: int = 200) -> HTMLResponse:
    org = store.org_id(user)
    p = store.employer_profile(conn, org) or {}
    team = members(conn, org)
    invites = pending_invites(conn, org)
    manage = can_manage(user)
    csrf = ui.user_csrf_input()
    draft = draft or {}
    me = next((m for m in team if m["user_id"] == user["id"]), {"name": "", "title": ""})
    head = ui.page_head("Team", esc(f"Everyone who hires for {p.get('company') or 'your company'} on NoleCareerShield. "
                                    "Listings, messages, candidates and templates are shared by the whole team."), num="You")
    note = (ui.banner("warning", error) if error else "") + (ui.banner("verified", notice) if notice else "")
    rows = []
    for m in team:
        you = m["user_id"] == user["id"]
        badge = f'<span class="pill {"gold" if m["role"] == "owner" else "ok" if m["role"] == "admin" else ""}">{ROLES.get(m["role"], m["role"])}</span>'
        acts = ""
        if manage and not you and m["role"] != "owner":
            uid = int(m["user_id"])
            acts = (f'<form method="post" action="/team/member/{uid}/role" class="tm-role">{csrf}<label class="sr" for="r{uid}">Role for {esc(m["name"] or m["email"])}</label>'
                    f'{_role_select("role", f"r{uid}", m["role"])}<button class="b sm sec" type="submit">Change</button></form>'
                    f'<form method="post" action="/team/member/{uid}/remove" class="navform">{csrf}<button class="b sm ghost" type="submit">Remove</button></form>')
            if is_owner(user):
                acts += (f'<details class="tm-xfer"><summary class="b sm ghost">Make owner</summary><form method="post" action="/team/transfer">{csrf}'
                         f'<input type="hidden" name="to" value="{uid}"><p class="small">{esc(m["name"] or m["email"])} becomes the owner and you become an admin. '
                         'Only the owner can delete the company.</p><button class="b sm danger" type="submit">Transfer ownership</button></form></details>')
        who = esc(m["name"] or "No name yet") + (' <span class="faint small">(you)</span>' if you else "")
        rows.append(f'<li class="tm-row"><span class="avatar emp" aria-hidden="true">{ui.initials(m["name"] or m["email"])}</span>'
                    f'<div class="tm-who"><b>{who}</b><span>{esc(m["title"] or "")}{" · " if m["title"] else ""}{esc(m["email"])}</span>'
                    f'<span class="faint small">Joined {esc(_when(m["created_at"] or time.time()))}</span></div>'
                    f'<div class="tm-badge">{badge}</div><div class="tm-acts">{acts}</div></li>')
    people = (f'<section class="card tm-list" aria-labelledby="tm-h"><div class="phead"><h2 id="tm-h">Members</h2>'
              f'<span class="small faint">{len(team)}</span></div><ul class="tm-rows">{"".join(rows)}</ul></section>')
    inv = ""
    if manage:
        irows = "".join(
            f'<li class="tm-row"><span class="avatar" aria-hidden="true">{ui.icon("mail", 16)}</span><div class="tm-who"><b>{esc(i["email"])}</b>'
            f'<span>{ROLES.get(i["role"], i["role"])} · sent {esc(_when(i["created_at"]))}</span>'
            f'<span class="small {"bad-t" if i["expires_at"] <= time.time() else "faint"}">{"Expired" if i["expires_at"] <= time.time() else "Expires " + esc(_when(i["expires_at"]))}</span></div>'
            f'<div class="tm-badge"><span class="pill warn">Pending</span></div><div class="tm-acts">'
            f'<form method="post" action="/team/invite/{int(i["id"])}/resend" class="navform">{csrf}<button class="b sm sec" type="submit">Resend</button></form>'
            f'<form method="post" action="/team/invite/{int(i["id"])}/revoke" class="navform">{csrf}<button class="b sm ghost" type="submit">Revoke</button></form></div></li>'
            for i in invites)
        inv = (f'<section class="card tm-list" aria-labelledby="tm-i"><div class="phead"><h2 id="tm-i">Pending invites</h2><span class="small faint">{len(invites)}</span></div>'
               + (f'<ul class="tm-rows">{irows}</ul>' if irows else '<p class="small muted">No pending invites.</p>') + '</section>')
        form = (f'<form class="card tm-invite" method="post" action="/team/invite">{csrf}<h2>Invite a teammate</h2>'
                '<p class="small muted">They need an email address on your company\'s domain. We email them a one-time link; they sign up or log in as an '
                'employer with that address and accept.</p>'
                f'<div class="form-field"><label for="ti-email">Work email</label><input id="ti-email" type="email" name="email" required maxlength="254" '
                f'autocomplete="off" placeholder="name@{esc(_domain(user.get("email", "")) or "company.com")}" value="{esc(draft.get("email", ""))}"></div>'
                f'<div class="form-field"><label for="ti-role">Role</label>{_role_select("role", "ti-role", draft.get("role") or "recruiter")}'
                f'<p class="hint">Recruiter: {esc(ROLE_HELP["recruiter"])} Admin: {esc(ROLE_HELP["admin"])}</p></div>'
                f'<button class="b" type="submit">{ui.icon("send", 15)} Send invite</button></form>')
    else:
        form = (f'<section class="card tm-invite"><h2>Your role: {ROLES.get(role_of(user), "")}</h2><p class="small muted">{esc(ROLE_HELP.get(role_of(user), ""))} '
                'An owner or admin manages the team and the company profile.</p></section>')
    mine = (f'<form class="card tm-me" method="post" action="/team/me">{csrf}<h2>Your details</h2>'
            '<p class="small muted">Shown on listings you post and next to messages you send, e.g. "Pat Lee · Garnet Analytics".</p>'
            f'<div class="form-field"><label for="tm-name">Your name</label><input id="tm-name" name="name" required maxlength="{NAME_MAX}" value="{esc(draft.get("name", me.get("name", "")))}"></div>'
            f'<div class="form-field"><label for="tm-title">Your job title</label><input id="tm-title" name="title" maxlength="{NAME_MAX}" value="{esc(draft.get("title", me.get("title", "")))}"></div>'
            '<button class="b sec" type="submit">Save</button></form>')
    leave = ""
    if not is_owner(user):
        leave = (f'<form method="post" action="/team/leave" class="card tm-leave">{csrf}<h2>Leave the team</h2><p class="small muted">You stop acting for '
                 f'{esc(p.get("company") or "this company")}. Your employer account stays; the company keeps its listings and conversations.</p>'
                 '<button class="b sm danger" type="submit">Leave team</button></form>')
    body = head + note + f'<div class="tm-grid"><div class="tm-main">{people}{inv}</div><aside class="tm-side">{form}{mine}{leave}</aside></div>'
    return web.page(body, "Team", active="/team", status=status)


def _employer(request: Request) -> dict:
    return web.require_user(request, "employer")


@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request, done: str = ""):
    user = _employer(request)
    security.enforce_rate_limit(request, security.general_limiter, "team")
    with store.db() as conn:
        p = store.employer_profile(conn, store.org_id(user)) or {}
        if not p.get("company"):
            return web.page(ui.page_head("Team", num="You") + ui.banner("info", "Set up your company profile first. Then you can invite teammates.")
                            + '<a class="b" href="/profile/setup">Set up company profile</a>', "Team", active="/team")
        return _page(conn, user, notice=DONE.get(done, ""))


def _back(done: str) -> RedirectResponse:
    return RedirectResponse(f"/team?done={done}", status_code=303)


@router.post("/team/invite", response_class=HTMLResponse)
def invite(request: Request, background: BackgroundTasks, email: str = Form(""), role: str = Form("recruiter"), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/team", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"team{user['id']}", "team invites")
    with store.db() as conn:
        if not can_manage(user):
            return _page(conn, user, error="Only an owner or admin can invite teammates.", status=403)
        org = store.org_id(user)
        draft = {"email": email[:254], "role": role}
        try:
            addr = accounts.normalize_email(email)
        except ValueError as e:
            return _page(conn, user, error=str(e), draft=draft, status=400)
        role = role if role in ("admin", "recruiter") else "recruiter"
        problem = invite_domain_problem(conn, org, addr)
        if not problem and any(m["email"].lower() == addr for m in members(conn, org)):
            problem = "That person is already on your team."
        n = conn.execute("SELECT COUNT(*) FROM org_invites WHERE org_id = ? AND email != ?", (org, addr)).fetchone()[0]
        if not problem and n >= MAX_PENDING:
            problem = f"You can have up to {MAX_PENDING} pending invites. Revoke some first."
        if not problem and team_size(conn, org) >= MAX_MEMBERS:
            problem = f"A team can have up to {MAX_MEMBERS} members."
        if problem:
            return _page(conn, user, error=problem, draft=draft, status=400)
        ensure_owner_row(conn, org)
        raw = create_invite(conn, org, addr, role, user["id"])
        background.add_task(mailer.send, *invite_mail(conn, org, user["id"], addr, role, raw))
    return _back("invited")


def _own_invite(conn, user: dict, iid: int) -> dict | None:
    return store.row(conn, "SELECT * FROM org_invites WHERE id = ? AND org_id = ?", (iid, store.org_id(user)))


@router.post("/team/invite/{iid}/resend")
def resend(iid: int, request: Request, background: BackgroundTasks, csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf) or not can_manage(user):
        return RedirectResponse("/team", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"team{user['id']}", "team invites")
    with store.db() as conn:
        inv = _own_invite(conn, user, iid)
        if not inv:
            return RedirectResponse("/team", status_code=303)
        raw = create_invite(conn, inv["org_id"], inv["email"], inv["role"], user["id"])     # a new token; the old link stops working
        background.add_task(mailer.send, *invite_mail(conn, inv["org_id"], user["id"], inv["email"], inv["role"], raw))
    return _back("resent")


@router.post("/team/invite/{iid}/revoke")
def revoke(iid: int, request: Request, csrf: str = Form("")):
    user = _employer(request)
    if web.csrf_ok(request, csrf) and can_manage(user):
        with store.db() as conn:
            conn.execute("DELETE FROM org_invites WHERE id = ? AND org_id = ?", (iid, store.org_id(user)))
        return _back("revoked")
    return RedirectResponse("/team", status_code=303)


def _member(conn, user: dict, uid: int) -> dict | None:
    return store.row(conn, "SELECT * FROM org_members WHERE user_id = ? AND org_id = ?", (uid, store.org_id(user)))


@router.post("/team/member/{uid}/role")
def change_role(uid: int, request: Request, role: str = Form(""), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf) or not can_manage(user) or uid == user["id"] or role not in ("admin", "recruiter"):
        return RedirectResponse("/team", status_code=303)
    with store.db() as conn:
        m = _member(conn, user, uid)
        if not m or m["role"] == "owner":
            return RedirectResponse("/team", status_code=303)
        conn.execute("UPDATE org_members SET role = ? WHERE user_id = ? AND org_id = ?", (role, uid, m["org_id"]))
    return _back("role")


@router.post("/team/member/{uid}/remove")
def remove(uid: int, request: Request, csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf) or not can_manage(user) or uid == user["id"]:
        return RedirectResponse("/team", status_code=303)
    with store.db() as conn:
        m = _member(conn, user, uid)
        if not m or m["role"] == "owner":
            return RedirectResponse("/team", status_code=303)
        remove_member(conn, m["org_id"], uid)
    return _back("removed")


@router.post("/team/leave", response_class=HTMLResponse)
def leave(request: Request, csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf) or is_owner(user):
        return RedirectResponse("/team", status_code=303)
    with store.db() as conn:
        remove_member(conn, store.org_id(user), user["id"])
    return web.page(ui.page_head("You left the team", "Your employer account is still here. To hire again, set up your own company profile or accept a new invite.")
                    + '<a class="b" href="/profile/setup">Set up a company profile</a>', "Left the team", active="/team")


@router.post("/team/transfer")
def transfer(request: Request, to: int = Form(0), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf) or not is_owner(user) or to == user["id"]:
        return RedirectResponse("/team", status_code=303)
    with store.db() as conn:
        m = _member(conn, user, to)
        if not m:
            return RedirectResponse("/team", status_code=303)
        transfer_ownership(conn, store.org_id(user), to)
    return _back("transferred")


@router.post("/team/me", response_class=HTMLResponse)
def save_me(request: Request, name: str = Form(""), title: str = Form(""), csrf: str = Form("")):
    user = _employer(request)
    if not web.csrf_ok(request, csrf):
        return RedirectResponse("/team", status_code=303)
    security.enforce_key_limit(security.profile_limiter, f"u{user['id']}", "profile updates")
    name, e1 = _clean_name(name, "name")
    title, e2 = _clean_name(title, "job title", required=False)
    with store.db() as conn:
        if e1 or e2:
            return _page(conn, user, error=e1 or e2, draft={"name": name, "title": title}, status=400)
        org = store.org_id(user)
        ensure_owner_row(conn, org)
        if not conn.execute("SELECT 1 FROM org_members WHERE user_id = ?", (user["id"],)).fetchone():
            return RedirectResponse("/team", status_code=303)
        conn.execute("UPDATE org_members SET name = ?, title = ? WHERE user_id = ?", (name, title, user["id"]))
    return _back("saved")


# ---------- joining ----------

def _invite_by_token(conn, raw: str) -> dict | None:
    if not raw or len(raw) > 200:
        return None
    return store.row(conn, "SELECT * FROM org_invites WHERE token_hash = ? AND expires_at > ?", (accounts._h(raw), time.time()))


def _join_problem(conn, user: dict, inv: dict | None) -> str:
    if not inv:
        return "That invite has expired, was revoked, or was already used. Ask your company's owner or admin to send a new one."
    if (user.get("email") or "").lower() != inv["email"].lower():
        return (f"This invite is for {inv['email']}. Log in (or sign up) as an employer with that exact address to accept it.")
    if store.org_of(conn, user["id"]) == inv["org_id"]:
        return "You're already on this team."
    if store.org_of(conn, user["id"]) != user["id"]:
        return "You're already on another company's team. Leave that team first (Team page), then accept this invite."
    if runs_own_company(conn, user["id"]):
        return ("This employer account already runs its own company on NoleCareerShield (it has listings, conversations or a team), "
                "so it can't join another company. Use a separate employer account at this address, or ask to be removed from your old company first.")
    return ""


def _join_page(conn, user: dict, inv: dict | None, token: str = "", error: str = "", draft: dict | None = None, status: int = 200) -> HTMLResponse:
    draft = draft or {}
    problem = _join_problem(conn, user, inv)
    if problem:
        return web.page(ui.page_head("Join a team", num="Team") + ui.banner("info", problem) + '<a class="b sec" href="/">Home</a>', "Join a team",
                        active="/team", status=403 if inv else 404)
    p = store.employer_profile(conn, inv["org_id"]) or {}
    by = store.member_card(conn, inv["invited_by"] or inv["org_id"])["name"]
    err = ui.banner("warning", error) if error else ""
    hidden = (f'<input type="hidden" name="token" value="{esc(token)}">' if token else f'<input type="hidden" name="invite" value="{int(inv["id"])}">')
    body = (ui.page_head(f"Join {p.get('company') or 'the team'}", num="Team") + err +
            f'<div class="card tm-join"><div class="row" style="gap:14px;align-items:center"><span class="avatar xl emp" aria-hidden="true">{ui.initials(p.get("company") or "?")}</span>'
            f'<div><h2 style="margin:0">{esc(p.get("company") or "")}</h2><p class="small muted">{esc(by + " invited you" if by else "You were invited")} as '
            f'{"an" if inv["role"] == "admin" else "a"} <b>{ROLES.get(inv["role"], "")}</b>. {esc(ROLE_HELP.get(inv["role"], ""))}</p></div></div>'
            f'<form method="post" action="/team/join" style="margin-top:16px">{ui.user_csrf_input()}{hidden}'
            f'<div class="form-field"><label for="tj-name">Your name</label><input id="tj-name" name="name" required maxlength="{NAME_MAX}" value="{esc(draft.get("name", ""))}" placeholder="Pat Lee"></div>'
            f'<div class="form-field"><label for="tj-title">Your job title</label><input id="tj-title" name="title" maxlength="{NAME_MAX}" value="{esc(draft.get("title", ""))}" placeholder="Campus Recruiter"></div>'
            '<p class="small faint">Students see your name and title on listings you post and next to messages you send.</p>'
            '<button class="b" type="submit">Accept and join</button></form></div>')
    return web.page(body, "Join a team", active="/team", status=status)


@router.get("/team/join", response_class=HTMLResponse)
def join_page(request: Request, token: str = ""):
    user = _employer(request)
    security.enforce_rate_limit(request, security.general_limiter, "team_join")
    with store.db() as conn:
        if token:
            return _join_page(conn, user, _invite_by_token(conn, token), token)
        # No token (e.g. from the "You're in" page after signing up): invites waiting for this verified address.
        invs = store.rows(conn, "SELECT * FROM org_invites WHERE lower(email) = lower(?) AND expires_at > ? ORDER BY created_at DESC",
                          (user["email"], time.time()))
        if len(invs) == 1:
            return _join_page(conn, user, invs[0])
        if not invs:
            return _join_page(conn, user, None)
        items = "".join(f'<li><a class="b sec" href="/team/join?invite={int(i["id"])}">'
                        f'{esc((store.employer_profile(conn, i["org_id"]) or {}).get("company") or "A company")} · {ROLES[i["role"]]}</a></li>' for i in invs)
        pick = int(request.query_params.get("invite") or 0) if (request.query_params.get("invite") or "").isdigit() else 0
        chosen = next((i for i in invs if i["id"] == pick), None)
        if chosen:
            return _join_page(conn, user, chosen)
        return web.page(ui.page_head("Your team invites", num="Team") + f'<ul class="tm-pick">{items}</ul>', "Join a team", active="/team")


@router.post("/team/join", response_class=HTMLResponse)
def join_submit(request: Request, token: str = Form(""), invite: int = Form(0), name: str = Form(""), title: str = Form(""), csrf: str = Form("")):
    user = _employer(request)
    security.enforce_rate_limit(request, security.user_login_limiter, "team_join")
    with store.db() as conn:
        if token:
            inv = _invite_by_token(conn, token)
        else:
            inv = store.row(conn, "SELECT * FROM org_invites WHERE id = ? AND lower(email) = lower(?) AND expires_at > ?",
                            (invite, user["email"], time.time()))
        if not web.csrf_ok(request, csrf):
            return _join_page(conn, user, inv, token, "That page had been open too long. Press Accept again.", {"name": name, "title": title}, 400)
        problem = _join_problem(conn, user, inv)
        if problem:
            return _join_page(conn, user, inv, token)
        name, e1 = _clean_name(name, "name")
        title, e2 = _clean_name(title, "job title", required=False)
        if e1 or e2:
            return _join_page(conn, user, inv, token, e1 or e2, {"name": name, "title": title}, 400)
        join(conn, user, inv, name, title)
    return _back("joined")


def pending_for(conn, email: str) -> int:
    """Invites waiting for this address (for the "You're in" page after an invitee confirms their email)."""
    try:
        return conn.execute("SELECT COUNT(*) FROM org_invites WHERE lower(email) = lower(?) AND expires_at > ?", (email, time.time())).fetchone()[0]
    except Exception:                          # noqa: BLE001
        return 0
