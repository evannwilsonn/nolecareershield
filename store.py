"""
Storage for the student-network features: profiles, messaging, the feed, resume versions,
reports and AI usage caps. Same SQLite file as the job board (DB_PATH).

Every table here is keyed to an account in `users` (accounts.py). Deleting an account
goes through delete_account(), which removes or blanks everything that belongs to it.
"""

from __future__ import annotations

import calendar
import json
import os
import sqlite3
import time
from contextlib import contextmanager


def db_path() -> str:
    return os.environ.get("DB_PATH", "jobs.db")


@contextmanager
def db():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def jload(value, default):
    try:
        out = json.loads(value) if value else default
        return out if isinstance(out, type(default)) else default
    except (ValueError, TypeError):
        return default


SCHEMA = """
CREATE TABLE IF NOT EXISTS student_profiles (
    user_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    pronouns TEXT NOT NULL DEFAULT '',
    major TEXT NOT NULL DEFAULT '',
    minor TEXT NOT NULL DEFAULT '',
    degree TEXT NOT NULL DEFAULT '',
    grad_term TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    skills TEXT NOT NULL DEFAULT '[]',
    interests TEXT NOT NULL DEFAULT '[]',
    work_types TEXT NOT NULL DEFAULT '[]',
    job_kinds TEXT NOT NULL DEFAULT '[]',
    links TEXT NOT NULL DEFAULT '{}',
    resume_text TEXT NOT NULL DEFAULT '',
    resume_name TEXT NOT NULL DEFAULT '',
    resume_updated REAL,
    visible_to_employers INTEGER NOT NULL DEFAULT 0,
    share_resume INTEGER NOT NULL DEFAULT 0,
    allow_messages INTEGER NOT NULL DEFAULT 1,
    setup_step INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    org TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    start TEXT NOT NULL DEFAULT '',
    end TEXT NOT NULL DEFAULT '',
    current INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_user ON profile_items (user_id, kind, position);
CREATE TABLE IF NOT EXISTS employer_profiles (
    user_id INTEGER PRIMARY KEY,
    company TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    about TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    contact_title TEXT NOT NULL DEFAULT '',
    fsu_connection TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    status_note TEXT NOT NULL DEFAULT '',
    reviewed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emp_status ON employer_profiles (status);
CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    job_id INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL DEFAULT 0,
    subject TEXT NOT NULL DEFAULT '',
    started_by INTEGER NOT NULL,
    created_at REAL NOT NULL,
    last_at REAL NOT NULL,
    student_hidden INTEGER NOT NULL DEFAULT 0,
    employer_hidden INTEGER NOT NULL DEFAULT 0,
    blocked_by INTEGER,
    UNIQUE (student_id, employer_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_conv_student ON conversations (student_id, last_at);
CREATE INDEX IF NOT EXISTS idx_conv_employer ON conversations (employer_id, last_at);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    read_at REAL,
    scan_band TEXT NOT NULL DEFAULT 'clear',
    scan_score INTEGER NOT NULL DEFAULT 0,
    scan_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'delivered'
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_status ON messages (status);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    scan_band TEXT NOT NULL DEFAULT 'clear',
    scan_json TEXT NOT NULL DEFAULT '[]',
    relevance_json TEXT NOT NULL DEFAULT '{}',
    review_note TEXT NOT NULL DEFAULT '',
    helpful_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    reviewed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts (status, created_at);
CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published',
    scan_band TEXT NOT NULL DEFAULT 'clear',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_post ON post_comments (post_id, id);
CREATE TABLE IF NOT EXISTS post_helpful (
    post_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS post_saves (
    user_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, post_id)
);
CREATE INDEX IF NOT EXISTS idx_post_saves_post ON post_saves (post_id);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    UNIQUE (reporter_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS ai_usage (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS submitted_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    body TEXT NOT NULL,
    sender TEXT NOT NULL DEFAULT '',
    band TEXT NOT NULL,
    user_label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
-- "Want NoleCareerShield at your school?" from the public scam check. Only the school name is kept.
CREATE TABLE IF NOT EXISTS school_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school TEXT NOT NULL,
    created_at REAL NOT NULL
);
-- Employer hiring tools (hiring.py)
CREATE TABLE IF NOT EXISTS job_views (
    job_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (job_id, user_id, day)
);
CREATE TABLE IF NOT EXISTS job_apply_clicks (
    job_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, user_id)
);
CREATE TABLE IF NOT EXISTS candidates (
    job_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    stage TEXT NOT NULL DEFAULT 'new',
    source TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_cand_employer ON candidates (employer_id, job_id, stage);
CREATE TABLE IF NOT EXISTS notify_log (
    user_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    sent_at REAL NOT NULL,
    PRIMARY KEY (user_id, conversation_id)
);
-- Easy apply (easyapply.py): one application per student per listing, answers stored as JSON.
CREATE TABLE IF NOT EXISTS applications (
    job_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    answers TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    share_resume INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_app_employer ON applications (employer_id, job_id);
-- Student connections (network.py). user_a < user_b always; a declined request stays so it can't be resent.
CREATE TABLE IF NOT EXISTS connections (
    user_a INTEGER NOT NULL,
    user_b INTEGER NOT NULL,
    requested_by INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_a, user_b)
);
CREATE INDEX IF NOT EXISTS idx_conn_b ON connections (user_b, status);
-- Students following approved employers. Employers see the total, never who.
CREATE TABLE IF NOT EXISTS follows (
    student_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (student_id, employer_id)
);
CREATE INDEX IF NOT EXISTS idx_follow_emp ON follows (employer_id);
-- Company page views (employer_dash.py): students only, one row per viewer per day. Employers see totals, never who.
CREATE TABLE IF NOT EXISTS company_views (
    employer_id INTEGER NOT NULL,
    viewer_id INTEGER,
    day TEXT NOT NULL,
    UNIQUE (employer_id, viewer_id, day)
);
CREATE INDEX IF NOT EXISTS idx_company_views ON company_views (employer_id, day);
-- Jobs a student bookmarked on the board (jobboard.py). Private to the student; gone with the listing or the account.
-- In-site copy of every email sent to an account holder (emails.py). Sign-in links are redacted.
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at REAL NOT NULL,
    read_at REAL
);
CREATE INDEX IF NOT EXISTS idx_emails_user ON emails (user_id, sent_at);
CREATE TABLE IF NOT EXISTS saved_jobs (
    user_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_saved_jobs_job ON saved_jobs (job_id);
-- Career assistant chats (assistant.py). Only the student who owns a chat can read it. payload holds listing ids
-- and follow-up chips, never listing text: cards are rebuilt from live, approved listings each time a chat is shown.
CREATE TABLE IF NOT EXISTS assistant_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_achat_user ON assistant_chats (user_id, updated_at);
CREATE TABLE IF NOT EXISTS assistant_msgs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,                       -- 'user' | 'assistant'
    text TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    feedback INTEGER NOT NULL DEFAULT 0,      -- 1 thumbs up, -1 thumbs down
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amsg_chat ON assistant_msgs (chat_id, id);
-- What the Career assistant remembers about a student (assistant.py): short facts the student stated, never sensitive
-- data (a filter refuses SSNs, bank/card numbers, health and similar). The student can see, delete or clear them.
CREATE TABLE IF NOT EXISTS assistant_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    chat_id INTEGER,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amem_user ON assistant_memory (user_id, id);
-- Jobs the assistant showed in a chat are pinned to its side panel; a row with pinned = 0 means the student unpinned it.
-- Employer events (events.py): info sessions, career fair tables, workshops, coffee chats. Reviewed like listings
-- (pending -> approved). Times are UTC epoch seconds; pages show them in America/New_York.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    starts_at REAL NOT NULL,
    duration_min INTEGER NOT NULL DEFAULT 60,
    format TEXT NOT NULL DEFAULT 'in_person',  -- 'in_person' | 'virtual'
    location TEXT NOT NULL DEFAULT '',
    meeting_url TEXT NOT NULL DEFAULT '',
    capacity INTEGER NOT NULL DEFAULT 0,       -- 0 = no limit
    majors TEXT NOT NULL DEFAULT '[]',
    class_years TEXT NOT NULL DEFAULT '[]',
    job_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',    -- pending | approved | rejected | cancelled | removed
    scan_band TEXT NOT NULL DEFAULT 'clear',
    scan_json TEXT NOT NULL DEFAULT '[]',
    review_note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    reviewed_at REAL,
    cancelled_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events (status, starts_at);
CREATE INDEX IF NOT EXISTS idx_events_employer ON events (employer_id, starts_at);
-- RSVPs: going | waitlist | not_going. A student who RSVPs agrees the employer sees their name and major.
-- reminded_at records the day-before reminder so it is sent once.
CREATE TABLE IF NOT EXISTS event_rsvps (
    event_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    reminded_at REAL,
    PRIMARY KEY (event_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_rsvps_student ON event_rsvps (student_id);
CREATE TABLE IF NOT EXISTS assistant_pins (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, chat_id, job_id)
);
-- Interview scheduling inside Messages (scheduling.py). An employer proposes 1-5 slots; the student picks one.
-- status: open | confirmed | declined | cancelled | rescheduled. Times are UTC epoch seconds.
CREATE TABLE IF NOT EXISTS interview_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    format TEXT NOT NULL DEFAULT 'video',
    location TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    chosen_slot INTEGER,
    student_note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_iv_convo ON interview_proposals (conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_iv_student ON interview_proposals (student_id, status);
CREATE INDEX IF NOT EXISTS idx_iv_employer ON interview_proposals (employer_id, status);
CREATE TABLE IF NOT EXISTS interview_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL,
    starts_at REAL NOT NULL,
    minutes INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ivslot_p ON interview_slots (proposal_id);
-- The in-thread system lines ("Jordan picked Tue, Oct 6 at 2:00 PM ET").
CREATE TABLE IF NOT EXISTS interview_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ivev_convo ON interview_events (conversation_id, id);
-- Employers' saved replies (msg_templates.py). template_seeds marks that the four defaults were added once.
CREATE TABLE IF NOT EXISTS message_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mtpl_emp ON message_templates (employer_id, id);
CREATE TABLE IF NOT EXISTS template_seeds (
    employer_id INTEGER PRIMARY KEY
);
"""


# Columns added after the first release; existing databases are migrated in place.
_STUDENT_EXTRA = {"location": "TEXT NOT NULL DEFAULT ''", "looking_roles": "TEXT NOT NULL DEFAULT '[]'",
                  "pref_locations": "TEXT NOT NULL DEFAULT '[]'",
                  "allow_connections": "INTEGER NOT NULL DEFAULT 1"}
_EMPLOYER_EXTRA = {"tagline": "TEXT NOT NULL DEFAULT ''", "founded": "TEXT NOT NULL DEFAULT ''", "linkedin": "TEXT NOT NULL DEFAULT ''",
                   "hires_for": "TEXT NOT NULL DEFAULT '[]'", "perks": "TEXT NOT NULL DEFAULT '[]'"}
# Employer-private applicant-table fields (hiring.py): a 1-5 rating and an archive flag. The note column already exists.
_CAND_EXTRA = {"rating": "INTEGER NOT NULL DEFAULT 0", "archived": "INTEGER NOT NULL DEFAULT 0"}
ITEM_KINDS = ["experience", "education", "project", "certification", "organization", "course", "language"]


def init(conn) -> None:
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(student_profiles)")}
    for col, typ in _STUDENT_EXTRA.items():
        if col not in have:
            conn.execute(f"ALTER TABLE student_profiles ADD COLUMN {col} {typ}")
    have = {r[1] for r in conn.execute("PRAGMA table_info(employer_profiles)")}
    for col, typ in _EMPLOYER_EXTRA.items():
        if col not in have:
            conn.execute(f"ALTER TABLE employer_profiles ADD COLUMN {col} {typ}")
    have = {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
    for col, typ in _CAND_EXTRA.items():
        if col not in have:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {typ}")
    conn.commit()


def purge(conn) -> None:
    """Data minimisation for the network features."""
    now = time.time()
    conn.execute("DELETE FROM ai_usage WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 86400)),))
    # Rejected or removed posts and removed messages keep their text for 30 days (appeals, abuse review), then go.
    conn.execute("DELETE FROM posts WHERE status IN ('rejected','removed') AND created_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM post_comments WHERE status = 'removed' AND created_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM post_saves WHERE post_id NOT IN (SELECT id FROM posts)")
    conn.execute("UPDATE messages SET body = '' WHERE status = 'removed' AND created_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM submitted_checks WHERE created_at < ?", (now - 365 * 86400,))
    # Listing stats and trackers go when their listing does; view counts are kept for 180 days.
    for t in ("job_views", "job_apply_clicks", "candidates", "applications", "saved_jobs"):
        conn.execute(f"DELETE FROM {t} WHERE job_id NOT IN (SELECT id FROM jobs)")
    conn.execute("DELETE FROM job_views WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(now - 180 * 86400)),))
    conn.execute("DELETE FROM company_views WHERE day < ? OR employer_id NOT IN (SELECT user_id FROM employer_profiles)",
                 (time.strftime("%Y-%m-%d", time.gmtime(now - 180 * 86400)),))
    # In-site email copies are kept for a year.
    conn.execute("DELETE FROM emails WHERE sent_at < ?", (now - 365 * 86400,))
    # Assistant chats go after 180 days without a new message.
    conn.execute("DELETE FROM assistant_chats WHERE updated_at < ?", (now - 180 * 86400,))
    conn.execute("DELETE FROM assistant_msgs WHERE chat_id NOT IN (SELECT id FROM assistant_chats)")
    conn.execute("DELETE FROM assistant_pins WHERE chat_id NOT IN (SELECT id FROM assistant_chats)")
    # Assistant memories go when the account does, or after a year without being refreshed.
    conn.execute("DELETE FROM assistant_memory WHERE created_at < ?", (now - 365 * 86400,))
    # Interviews go with their conversation, or 180 days after their last proposed time.
    conn.execute("DELETE FROM interview_proposals WHERE conversation_id NOT IN (SELECT id FROM conversations)")
    conn.execute("DELETE FROM interview_proposals WHERE updated_at < ? AND COALESCE((SELECT MAX(starts_at) FROM interview_slots s "
                 "WHERE s.proposal_id = interview_proposals.id), 0) < ?", (now - 180 * 86400, now - 180 * 86400))
    conn.execute("DELETE FROM interview_slots WHERE proposal_id NOT IN (SELECT id FROM interview_proposals)")
    conn.execute("DELETE FROM interview_events WHERE proposal_id NOT IN (SELECT id FROM interview_proposals)")
    # Events: gone a year after they happened; rejected or removed ones after 30 days; RSVPs go with their event.
    conn.execute("DELETE FROM events WHERE starts_at < ?", (now - 365 * 86400,))
    conn.execute("DELETE FROM events WHERE status IN ('rejected','removed') AND updated_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM event_rsvps WHERE event_id NOT IN (SELECT id FROM events)")
    conn.commit()


def delete_account(conn, user_id: int) -> None:
    """Everything that belongs to one account. Messages the person sent are blanked (the other side
    keeps a visible gap, not the words); posts, comments, profile, resume versions and reports go."""
    conn.execute("DELETE FROM student_profiles WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM employer_profiles WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM resume_versions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM profile_items WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE messages SET body = '', status = 'removed' WHERE sender_id = ?", (user_id,))
    conn.execute("UPDATE conversations SET blocked_by = ? WHERE student_id = ? OR employer_id = ?",
                 (user_id, user_id, user_id))
    for (pid,) in conn.execute("SELECT id FROM posts WHERE author_id = ?", (user_id,)).fetchall():
        conn.execute("DELETE FROM post_comments WHERE post_id = ?", (pid,))
        conn.execute("DELETE FROM post_helpful WHERE post_id = ?", (pid,))
        conn.execute("DELETE FROM post_saves WHERE post_id = ?", (pid,))
    conn.execute("DELETE FROM posts WHERE author_id = ?", (user_id,))
    conn.execute("DELETE FROM post_comments WHERE author_id = ?", (user_id,))
    conn.execute("DELETE FROM post_helpful WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM post_saves WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM reports WHERE reporter_id = ?", (user_id,))
    conn.execute("DELETE FROM ai_usage WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM submitted_checks WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM notify_log WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM job_views WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM job_apply_clicks WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM candidates WHERE student_id = ? OR employer_id = ?", (user_id, user_id))
    conn.execute("DELETE FROM applications WHERE student_id = ? OR employer_id = ?", (user_id, user_id))
    conn.execute("DELETE FROM connections WHERE user_a = ? OR user_b = ?", (user_id, user_id))
    conn.execute("DELETE FROM follows WHERE student_id = ? OR employer_id = ?", (user_id, user_id))
    conn.execute("DELETE FROM company_views WHERE employer_id = ?", (user_id,))
    conn.execute("UPDATE company_views SET viewer_id = NULL WHERE viewer_id = ?", (user_id,))   # the employer keeps the total, not the person
    conn.execute("DELETE FROM saved_jobs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM emails WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM assistant_msgs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM assistant_chats WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM assistant_memory WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM assistant_pins WHERE user_id = ?", (user_id,))
    for (pid,) in conn.execute("SELECT id FROM interview_proposals WHERE student_id = ? OR employer_id = ?", (user_id, user_id)).fetchall():
        conn.execute("DELETE FROM interview_slots WHERE proposal_id = ?", (pid,))
        conn.execute("DELETE FROM interview_events WHERE proposal_id = ?", (pid,))
    conn.execute("DELETE FROM interview_proposals WHERE student_id = ? OR employer_id = ?", (user_id, user_id))
    conn.execute("DELETE FROM message_templates WHERE employer_id = ?", (user_id,))
    conn.execute("DELETE FROM template_seeds WHERE employer_id = ?", (user_id,))
    conn.execute("DELETE FROM event_rsvps WHERE student_id = ? OR event_id IN (SELECT id FROM events WHERE employer_id = ?)", (user_id, user_id))
    conn.execute("DELETE FROM events WHERE employer_id = ?", (user_id,))
    conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE jobs SET employer_id = NULL WHERE employer_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


# ---------- shared lookups ----------

def live_jobs(conn, ttl_days: int | None = None) -> list[dict]:
    return rows(conn, f"SELECT * FROM jobs WHERE {live_where(ttl_days=ttl_days)} ORDER BY created_at DESC")


# ---------- listing visibility: the one rule for what students can see ----------
# A listing is on the board only when a reviewer approved it, the employer hasn't paused or closed it
# (jobs.listing_status), and it hasn't expired (jobs.expires_at, set when it is approved). Listings approved
# before expiry dates existed (expires_at NULL) fall back to the old rule: LISTING_TTL_DAYS after they were posted.
# Every public query (board, job page, assistant, resume tools, feed, company pages) goes through live_where()
# in SQL or visible_listing() in Python.

LISTING_DAYS_DEFAULT, LISTING_DAYS_MIN, LISTING_DAYS_MAX, REMIND_DAYS = 60, 7, 120, 5


def _ttl_days(ttl_days: int | None = None) -> int:
    return int(ttl_days or os.environ.get("LISTING_TTL_DAYS", "90"))


def _old_cutoff(ttl_days: int | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - _ttl_days(ttl_days) * 86400))


def live_where(alias: str = "", ttl_days: int | None = None) -> str:
    """SQL condition (no parameters) for listings students may see. alias: the jobs table's alias, e.g. "j"."""
    a = alias + "." if alias else ""
    now = int(time.time())
    return (f"({a}review_status = 'approved' AND COALESCE({a}listing_status, 'open') = 'open' AND "
            f"(({a}expires_at IS NOT NULL AND {a}expires_at > {now}) OR ({a}expires_at IS NULL AND {a}created_at >= '{_old_cutoff(ttl_days)}')))")


def expires_ts(j: dict) -> float | None:
    """When the listing drops off the board (epoch seconds), or None if it was never approved."""
    if j.get("expires_at"):
        return float(j["expires_at"])
    if j.get("review_status") != "approved":
        return None
    try:
        made = calendar.timegm(time.strptime(str(j.get("created_at") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None
    return made + _ttl_days() * 86400


def listing_state(j: dict | None) -> str:
    """pending | rejected | removed | closed | paused | expired | live."""
    if not j:
        return "removed"
    rs = j.get("review_status")
    if rs != "approved":
        return rs or "pending"
    ls = j.get("listing_status") or "open"
    if ls in ("closed", "paused"):
        return ls
    exp = expires_ts(j)
    return "expired" if exp is not None and exp <= time.time() else "live"


def visible_listing(j: dict | None) -> bool:
    """True when students may see and apply to this listing (the Python twin of live_where)."""
    return listing_state(j) == "live"


def live_job(conn, job_id: int) -> dict | None:
    return row(conn, f"SELECT * FROM jobs WHERE id = ? AND {live_where()}", (job_id,))


def student_profile(conn, user_id: int) -> dict | None:
    p = row(conn, "SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    if p:
        for k in ("skills", "interests", "work_types", "job_kinds", "looking_roles", "pref_locations"):
            p[k] = jload(p.get(k), [])
        p["links"] = jload(p["links"], {})
        p["items"] = profile_items(conn, user_id)
    return p


def profile_items(conn, user_id: int) -> list[dict]:
    out = rows(conn, "SELECT * FROM profile_items WHERE user_id = ? ORDER BY position, id", (user_id,))
    for it in out:
        it["extra"] = jload(it["extra"], {})
        it["current"] = bool(it["current"])
    return out


def employer_profile(conn, user_id: int) -> dict | None:
    return row(conn, "SELECT * FROM employer_profiles WHERE user_id = ?", (user_id,))


def employer_approved(conn, user_id: int) -> bool:
    r = conn.execute("SELECT status FROM employer_profiles WHERE user_id = ?", (user_id,)).fetchone()
    return bool(r and r[0] == "approved")


def applied_to(conn, student_id: int, employer_id: int) -> dict | None:
    """The student's latest easy-apply application to any of this employer's listings, if there is one."""
    return row(conn, "SELECT job_id, share_resume FROM applications WHERE student_id = ? AND employer_id = ? "
                     "ORDER BY created_at DESC LIMIT 1", (student_id, employer_id))


def unread_count(conn, user_id: int) -> int:
    r = conn.execute("""
        SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
        WHERE (c.student_id = ? OR c.employer_id = ?) AND m.sender_id != ? AND m.read_at IS NULL
          AND m.status = 'delivered' AND c.blocked_by IS NULL
          AND NOT (c.student_id = ? AND c.student_hidden = 1) AND NOT (c.employer_id = ? AND c.employer_hidden = 1)
    """, (user_id, user_id, user_id, user_id, user_id)).fetchone()
    return int(r[0]) if r else 0


def ai_take(conn, user_id: int, daily_limit: int) -> bool:
    """Count one AI request against today's allowance. False when the allowance is used up."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    r = conn.execute("SELECT count FROM ai_usage WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()
    used = r[0] if r else 0
    if used >= daily_limit:
        return False
    conn.execute("INSERT INTO ai_usage (user_id, day, count) VALUES (?,?,1) "
                 "ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1", (user_id, day))
    conn.commit()
    return True


def ai_used_today(conn, user_id: int) -> int:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    r = conn.execute("SELECT count FROM ai_usage WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()
    return r[0] if r else 0
