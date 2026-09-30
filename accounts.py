"""
Accounts for NoleCareerShield: password rules, hashing, users, one-time tokens,
login sessions and saved post drafts.

Two kinds of account, kept separate:
  * student  - email must be @fsu.edu; can log in to see the Apply link on listings
  * employer - any email; must log in to send a listing for review

Both need a confirmed email address and a password of 8+ characters with a capital
letter, a number and a symbol. Nothing else about a person is stored: no name, no
resume, no profile. Tokens and session ids are stored only as SHA-256 hashes, so a
copy of the database cannot be used to log in or reset a password.

All functions take an open sqlite3 connection and commit their own writes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

ROLES = ("student", "employer")
STUDENT_DOMAIN = "fsu.edu"

PW_MIN, PW_MAX = 8, 128
_UPPER = re.compile(r"[A-Z]")
_DIGIT = re.compile(r"[0-9]")
_SYMBOL = re.compile(r"[!-/:-@\[-`{-~]")            # ASCII punctuation; the page script uses the same set
_EMAIL = re.compile(r"^[^@\s<>\"',;:\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}$")

# Passwords that satisfy the character rules but are guessed first. Compared after
# removing digits and symbols and lowercasing, so "Password1!" and "P@ssw0rd" both hit.
_COMMON = {
    "password", "passw", "passwd", "letmein", "welcome", "qwerty", "qwertyuiop", "admin", "administrator",
    "iloveyou", "monkey", "dragon", "football", "baseball", "seminoles", "seminole", "noles", "gonoles",
    "floridastate", "tallahassee", "fsu", "changeme", "abcdef", "abcdefgh", "trustno", "sunshine", "princess",
}

VERIFY_TTL = 24 * 3600
RESET_TTL = 60 * 60
SESSION_TTL = 7 * 24 * 3600
DRAFT_TTL = 3 * 24 * 3600
UNVERIFIED_PURGE = 7 * 24 * 3600


# ---------- email and password rules ----------

def normalize_email(value: str) -> str:
    """Lower-case, trimmed, and safe to put in a mail header. Raises ValueError if not an address."""
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def is_fsu_email(email: str) -> bool:
    """Exactly the @fsu.edu domain. Lookalikes (fsu.edu.evil.com, notfsu.edu, sub.fsu.edu) do not pass."""
    local, _, domain = email.rpartition("@")
    return bool(local) and domain == STUDENT_DOMAIN


def password_problems(pw: str, email: str = "") -> list[str]:
    """Every unmet requirement, in plain words. An empty list means the password is acceptable."""
    pw = pw or ""
    out = []
    if len(pw) < PW_MIN:
        out.append(f"at least {PW_MIN} characters")
    if len(pw) > PW_MAX:
        out.append(f"no more than {PW_MAX} characters")
    if not _UPPER.search(pw):
        out.append("a capital letter")
    if not _DIGIT.search(pw):
        out.append("a number")
    if not _SYMBOL.search(pw):
        out.append("a symbol such as ! ? # $ %")
    if not out:
        core = re.sub(r"[^A-Za-z]", "", pw).lower()
        local = email.split("@")[0].lower() if email else ""
        if core in _COMMON or (len(local) >= 4 and local in pw.lower()):
            out.append("something less guessable (not a common word or part of your email)")
    return out


def requirement_text(problems: list[str]) -> str:
    return "Your password needs " + ", ".join(problems[:-1]) + (" and " if len(problems) > 1 else "") + problems[-1] + "."


# ---------- password hashing (scrypt, standard library) ----------

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(pw: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, want = (stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(want))
    except (ValueError, TypeError):
        return False


# Checked when the email is unknown, so a missing account takes as long to reject as a wrong password.
DUMMY_HASH = hash_password("not-a-real-password-just-timing")


# ---------- schema ----------

def init_account_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student','employer')),
            pw_hash TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            verified_at REAL,
            UNIQUE (email, role)
        );
        CREATE TABLE IF NOT EXISTS user_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            purpose TEXT NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
            token_hash TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
    """)
    db.commit()


def _h(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


# ---------- users ----------

def create_user(db, email: str, role: str, password: str) -> int | None:
    """Returns the new id, or None when that email already has an account of this kind."""
    if role not in ROLES:
        raise ValueError("unknown role")
    try:
        cur = db.execute("INSERT INTO users (email, role, pw_hash, created_at) VALUES (?,?,?,?)",
                         (email, role, hash_password(password), time.time()))
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user(db, email: str, role: str) -> dict | None:
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM users WHERE email = ? AND role = ?", (email, role)).fetchone()
    return dict(row) if row else None


def get_user_by_id(db, user_id: int) -> dict | None:
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def restart_unverified(db, user_id: int, password: str) -> None:
    """Someone signed up again with an address that still has an unconfirmed account. The newest sign-up wins:
    its password replaces the old one and every earlier confirmation link stops working. Together with asking for
    the password when a link is confirmed, this stops a stranger from registering your address with their own
    password and waiting for you to click."""
    db.execute("UPDATE users SET pw_hash = ? WHERE id = ? AND verified = 0", (hash_password(password), user_id))
    db.execute("UPDATE user_tokens SET used = 1 WHERE user_id = ? AND purpose = 'verify'", (user_id,))
    db.commit()


def mark_verified(db, user_id: int) -> None:
    db.execute("UPDATE users SET verified = 1, verified_at = COALESCE(verified_at, ?) WHERE id = ?", (time.time(), user_id))
    db.commit()


def set_password(db, user_id: int, password: str) -> None:
    """New password: every login session and every unused link for this account stops working."""
    db.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(password), user_id))
    db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    db.execute("UPDATE user_tokens SET used = 1 WHERE user_id = ? AND purpose = 'reset'", (user_id,))
    db.commit()


# ---------- one-time tokens (email confirmation, password reset) ----------

def issue_token(db, user_id: int, purpose: str, ttl: int) -> str:
    raw = secrets.token_urlsafe(32)
    db.execute("INSERT INTO user_tokens (token_hash, user_id, purpose, expires_at) VALUES (?,?,?,?)",
               (_h(raw), user_id, purpose, time.time() + ttl))
    db.commit()
    return raw


def peek_token(db, raw: str, purpose: str) -> int | None:
    """Is this link still good? Does not use it up (so an email scanner opening the link changes nothing)."""
    row = db.execute("SELECT user_id FROM user_tokens WHERE token_hash = ? AND purpose = ? AND used = 0 AND expires_at > ?",
                     (_h(raw), purpose, time.time())).fetchone()
    return row[0] if row else None


def consume_token(db, raw: str, purpose: str) -> int | None:
    """Use the link up. Returns the account id once; any second attempt gets None."""
    cur = db.execute("UPDATE user_tokens SET used = 1 WHERE token_hash = ? AND purpose = ? AND used = 0 AND expires_at > ?",
                     (_h(raw), purpose, time.time()))
    db.commit()
    if cur.rowcount != 1:
        return None
    return db.execute("SELECT user_id FROM user_tokens WHERE token_hash = ?", (_h(raw),)).fetchone()[0]


# ---------- login sessions ----------

def create_session(db, user_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    db.execute("INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
               (_h(raw), user_id, time.time() + SESSION_TTL))
    db.commit()
    return raw


def session_user(db, raw: str | None) -> dict | None:
    if not raw:
        return None
    db.row_factory = sqlite3.Row
    row = db.execute("""SELECT u.id, u.email, u.role FROM user_sessions s JOIN users u ON u.id = s.user_id
                        WHERE s.token_hash = ? AND s.expires_at > ? AND u.verified = 1""",
                     (_h(raw), time.time())).fetchone()
    return dict(row) if row else None


def end_session(db, raw: str | None) -> None:
    if raw:
        db.execute("DELETE FROM user_sessions WHERE token_hash = ?", (_h(raw),))
        db.commit()


# ---------- saved drafts (a listing typed while logged out) ----------

def save_draft(db, data: dict) -> str:
    raw = secrets.token_urlsafe(24)
    db.execute("INSERT INTO drafts (token_hash, data, expires_at) VALUES (?,?,?)",
               (_h(raw), json.dumps(data), time.time() + DRAFT_TTL))
    db.commit()
    return raw


def take_draft(db, raw: str | None) -> dict | None:
    """Returns the saved listing and deletes it, so it can only be sent once."""
    if not raw:
        return None
    row = db.execute("SELECT data, expires_at FROM drafts WHERE token_hash = ?", (_h(raw),)).fetchone()
    if not row:
        return None
    cur = db.execute("DELETE FROM drafts WHERE token_hash = ?", (_h(raw),))
    db.commit()
    if cur.rowcount != 1 or row[1] < time.time():
        return None
    return json.loads(row[0])


def purge_expired(db) -> None:
    now = time.time()
    db.execute("DELETE FROM user_tokens WHERE expires_at < ? OR used = 1", (now,))
    db.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now,))
    db.execute("DELETE FROM drafts WHERE expires_at < ?", (now,))
    db.execute("DELETE FROM users WHERE verified = 0 AND created_at < ?", (now - UNVERIFIED_PURGE,))
    db.commit()
