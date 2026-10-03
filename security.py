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
import ipaddress
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


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


# Where the real visitor address is, when TRUST_PROXY=1. Checked in order:
#   1. CLIENT_IP_HEADER: a header your CDN overwrites with the visitor's address. On Render (RENDER=true, set by Render
#      itself) this defaults to CF-Connecting-IP, then True-Client-IP: Render sits behind Cloudflare, whose edge sets
#      those, and its X-Forwarded-For reads "visitor, cloudflare, render-internal".
#   2. X-Forwarded-For, the entry TRUST_PROXY_HOPS from the right (1 = one proxy that appends the address).
# Check what the server sees on the admin page /admin/client-ip after deploying.
_default_ip_headers = "cf-connecting-ip,true-client-ip" if os.environ.get("RENDER", "").lower() == "true" else ""
CLIENT_IP_HEADERS = [h.strip().lower() for h in os.environ.get("CLIENT_IP_HEADER", _default_ip_headers).split(",") if h.strip()]
PROXY_HOPS = _env_int("TRUST_PROXY_HOPS", 1, 1, 10)
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

class _MemoryStore:
    """Sliding-window hit log in this process's memory. Right for one process (and for tests)."""

    def __init__(self):
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _dq(self, name, key, window, now):
        dq = self._hits[(name, key)]
        while dq and now - dq[0] > window:
            dq.popleft()
        return dq

    def take(self, name, key, limit, window, record=True):
        now = time.monotonic()
        with self._lock:
            dq = self._dq(name, key, window, now)
            if len(dq) >= limit:
                return False, max(int(window - (now - dq[0])) + 1, 1)
            if record:
                dq.append(now)
            return True, 0

    def hit(self, name, key, window):
        now = time.monotonic()
        with self._lock:
            self._dq(name, key, window, now).append(now)

    def refund(self, name, key):
        with self._lock:
            dq = self._hits.get((name, key))
            if dq:
                dq.pop()

    def reset(self, name):
        with self._lock:
            for k in [k for k in self._hits if k[0] == name]:
                del self._hits[k]


class _SqliteStore:
    """The same hit log in a SQLite file, so every worker process on the server shares one set of limits.
    (The app keeps all its data in one SQLite file on one disk, so it runs on one server; this covers several worker
    processes on it.) If the file can't be used, it falls back to memory rather than taking the site down."""

    MAX_WINDOW = 2 * 24 * 3600

    def __init__(self, path: str):
        import sqlite3
        self._sqlite3, self.path = sqlite3, path
        self._local = threading.local()
        self._fallback = _MemoryStore()
        self._ops = 0
        with self._conn() as _:
            pass

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("CREATE TABLE IF NOT EXISTS hits (lim TEXT NOT NULL, k TEXT NOT NULL, ts REAL NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS hits_lk ON hits (lim, k, ts)")
            self._local.conn = c
        return _Tx(c)

    def _tidy(self, c, now):
        self._ops += 1
        if self._ops % 500 == 0:
            c.execute("DELETE FROM hits WHERE ts < ?", (now - self.MAX_WINDOW,))

    def take(self, name, key, limit, window, record=True):
        try:
            now = time.time()
            with self._conn() as c:
                c.execute("DELETE FROM hits WHERE lim = ? AND k = ? AND ts <= ?", (name, key, now - window))
                n, first = c.execute("SELECT COUNT(*), MIN(ts) FROM hits WHERE lim = ? AND k = ?", (name, key)).fetchone()
                if n >= limit:
                    return False, max(int(window - (now - first)) + 1, 1)
                if record:
                    c.execute("INSERT INTO hits (lim, k, ts) VALUES (?, ?, ?)", (name, key, now))
                    self._tidy(c, now)
                return True, 0
        except self._sqlite3.Error:
            return self._fallback.take(name, key, limit, window, record)

    def hit(self, name, key, window):
        try:
            with self._conn() as c:
                c.execute("INSERT INTO hits (lim, k, ts) VALUES (?, ?, ?)", (name, key, time.time()))
        except self._sqlite3.Error:
            self._fallback.hit(name, key, window)

    def refund(self, name, key):
        try:
            with self._conn() as c:
                c.execute("DELETE FROM hits WHERE rowid = (SELECT rowid FROM hits WHERE lim = ? AND k = ? ORDER BY ts DESC LIMIT 1)",
                          (name, key))
        except self._sqlite3.Error:
            self._fallback.refund(name, key)

    def reset(self, name):
        try:
            with self._conn() as c:
                c.execute("DELETE FROM hits WHERE lim = ?", (name,))
        except self._sqlite3.Error:
            pass
        self._fallback.reset(name)


class _Tx:
    """BEGIN IMMEDIATE ... COMMIT, so a check-and-record is atomic across processes."""

    def __init__(self, conn):
        self.c = conn

    def __enter__(self):
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, exc_type, *_):
        self.c.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def _make_store():
    kind = os.environ.get("RATE_LIMIT_STORE", "sqlite" if IS_PROD else "memory").strip().lower()
    if kind == "sqlite":
        default = os.path.join(os.path.dirname(os.path.abspath(os.environ.get("DB_PATH", "jobs.db"))), "ratelimit.db")
        try:
            return _SqliteStore(os.environ.get("RATE_LIMIT_DB", default))
        except Exception:                        # noqa: BLE001 - never stop the site from starting over the limiter
            pass
    return _MemoryStore()


STORE = _make_store()


class RateLimiter:
    """A sliding-window limit: at most max_attempts per window_seconds per key. Its name (set below from the variable
    it's assigned to) keeps limiters apart in the shared store."""

    def __init__(self, max_attempts: int, window_seconds: int, name: str = ""):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.name = name

    def check(self, key: str) -> tuple[bool, int]:
        return STORE.take(self.name, key, self.max_attempts, self.window_seconds, record=False)

    def hit(self, key: str) -> None:
        STORE.hit(self.name, key, self.window_seconds)

    def take(self, key: str) -> tuple[bool, int]:
        """Check and record in one step, so concurrent requests can't all slip past the check."""
        return STORE.take(self.name, key, self.max_attempts, self.window_seconds)

    def refund(self, key: str) -> None:
        """Give back one recorded attempt (a log-in that turned out to succeed)."""
        STORE.refund(self.name, key)

    def reset_all(self) -> None:
        STORE.reset(self.name)


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
# Every endpoint: requests per client IP per minute (RequestGuard below).
GLOBAL_RATE_PER_MIN = _env_int("RATE_LIMIT_PER_MIN", 300, 30, 100_000)
# Log-in routes: failed attempts per client IP per window. A successful log-in doesn't count, so a campus network
# where many students share one public address isn't locked out by people logging in normally.
LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 5, 1, 100)
LOGIN_WINDOW_SECONDS = _env_int("LOGIN_WINDOW_MIN", 15, 1, 24 * 60) * 60
global_limiter = RateLimiter(max_attempts=GLOBAL_RATE_PER_MIN, window_seconds=60)
login_fail_limiter = RateLimiter(max_attempts=LOGIN_MAX_ATTEMPTS, window_seconds=LOGIN_WINDOW_SECONDS)
# Per account. Failed attempts only, so someone else can't lock you out by typing your address:
#   - from any one IP: the same 5 per window as above;
#   - from all IPs together: ACCOUNT_MAX_FAILS (stops slow guessing spread over many addresses).
user_login_email_limiter.max_attempts = LOGIN_MAX_ATTEMPTS
user_login_email_limiter.window_seconds = LOGIN_WINDOW_SECONDS
ACCOUNT_MAX_FAILS = _env_int("ACCOUNT_MAX_FAILS", 20, LOGIN_MAX_ATTEMPTS, 1000)
account_fail_limiter = RateLimiter(max_attempts=ACCOUNT_MAX_FAILS, window_seconds=LOGIN_WINDOW_SECONDS)
# Known devices. A browser that has logged in here before carries a signed cookie, and its failed log-ins are counted on
# their own (5 per window) instead of against the whole address. So when a campus network puts hundreds of students
# behind one public IP, a few strangers' typos don't lock everyone out. Browsers without the cookie share the address's
# 5; all known devices on one address together get LOGIN_SHARED_IP_MAX, so minting cookies doesn't buy endless guesses.
LOGIN_SHARED_IP_MAX = _env_int("LOGIN_SHARED_IP_MAX", 50, LOGIN_MAX_ATTEMPTS, 10_000)
login_shared_limiter = RateLimiter(max_attempts=LOGIN_SHARED_IP_MAX, window_seconds=LOGIN_WINDOW_SECONDS)
DEVICE_COOKIE = "ncs_dev"
PRE_COOKIE = "ncs_pre"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")


# The cookie is "<device id>.<user id>.<signature>": bound to the account that last logged in on that browser. For
# per-account limits it only changes how that one account's attempts are counted, so logging into your own account a
# dozen times doesn't buy extra guesses at anyone else's.

def _device_sig(dev_id: str, uid: int) -> str:
    return hmac.new(secret_key(), f"device|{dev_id}|{uid}".encode(), hashlib.sha256).hexdigest()[:32]


def new_device_cookie(uid: int, dev_id: str = "") -> str:
    dev_id = dev_id or secrets.token_urlsafe(12)
    return f"{dev_id}.{int(uid)}.{_device_sig(dev_id, int(uid))}"


def _device_parts(cookie_value: str | None) -> tuple[str, int]:
    parts = (cookie_value or "").split(".")
    if len(parts) == 3 and _TOKEN_RE.fullmatch(parts[0]) and parts[1].isdigit() and len(parts[1]) < 12 \
            and hmac.compare_digest(parts[2], _device_sig(parts[0], int(parts[1]))):
        return parts[0], int(parts[1])
    return "", 0


def device_id(cookie_value: str | None) -> str:
    """The id in a valid known-device cookie, else ""."""
    return _device_parts(cookie_value)[0]


def device_cookie_for(uid: int) -> str:
    """A cookie value binding this browser to the account that just logged in (keeps its device id if it had one)."""
    return new_device_cookie(uid, _pre_session.get().get("dev", ""))


def login_identity(ip: str, device_cookie: str | None, uid: int | None) -> str:
    """Who a log-in attempt at account `uid` is counted against: the address, or, on a browser that has logged into
    this same account before, the address plus that browser."""
    dev, owner = _device_parts(device_cookie)
    return f"{ip}|d:{dev}" if dev and uid and owner == uid else ip


def account_attempt(role: str, email: str, ip: str) -> tuple[str, list[tuple["RateLimiter", str]]]:
    """Reserve one log-in attempt against an account. Returns (verdict, slots):
      "ok"           check the password; pass the slots to account_success() if it's right (only failures stay counted)
      "blocked"      this address has used its 5 tries on this account: refuse without checking
      "only_correct" the account-wide cap is full (guessing from many addresses): check the password, let the right
                     one in, and refuse a wrong one. The owner is never locked out by strangers, and the guessers
                     learn nothing new: each of them is still held to 5 tries per address."""
    pair = (user_login_email_limiter, f"login:{role}:{email}:{ip}")
    ok, _ = pair[0].take(pair[1])
    if not ok:
        return "blocked", []
    acct = (account_fail_limiter, f"login:{role}:{email}")
    ok, _ = acct[0].take(acct[1])
    if not ok:
        # Someone is guessing from many addresses. Only the owner's own known browser still gets a password check;
        # everyone else waits out the window without one, so a refusal never tells a guesser anything.
        if "|d:" in ip:
            return "only_correct", [pair]
        pair[0].refund(pair[1])
        return "blocked", []
    return "ok", [pair, acct]


def account_success(slots) -> None:
    for lim, key in slots:
        lim.refund(key)

for _n, _v in list(globals().items()):
    if isinstance(_v, RateLimiter) and not _v.name:
        _v.name = _n

ALL_LIMITERS = (login_limiter, submit_limiter, general_limiter, user_login_limiter,
                user_login_email_limiter, signup_limiter, email_limiter, message_limiter, new_convo_limiter,
                check_limiter, ai_limiter, post_limiter, comment_limiter, upload_limiter, profile_limiter,
                public_check_limiter, school_limiter, global_limiter, login_fail_limiter, account_fail_limiter,
                login_shared_limiter)


def _valid_ip(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("[") and "]" in value:              # [ipv6]:port
        value = value[1:value.index("]")]
    elif value.count(":") == 1:                             # ipv4:port
        value = value.split(":")[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def resolve_ip(peer: str, header) -> tuple[str, str]:
    """(client address, where it came from). `header(name)` returns that header's value(s), comma-joined.
    Without TRUST_PROXY nothing the client sends is believed: the address is the connection's own."""
    peer = peer or "unknown"
    if not TRUST_PROXY:
        return peer, "connection"
    for name in CLIENT_IP_HEADERS:
        ip = _valid_ip((header(name) or "").split(",")[0])
        if ip:
            return ip, name
    parts = [p.strip() for p in (header("x-forwarded-for") or "").split(",") if p.strip()]
    if len(parts) >= PROXY_HOPS:
        ip = _valid_ip(parts[-PROXY_HOPS])
        if ip:
            return ip, f"x-forwarded-for (entry {PROXY_HOPS} from the right)"
    return peer, "connection"


def _ip_from(peer: str, forwarded: str) -> str:
    return resolve_ip(peer, lambda n: forwarded if n == "x-forwarded-for" else "")[0]


def client_ip(request: Request) -> str:
    return resolve_ip(request.client.host if request.client else "", lambda n: ",".join(request.headers.getlist(n)))[0]


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

# Pre-log-in forms (log in, sign up, reset, the public scam check) have no session to bind a token to, so each browser
# gets a random pre-session cookie and "form" tokens are bound to it. A token fetched by someone else is useless in your
# browser, which closes login CSRF (an attacker silently logging you into their account). RequestGuard sets the cookie.
import contextvars as _cv
# The cookie is only sent with a page that actually contains such a form, so just browsing sets no cookies.
_pre_session: _cv.ContextVar[dict] = _cv.ContextVar("pre_session", default={})


def _scoped(scope: str) -> str:
    return f"form|{_pre_session.get().get('id', '')}" if scope == "form" else scope


def make_csrf(scope: str) -> str:
    if scope == "form":
        _pre_session.get()["used"] = True
    scope = _scoped(scope)
    ts = str(int(time.time()))
    sig = hmac.new(secret_key(), f"{scope}|{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_csrf(token: str | None, scope: str, max_age: int = 2 * 60 * 60) -> bool:
    if not token or "." not in token:
        return False
    if scope == "form" and (not _pre_session.get().get("id") or _pre_session.get().get("new")):
        return False                             # no cookie came with the request: the token can't be this browser's
    scope = _scoped(scope)
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
    "poster_name": 80,
    "poster_title": 80,
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


# ---------- request guard ----------
# Runs on every request before the app does any work: per-IP rate limit on every endpoint, the log-in lockout,
# body-size caps, and rejection of malformed input (bad encodings, NUL bytes, oversized fields, broken JSON).
# Field-level rules (lengths per field, allowed choices) still live with each form, via clean_text() and friends.

import json as _json
from urllib.parse import parse_qsl as _parse_qsl, unquote_to_bytes as _unquote_to_bytes

MAX_BODY = _env_int("MAX_BODY_KB", 128, 16, 4096) * 1024                    # forms and JSON
MAX_UPLOAD_BODY = _env_int("MAX_UPLOAD_MB", 9, 1, 64) * 1024 * 1024          # multipart (resume, screenshot, PDF)
MAX_PATH = 2048
MAX_QUERY = 4096
MAX_FIELDS = 300
MAX_FIELD_CHARS = 50_000
MAX_JSON_DEPTH = 20
_LOGIN_PATH = re.compile(r"^/(?:login(?:/(?:student|employer))?|admin/login|verify|sso/(?:start|callback))/?$")
_BIG_FIELD_PATHS = ("/inbound/",)            # mail-provider webhooks carry whole emails in one field
_NO_GLOBAL_LIMIT = ("/healthz", "/static/")  # the host's health checks; fixed, cached site files
_CTRL = re.compile(rb"[\x00-\x1f\x7f]")
_BODY_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data", "application/json")
_GUARD_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
                  "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}

# app.py sets this so refusals on normal pages look like the rest of the site. (status, message, path) -> Response
GUARD_RENDER = None


class _Reject(Exception):
    def __init__(self, status: int, message: str, retry_after: int = 0):
        self.status, self.message, self.retry_after = status, message, retry_after


def _json_depth_ok(value, depth: int = 0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return False
    if isinstance(value, dict):
        return all(isinstance(k, str) and _json_depth_ok(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return all(_json_depth_ok(v, depth + 1) for v in value)
    if isinstance(value, str):
        return "\x00" not in value and len(value) <= MAX_FIELD_CHARS
    return True


def check_body(body: bytes, ctype: str, path: str) -> None:
    """Raises _Reject when a request body is malformed. ctype is the bare, lower-cased media type."""
    if not body:
        return
    if ctype not in _BODY_TYPES:
        raise _Reject(415, "That kind of request isn't accepted here.")
    if ctype == "application/x-www-form-urlencoded":
        limit = 1_000_000 if path.startswith(_BIG_FIELD_PATHS) else MAX_FIELD_CHARS
        try:
            pairs = _parse_qsl(body.decode("ascii"), keep_blank_values=True, strict_parsing=False,
                               encoding="utf-8", errors="strict", max_num_fields=MAX_FIELDS)
        except (UnicodeDecodeError, ValueError):
            raise _Reject(400, "That form couldn't be read. Refresh the page and try again.")
        for k, v in pairs:
            if "\x00" in k or "\x00" in v:
                raise _Reject(400, "That form couldn't be read. Refresh the page and try again.")
            if len(k) > 200 or len(v) > limit:
                raise _Reject(413, "Something you entered is far too long. Shorten it and try again.")
    elif ctype == "application/json":
        try:
            data = _json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _Reject(400, "Bad request.")
        if not _json_depth_ok(data):
            raise _Reject(400, "Bad request.")


def check_target(path_raw: bytes, query: bytes) -> None:
    if len(path_raw) > MAX_PATH or len(query) > MAX_QUERY:
        raise _Reject(414, "That address is too long.")
    if _CTRL.search(path_raw) or _CTRL.search(_unquote_to_bytes(query)):
        raise _Reject(400, "That address isn't valid.")
    try:
        _unquote_to_bytes(path_raw).decode("utf-8")
        _unquote_to_bytes(query.replace(b"+", b" ")).decode("utf-8")
    except UnicodeDecodeError:
        raise _Reject(400, "That address isn't valid.")


_NO_COOKIE_PATHS = ("/static/", "/healthz", "/robots.txt", "/inbound/")


def _cookies(header: str) -> dict:
    out = {}
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k and k not in out:
            out[k] = v.strip().strip('"')
    return out


def _set_cookie(name: str, value: str, max_age: int) -> tuple[bytes, bytes]:
    flags = f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if IS_PROD else "")
    return (b"set-cookie", flags.encode("latin-1"))


class RequestGuard:
    """Pure ASGI middleware (so it can stop a request before the body is read into the app)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        raw_headers = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in scope.get("headers", [])]
        headers = dict(raw_headers)
        peer = (scope.get("client") or ("", 0))[0]
        ip = resolve_ip(peer, lambda n: ",".join(v for k, v in raw_headers if k == n))[0]
        cookies = _cookies(headers.get("cookie", ""))
        login_slots: list[tuple[RateLimiter, str]] = []
        dev = device_id(cookies.get(DEVICE_COOKIE))
        pre = cookies.get(PRE_COOKIE, "")
        new_pre = ""
        if not _TOKEN_RE.fullmatch(pre):
            pre = new_pre = secrets.token_urlsafe(24)
        pre_state = {"id": pre, "new": bool(new_pre), "used": False, "dev": dev}
        _pre_session.set(pre_state)
        try:
            check_target(scope.get("raw_path") or path.encode("utf-8", "surrogateescape"), scope.get("query_string", b""))
            if not path.startswith(_NO_GLOBAL_LIMIT):
                ok, wait = global_limiter.check(f"all:{ip}")
                if not ok:
                    raise _Reject(429, f"Too many requests. Try again in {wait} seconds.", wait)
                global_limiter.hit(f"all:{ip}")
            if _LOGIN_PATH.match(path) and (method == "POST" or path.startswith("/sso/callback")):
                # Reserve the slot now and give it back if the log-in succeeds. Checking now and counting only
                # when the response goes out would let a burst of parallel guesses all get through.
                wanted = ([(login_fail_limiter, f"login:{ip}|d:{dev}"), (login_shared_limiter, f"login:{ip}")] if dev
                          else [(login_fail_limiter, f"login:{ip}")])
                ok, wait = True, 0
                for lim, key in wanted:
                    ok, wait = lim.take(key)
                    if not ok:
                        break
                    login_slots.append((lim, key))
                if not ok:
                    for lim, key in login_slots:
                        lim.refund(key)
                    login_slots = []
                    mins = max(1, round(wait / 60))
                    raise _Reject(429, f"Too many failed log-in attempts. Try again in about {mins} minute{'s' if mins != 1 else ''}.", wait)
            body = b""
            cl = headers.get("content-length", "")
            if cl and not cl.isdigit():
                raise _Reject(400, "Bad request.")
            if method in ("GET", "HEAD", "OPTIONS"):
                if cl and int(cl) > 0:
                    raise _Reject(400, "Bad request.")
            else:
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                big = ctype == "multipart/form-data"
                limit = MAX_UPLOAD_BODY if big else MAX_BODY
                if cl and int(cl) > limit:
                    raise _Reject(413, "That's too large to send. Shorten it or use a smaller file.")
                chunks, size, more = [], 0, True
                while more:
                    msg = await receive()
                    if msg["type"] == "http.disconnect":
                        return
                    part = msg.get("body", b"")
                    size += len(part)
                    if size > limit:
                        raise _Reject(413, "That's too large to send. Shorten it or use a smaller file.")
                    chunks.append(part)
                    more = msg.get("more_body", False)
                body = b"".join(chunks)
                check_body(body, ctype, path)
        except _Reject as r:
            return await self._refuse(scope, receive, send, r)      # a reserved log-in slot stays used

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed and method not in ("GET", "HEAD", "OPTIONS"):
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        quiet = path.startswith(_NO_COOKIE_PATHS)

        async def watch(message):
            if message["type"] == "http.response.start":
                extra = []
                if login_slots and message["status"] < 400:
                    for lim, key in login_slots:                  # it worked: successful log-ins don't count
                        lim.refund(key)
                if new_pre and pre_state["used"] and not quiet:
                    extra.append(_set_cookie(PRE_COOKIE, new_pre, 30 * 24 * 3600))
                if extra:
                    message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, replay if method not in ("GET", "HEAD", "OPTIONS") else receive, watch)

    async def _refuse(self, scope, receive, send, r: _Reject):
        from starlette.responses import JSONResponse, PlainTextResponse
        path = scope.get("path", "")
        extra = {"Retry-After": str(max(1, r.retry_after))} if r.status == 429 else {}
        resp = None
        if GUARD_RENDER and not path.startswith(("/api/", "/inbound/")):
            try:
                resp = GUARD_RENDER(r.status, r.message, path)
            except Exception:                    # noqa: BLE001  never let the error page itself fail open
                resp = None
        if resp is None:
            resp = (JSONResponse({"error": r.message}, status_code=r.status) if path.startswith(("/api/", "/inbound/"))
                    else PlainTextResponse(r.message, status_code=r.status))
        for k, v in {**_GUARD_HEADERS, **extra}.items():
            if k == "Content-Security-Policy" and k.lower() in resp.headers:
                continue                         # the site's own page brings the site's policy
            resp.headers[k] = v
        await resp(scope, receive, send)
