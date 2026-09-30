"""
Storage for the student-network features: profiles, messaging, the feed, resume versions,
reports and AI usage caps. Same SQLite file as the job board (DB_PATH).

Every table here is keyed to an account in `users` (accounts.py). Deleting an account
goes through delete_account(), which removes or blanks everything that belongs to it.
"""

from __future__ import annotations

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
"""


# Columns added after the first release; existing databases are migrated in place.
_STUDENT_EXTRA = {"location": "TEXT NOT NULL DEFAULT ''", "looking_roles": "TEXT NOT NULL DEFAULT '[]'",
                  "pref_locations": "TEXT NOT NULL DEFAULT '[]'",
                  "allow_connections": "INTEGER NOT NULL DEFAULT 1"}
_EMPLOYER_EXTRA = {"tagline": "TEXT NOT NULL DEFAULT ''", "founded": "TEXT NOT NULL DEFAULT ''", "linkedin": "TEXT NOT NULL DEFAULT ''",
                   "hires_for": "TEXT NOT NULL DEFAULT '[]'", "perks": "TEXT NOT NULL DEFAULT '[]'"}
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
    conn.commit()


def purge(conn) -> None:
    """Data minimisation for the network features."""
    now = time.time()
    conn.execute("DELETE FROM ai_usage WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 86400)),))
    # Rejected or removed posts and removed messages keep their text for 30 days (appeals, abuse review), then go.
    conn.execute("DELETE FROM posts WHERE status IN ('rejected','removed') AND created_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM post_comments WHERE status = 'removed' AND created_at < ?", (now - 30 * 86400,))
    conn.execute("UPDATE messages SET body = '' WHERE status = 'removed' AND created_at < ?", (now - 30 * 86400,))
    conn.execute("DELETE FROM submitted_checks WHERE created_at < ?", (now - 365 * 86400,))
    # Listing stats and trackers go when their listing does; view counts are kept for 180 days.
    for t in ("job_views", "job_apply_clicks", "candidates", "applications"):
        conn.execute(f"DELETE FROM {t} WHERE job_id NOT IN (SELECT id FROM jobs)")
    conn.execute("DELETE FROM job_views WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(now - 180 * 86400)),))
    # Assistant chats go after 180 days without a new message.
    conn.execute("DELETE FROM assistant_chats WHERE updated_at < ?", (now - 180 * 86400,))
    conn.execute("DELETE FROM assistant_msgs WHERE chat_id NOT IN (SELECT id FROM assistant_chats)")
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
    conn.execute("DELETE FROM posts WHERE author_id = ?", (user_id,))
    conn.execute("DELETE FROM post_comments WHERE author_id = ?", (user_id,))
    conn.execute("DELETE FROM post_helpful WHERE user_id = ?", (user_id,))
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
    conn.execute("DELETE FROM assistant_msgs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM assistant_chats WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_tokens WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE jobs SET employer_id = NULL WHERE employer_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


# ---------- shared lookups ----------

def live_jobs(conn, ttl_days: int) -> list[dict]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - ttl_days * 86400))
    return rows(conn, "SELECT * FROM jobs WHERE review_status = 'approved' AND created_at >= ? "
                      "ORDER BY created_at DESC", (cutoff,))


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
