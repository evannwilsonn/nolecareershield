"""Small helpers shared by the feature routers (profiles, messaging, assistant, resume, feed, check)."""

from __future__ import annotations

import time
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

import security
import store
import ui


class LoginRequired(Exception):
    """Raised by a route that needs a signed-in account; app.py turns it into a redirect to the right login page."""

    def __init__(self, role: str = "student", next_: str = ""):
        self.role = role
        self.next = next_


class Forbidden(Exception):
    def __init__(self, message: str = "You don't have access to that."):
        self.message = message


def current_user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def require_user(request: Request, role: str | None = None) -> dict:
    user = current_user(request)
    if not user:
        nxt = request.url.path
        if request.method == "GET" and request.url.query:
            nxt += "?" + request.url.query
        raise LoginRequired(role or "student", nxt)
    if role and user["role"] != role:
        raise Forbidden("That page is for " + ("FSU students." if role == "student" else "employers."))
    return user


def csrf_ok(request: Request, token: str | None) -> bool:
    raw = getattr(request.state, "utoken", None)
    return bool(raw) and security.verify_csrf(token, "user:" + raw)


def page(body: str, title: str, active: str | None = "", *, js: bool = False, status: int = 200) -> HTMLResponse:
    return HTMLResponse(ui.shell(body, title=f"{title} — NoleCareerShield", active=active, js=js), status_code=status)


def login_link(role: str, next_: str) -> str:
    return f"/login/{role}?next={quote(next_, safe='/')}"


def ago(ts: float | None) -> str:
    if not ts:
        return ""
    d = max(0, time.time() - ts)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    if d < 7 * 86400:
        return f"{int(d // 86400)}d ago"
    return time.strftime("%b %-d", time.localtime(ts))


def display_name(conn, user_id: int, role: str | None = None) -> tuple[str, str, str]:
    """(name, subtitle, kind) for showing a person: students by chosen name + major, employers by company."""
    if role is None:
        r = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        role = r[0] if r else "student"
    if role == "employer":
        p = store.employer_profile(conn, user_id) or {}
        name = p.get("company") or "Employer"
        sub = "Approved employer" if p.get("status") == "approved" else "Employer (not yet approved)"
        if p.get("location"):
            sub += " · " + p["location"]
        return name, sub, "emp"
    p = store.student_profile(conn, user_id) or {}
    name = p.get("display_name") or "FSU student"
    bits = [b for b in (p.get("major"), ("Class of " + p["grad_term"].split()[-1]) if p.get("grad_term") else "") if b]
    return name, " · ".join(bits) or "FSU student", "stu"


def person(name: str, sub: str, kind: str, href: str = "") -> str:
    av = f'<span class="avatar{" emp" if kind == "emp" else ""}">{ui.initials(name)}</span>'
    nm = f'<a href="{ui.esc(href)}" style="text-decoration:none">{ui.esc(name)}</a>' if href else ui.esc(name)
    return f'<div class="person">{av}<div style="min-width:0"><div class="nm">{nm}</div><div class="sub">{ui.esc(sub)}</div></div></div>'


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


# ---------- request bodies ----------
# Handlers that parse files, call the AI or run scam checks are plain `def` functions, which FastAPI runs in a
# thread pool. They read the body through these async dependencies first, so slow work never blocks the event loop
# (an async handler doing that work would freeze every other request until it finished).

async def form_data(request: Request):
    return await request.form()


async def body_bytes(request: Request) -> bytes:
    return await request.body()
