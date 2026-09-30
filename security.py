"""
Security and configuration helpers for NoleCareerShield.

Everything environment-dependent lives here so the deployment surface is one
place: ENV, SECRET_KEY, ADMIN_PASSWORD, CONTACT_EMAIL, DB_PATH, TRUST_PROXY,
BASE_URL, the SMTP_* mail settings (see mailer.py) and the optional Turnstile keys.

Rate limiting is an in-memory sliding window. That is correct for a single
process. Behind multiple workers or replicas it no longer sees all traffic and
should move to a shared store (Redis).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


# ---------- configuration ----------

ENV = os.environ.get("ENV", "development").strip().lower()
IS_PROD = ENV == "production"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"
# Absolute address of the site. Links in emails are built from this and never from the
# request's Host header, which an attacker controls.
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
# Optional Cloudflare Turnstile (a bot check on sign-up, log-in and forgot-password).
# Off unless both keys are set. Turning it on loads one Cloudflare script on those pages.
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "").strip()
LISTING_TTL_DAYS = int(os.environ.get("LISTING_TTL_DAYS", "90"))
PURGE_REJECTED_DAYS = int(os.environ.get("PURGE_REJECTED_DAYS", "90"))

_secret = os.environ.get("SECRET_KEY", "")


def validate_config() -> None:
    """Refuse to start in production with unsafe or missing configuration."""
    global _secret
    problems = []
    if IS_PROD:
        if ADMIN_PASSWORD in ("", "changeme") or len(ADMIN_PASSWORD) < 12:
            problems.append("ADMIN_PASSWORD must be set to a strong value (12+ characters)")
        if len(_secret) < 32:
            problems.append("SECRET_KEY must be set (32+ random characters, e.g. `python -c \"import secrets;print(secrets.token_hex(32))\"`)")
        if not CONTACT_EMAIL:
            problems.append("CONTACT_EMAIL must be set (shown on the report/privacy pages)")
        if not BASE_URL.startswith("https://"):
            problems.append("BASE_URL must be the public https:// address of the site (used in email links)")
        if not (os.environ.get("SMTP_HOST", "").strip() and os.environ.get("SMTP_FROM", "").strip()):
            problems.append("SMTP_HOST and SMTP_FROM must be set (confirmation and password-reset emails)")
        if bool(TURNSTILE_SITE_KEY) != bool(TURNSTILE_SECRET):
            problems.append("set both TURNSTILE_SITE_KEY and TURNSTILE_SECRET, or neither")
    if problems:
        raise RuntimeError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
    if not _secret:
        # Development only: random per process, so tokens reset on restart.
        _secret = secrets.token_hex(32)


def secret_key() -> bytes:
    return (_secret or "").encode()


# ---------- rate limiting ----------

class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window_seconds:
                dq.popleft()
            if len(dq) >= self.max_attempts:
                retry_after = int(self.window_seconds - (now - dq[0])) + 1
                return False, max(retry_after, 1)
            return True, 0

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window_seconds:
                dq.popleft()
            dq.append(now)

    def reset_all(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(max_attempts=5, window_seconds=15 * 60)
submit_limiter = RateLimiter(max_attempts=20, window_seconds=60 * 60)
general_limiter = RateLimiter(max_attempts=120, window_seconds=60)
# Accounts. Per address: slows password guessing on one account. Per person: sign-ups.
# Email limiter: caps how many messages one address can be sent, so the forms cannot be used to spam someone.
user_login_limiter = RateLimiter(max_attempts=10, window_seconds=15 * 60)
user_login_email_limiter = RateLimiter(max_attempts=8, window_seconds=15 * 60)
signup_limiter = RateLimiter(max_attempts=10, window_seconds=60 * 60)
email_limiter = RateLimiter(max_attempts=3, window_seconds=60 * 60)
# Network features. Keyed per account (not per IP) where an account exists.
message_limiter = RateLimiter(max_attempts=60, window_seconds=60 * 60)       # messages sent per hour
new_convo_limiter = RateLimiter(max_attempts=25, window_seconds=24 * 3600)   # new conversations started per day
check_limiter = RateLimiter(max_attempts=40, window_seconds=60 * 60)         # scam checks per hour
ai_limiter = RateLimiter(max_attempts=30, window_seconds=10 * 60)            # AI requests per 10 minutes (burst cap)
post_limiter = RateLimiter(max_attempts=10, window_seconds=60 * 60)          # feed posts per hour
comment_limiter = RateLimiter(max_attempts=40, window_seconds=60 * 60)       # comments per hour
upload_limiter = RateLimiter(max_attempts=20, window_seconds=60 * 60)        # resume uploads per hour
profile_limiter = RateLimiter(max_attempts=60, window_seconds=60 * 60)       # profile saves per hour
public_check_limiter = RateLimiter(max_attempts=10, window_seconds=24 * 3600)  # scam checks per day for visitors who aren't signed in
school_limiter = RateLimiter(max_attempts=5, window_seconds=24 * 3600)       # "bring it to my school" requests per day
ALL_LIMITERS = (login_limiter, submit_limiter, general_limiter, user_login_limiter,
                user_login_email_limiter, signup_limiter, email_limiter, message_limiter, new_convo_limiter,
                check_limiter, ai_limiter, post_limiter, comment_limiter, upload_limiter, profile_limiter,
                public_check_limiter, school_limiter)


def client_ip(request: Request) -> str:
    """
    Direct peer address by default. X-Forwarded-For is honored only when
    TRUST_PROXY=1 (i.e. you are behind exactly one proxy that appends the real
    client address). We take the LAST entry: anything to its left was supplied
    by the client and can be forged.
    """
    ip = request.client.host if request.client else "unknown"
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            ip = parts[-1]
    return ip


def enforce_rate_limit(request: Request, limiter: RateLimiter, bucket: str) -> None:
    key = f"{bucket}:{client_ip(request)}"
    allowed, retry_after = limiter.check(key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    limiter.hit(key)


def enforce_key_limit(limiter: RateLimiter, key: str, what: str = "that") -> None:
    """Rate limit keyed on something other than the IP, such as an account id."""
    allowed, retry_after = limiter.check(key)
    if not allowed:
        mins = max(1, round(retry_after / 60))
        raise HTTPException(
            status_code=429,
            detail=f"You've done {what} a lot in a short time. Try again in about {mins} minute{'s' if mins != 1 else ''}.",
            headers={"Retry-After": str(retry_after)},
        )
    limiter.hit(key)


# ---------- CSRF tokens ----------
# Stateless, HMAC-signed, time-limited. Admin actions bind the token to the
# admin session so a token from one session is useless in another. Public forms
# use scope "form": they exist to stop blind cross-site auto-posts and bots that
# never loaded the page, not to identify anyone (the site has no user accounts).

def make_csrf(scope: str) -> str:
    ts = str(int(time.time()))
    sig = hmac.new(secret_key(), f"{scope}|{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_csrf(token: str | None, scope: str, max_age: int = 2 * 60 * 60) -> bool:
    if not token or "." not in token:
        return False
    ts, sig = token.split(".", 1)
    if not ts.isdigit():
        return False
    age = time.time() - int(ts)
    if age < 0 or age > max_age:
        return False
    expected = hmac.new(secret_key(), f"{scope}|{ts}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# ---------- admin sessions ----------

SESSION_TTL = 8 * 60 * 60  # 8 hours
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()


def new_session() -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sessions_lock:
        for t in [t for t, exp in _sessions.items() if exp < now]:
            _sessions.pop(t, None)
        _sessions[token] = now + SESSION_TTL
    return token


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    with _sessions_lock:
        exp = _sessions.get(token)
        if exp is None:
            return False
        if exp < time.time():
            _sessions.pop(token, None)
            return False
        return True


def end_session(token: str | None) -> None:
    if token:
        with _sessions_lock:
            _sessions.pop(token, None)


# ---------- input validation ----------

MAX_LEN = {
    "title": 200,
    "company": 200,
    "location": 120,
    "description": 8000,
    "apply_url": 2000,
    "contact": 200,
    "password": 200,
}

_URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ValidationError(ValueError):
    pass


def clean_text(value: str, field: str, *, required: bool = True, min_len: int = 1) -> str:
    """Strip control characters, enforce length. Output escaping happens at render time."""
    value = _CONTROL_CHARS_RE.sub("", (value or "").strip())
    limit = MAX_LEN.get(field, 500)
    if len(value) > limit:
        raise ValidationError(f"{field} is too long (max {limit} characters).")
    if required and len(value) < min_len:
        raise ValidationError(f"{field} is required.")
    return value


def clean_url(value: str, field: str = "apply_url") -> str:
    value = clean_text(value, field, required=False)
    if not value:
        return ""
    if not _URL_RE.match(value):
        raise ValidationError("apply_url must be a valid http(s) URL.")
    return value


def clean_choice(value: str, allowed: list[str], field: str, default: str | None = None) -> str:
    value = (value or "").strip()
    if value in allowed:
        return value
    if default is not None:
        return default
    raise ValidationError(f"{field} must be one of {allowed}.")


# ---------- Turnstile (optional bot check) ----------

def turnstile_enabled() -> bool:
    return bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET)


def verify_turnstile(token: str | None, ip: str) -> bool:
    """True when the check is off, or Cloudflare confirms the token. Fails closed if Cloudflare cannot be reached."""
    if not turnstile_enabled():
        return True
    if not token:
        return False
    import json as _json
    import urllib.parse
    import urllib.request
    data = urllib.parse.urlencode({"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip}).encode()
    try:
        req = urllib.request.Request("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return bool(_json.load(resp).get("success"))
    except Exception:                      # noqa: BLE001 - any failure means "not verified"
        return False
