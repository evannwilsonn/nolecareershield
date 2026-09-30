"""Security and behavior tests. Run: python -m pytest -q"""
import os, re, sys, importlib, sqlite3, time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Everything that reads settings at import time, so each test gets a fresh copy.
LOCAL_MODULES = ("security", "app", "ui", "web", "store", "accounts", "mailer", "ai", "matching", "resume_engine",
                 "profiles", "messaging", "msgcheck", "assistant", "resume_tools", "feed", "admin_extra", "profile_page", "hiring",
                 "employer_page", "sso", "fit", "jobfit", "easyapply", "network", "quals", "emails", "jobboard", "css_feed", "css_jobs", "css_resume", "css_assist",
                 "scheduling", "msg_templates", "css_msg", "employer_dash", "css_employer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("CONTACT_EMAIL", "ops@example.org")
    monkeypatch.setenv("OUTBOX_LOG", str(tmp_path / "outbox.log"))
    for k in ("SMTP_HOST", "SMTP_FROM", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(k, raising=False)
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import security, app as appmod, accounts, mailer
    from fastapi.testclient import TestClient
    for lim in security.ALL_LIMITERS:
        lim.reset_all()
    mailer.outbox.clear()
    with TestClient(appmod.app, follow_redirects=False) as c:
        c.appmod, c.security, c.accounts, c.mailer = appmod, security, accounts, mailer
        yield c


def csrf_from(html):
    # The nav can hold a log-out form (its own token) ahead of the page's form, so take the last one.
    return re.findall(r'name="csrf" value="([^"]+)"', html)[-1]


PW = "Str0ng!pass"


def make_verified(client, role, email, pw=PW):
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        uid = client.accounts.create_user(db, email, role, pw)
        client.accounts.mark_verified(db, uid)
    return uid


def user_login(client, role, email, pw=PW, **over):
    tok = csrf_from(client.get(f"/login/{role}").text)
    data = {"email": email, "password": pw, "csrf": tok, "next": ""}
    data.update(over)
    return client.post(f"/login/{role}", data=data)


def ensure_employer(client, email="boss@acme.example"):
    if not getattr(client, "_employer", None):
        make_verified(client, "employer", email)
        assert user_login(client, "employer", email).status_code == 303
        client._employer = email


def mail_link(client, path):
    """The most recent emailed link whose path starts with `path`, e.g. '/verify'."""
    for m in reversed(client.mailer.outbox):
        hit = re.search(re.escape(client.appmod.BASE_URL) + r"(" + re.escape(path) + r"\?token=[\w-]+)", m["body"])
        if hit:
            return hit.group(1)
    raise AssertionError(f"no {path} link in outbox: {[m['subject'] for m in client.mailer.outbox]}")


def submit(client, **over):
    ensure_employer(client)
    tok = csrf_from(client.get("/post").text)
    data = dict(title="Data Analyst", company="Acme", category="Other", work_type="remote",
                location="", description="Analyze data using SQL.", apply_url="https://acme.com/j",
                contact="", csrf=tok, website="", direct="1")
    data.update(over)
    return client.post("/post", data=data)


def as_student(client, email="viewer@fsu.edu"):
    """Switch the client's site session to a verified student (employers don't browse the board; /jobs sends them to /hiring)."""
    make_verified(client, "student", email)
    assert user_login(client, "student", email).status_code == 303


def login(client, pw="correct-horse-battery"):
    tok = csrf_from(client.get("/admin").text)
    return client.post("/admin/login", data={"password": pw, "csrf": tok})


def test_public_pages_ok(client):
    for path in ("/", "/post", "/about", "/privacy", "/report", "/healthz", "/robots.txt", "/employers", "/check", "/login"):
        assert client.get(path).status_code == 200, path
    # The board itself is for signed-in FSU students and employers: visitors go to sign-in and come back after.
    for path, nxt in (("/jobs", "/jobs"), ("/job/1", "/job/1")):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"] == f"/login?next={nxt}", path
    assert "Disallow: /job/" in client.get("/robots.txt").text


def test_docs_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert client.get("/admin").headers["cache-control"] == "no-store"


def test_no_external_resources_or_cookies_for_visitors(client):
    r = client.get("/jobs")
    assert "googleapis" not in r.text and "<script" not in r.text
    assert "set-cookie" not in r.headers


def test_submission_requires_valid_csrf(client):
    r = client.post("/post", data=dict(title="t", company="c", work_type="remote",
                                       description="d", csrf="bad"))
    assert r.status_code == 400


def test_submission_is_pending_not_public(client):
    assert submit(client).status_code == 200
    assert "Data Analyst" not in client.get("/jobs").text


def test_honeypot_stores_nothing(client):
    submit(client, website="http://spam")
    assert client.appmod.pending_count() == 0


@pytest.mark.parametrize("field,value", [
    ("title", "x" * 201), ("description", "x" * 8001),
    ("apply_url", "javascript:alert(1)"), ("work_type", "<script>"),
])
def test_bad_input_rejected(client, field, value):
    assert submit(client, **{field: value}).status_code == 400


def test_xss_is_escaped_after_approval(client):
    submit(client, title='<img src=x onerror=alert(1)>', company='"><b>x</b>')
    login_resp = login(client)
    assert login_resp.status_code == 303
    page = client.get("/admin").text
    assert "<img src=x" not in page and "&lt;img" in page
    csrf = csrf_from(page)
    client.post("/admin/approve/1", data={"csrf": csrf})
    feed = client.get("/jobs").text
    assert "<img src=x" not in feed and "<b>x</b>" not in feed


def test_login_rate_limit_5_per_window(client):
    tok = csrf_from(client.get("/admin").text)
    codes = [client.post("/admin/login", data={"password": "no", "csrf": tok}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    assert login(client).status_code == 429  # even the right password is blocked


def test_login_needs_csrf_and_password(client):
    assert client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": "bad"}).status_code == 401
    assert login(client).status_code == 303


def test_admin_actions_need_session_and_csrf(client):
    submit(client)
    assert client.post("/admin/approve/1", data={"csrf": "x"}).headers["location"] == "/admin"
    assert client.appmod.public_count() == 0
    login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": "forged"})
    assert client.appmod.public_count() == 0            # bad token refused
    client.post("/admin/approve/1", data={"csrf": csrf})
    assert client.appmod.public_count() == 1


def test_csrf_token_bound_to_session(client):
    login(client)
    token_a = csrf_from(client.get("/admin").text)
    sec = client.security
    other = sec.make_csrf("admin:someone-else")
    assert sec.verify_csrf(token_a, "admin:" + client.cookies.get("session"))
    assert not sec.verify_csrf(other, "admin:" + client.cookies.get("session"))


def test_takedown_removes_listing(client):
    submit(client); login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": csrf})
    assert client.get("/jobs").headers["location"] == "/hiring"          # the employer who posted it goes to their listings
    as_student(client)
    assert "Data Analyst" in client.get("/jobs").text
    csrf = csrf_from(client.get("/admin/live").text)
    client.post("/admin/remove/1", data={"csrf": csrf})
    assert "Data Analyst" not in client.get("/jobs").text
    assert client.get("/job/1").status_code == 404


def test_listing_expires(client):
    submit(client); login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": csrf})
    import sqlite3
    with sqlite3.connect(client.appmod.DB_PATH) as db:
        db.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00'")
    assert client.appmod.public_count() == 0


def test_forwarded_header_ignored_unless_trusted(client):
    tok = csrf_from(client.get("/admin").text)
    codes = [client.post("/admin/login", data={"password": "no", "csrf": tok},
                         headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(6)]
    assert codes[-1] == 429  # spoofed XFF does not evade the limiter


def test_search_wildcards_are_literal(client):
    submit(client, title="100% Remote"); login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": csrf})
    as_student(client)
    assert "100%" in client.get("/jobs?search=100%25").text
    assert "No listings match" in client.get("/jobs?search=%25%25zzz").text


def test_prod_refuses_weak_config(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD", "changeme")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.setenv("BASE_URL", "http://insecure.example")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "only-one-key")
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)
    sys.modules.pop("security", None)
    import security
    with pytest.raises(RuntimeError) as e:
        security.validate_config()
    msg = str(e.value)
    for needle in ("ADMIN_PASSWORD", "SECRET_KEY", "CONTACT_EMAIL", "BASE_URL", "SMTP_HOST", "TURNSTILE"):
        assert needle in msg, needle


def test_prod_accepts_good_config_and_sets_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-unique-passphrase")
    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    monkeypatch.setenv("CONTACT_EMAIL", "ops@example.org")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("BASE_URL", "https://testserver")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_FROM", "NoleCareerShield <no-reply@example.org>")
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import app as appmod
    from fastapi.testclient import TestClient
    with TestClient(appmod.app, follow_redirects=False, base_url="https://testserver") as c:
        assert "max-age" in c.get("/").headers["strict-transport-security"]
        tok = csrf_from(c.get("/admin").text)
        r = c.post("/admin/login", data={"password": "a-long-unique-passphrase", "csrf": tok})
        sc = r.headers["set-cookie"].lower()
        assert "httponly" in sc and "secure" in sc and "samesite=strict" in sc


# ---------- adaptation loop: lead-gen axis, reviewer labels, export ----------

def _rows(client, sql="SELECT * FROM jobs ORDER BY id"):
    import sqlite3
    with sqlite3.connect(client.appmod.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(sql).fetchall()]


def test_lead_gen_listing_is_flagged_for_review_not_held(client):
    submit(client, company="Torentify", title="Remote Data Entry",
           apply_url="https://jooble.org/away/123?utm_source=affiliate&cpc=abc&extra_prev_uid=1")
    row = _rows(client)[0]
    assert row["scam_status"] == "flagged" and row["band"] == "clear"       # flagged, never 'held'
    assert row["review_status"] == "pending"
    assert any(f["rule_id"] == "lead_gen" for f in json_loads(row["findings_json"]))
    assert row["ruleset_version"]


def json_loads(s):
    import json
    return json.loads(s)


def test_reviewer_decisions_are_recorded_as_labels(client):
    for _ in range(4):
        submit(client)
    login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": csrf})
    client.post("/admin/reject/2", data={"csrf": csrf, "reason": "scam"})
    client.post("/admin/reject/3", data={"csrf": csrf, "reason": "lead_gen"})
    client.post("/admin/reject/4", data={"csrf": csrf, "reason": "<script>"})   # junk becomes 'other'
    labels = [r["review_label"] for r in _rows(client)]
    assert labels == ["legit", "scam", "lead_gen", "other"]
    assert all(r["reviewed_at"] for r in _rows(client))


def test_removal_records_a_reason(client):
    submit(client); login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/approve/1", data={"csrf": csrf})
    csrf = csrf_from(client.get("/admin/live").text)
    client.post("/admin/remove/1", data={"csrf": csrf, "reason": "scam"})
    assert _rows(client)[0]["review_label"] == "scam"


def test_agreement_stats_count_misses_and_false_alarms(client):
    appmod = client.appmod
    for _ in range(3):
        submit(client)
    # job 1: detector clear, reviewer says scam -> a miss; job 2: clear + legit -> agree;
    # job 3: force a flagged listing that the reviewer approves -> false alarm.
    import sqlite3
    with sqlite3.connect(appmod.DB_PATH) as db:
        db.execute("UPDATE jobs SET scam_status='flagged' WHERE id=3")
    login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/reject/1", data={"csrf": csrf, "reason": "scam"})
    client.post("/admin/approve/2", data={"csrf": csrf})
    client.post("/admin/approve/3", data={"csrf": csrf})
    st = appmod.agreement_stats()
    assert st == {"n": 3, "agree": 1, "missed": 1, "false_alarm": 1}
    assert "Too few to judge" in client.get("/admin").text


def test_old_database_is_migrated(tmp_path, monkeypatch):
    import sqlite3
    old = tmp_path / "old.db"
    with sqlite3.connect(old) as db:
        db.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            company TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Other', work_type TEXT NOT NULL,
            location TEXT, description TEXT NOT NULL, apply_url TEXT, contact TEXT, score INTEGER NOT NULL,
            band TEXT NOT NULL, scam_status TEXT NOT NULL, review_status TEXT NOT NULL,
            findings_json TEXT, created_at TEXT NOT NULL)""")
        db.execute("INSERT INTO jobs (title,company,work_type,description,score,band,scam_status,review_status,created_at)"
                   " VALUES ('t','c','remote','d',0,'clear','clear','approved','2026-01-01T00:00:00')")
    monkeypatch.setenv("ENV", "development"); monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DB_PATH", str(old)); monkeypatch.setenv("CONTACT_EMAIL", "ops@example.org")
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import app as appmod
    appmod.init_db()
    with sqlite3.connect(old) as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
        assert {"review_label", "ruleset_version", "reviewed_at"} <= cols
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1     # data preserved


def test_export_labels_masks_contact_details_and_skips_other(client, tmp_path):
    import json, importlib
    submit(client, description="Email jane.doe@gmail.com or call 850-555-0142 for details.",
           contact="jane.doe@gmail.com")
    submit(client); submit(client)
    login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/reject/1", data={"csrf": csrf, "reason": "scam"})
    client.post("/admin/approve/2", data={"csrf": csrf})
    client.post("/admin/reject/3", data={"csrf": csrf, "reason": "other"})
    sys.modules.pop("export_labeled", None)
    exp = importlib.import_module("export_labeled")
    out = tmp_path / "labeled.jsonl"
    counts = exp.export(client.appmod.DB_PATH, out)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["label"] for r in rows] == ["scam", "legit"]
    assert counts["skipped_other"] == 1 and counts["detector_missed"] == 1
    blob = out.read_text()
    assert "jane.doe" not in blob and "555-0142" not in blob and "contact" not in blob
    assert "[email]@gmail.com" in blob and "[phone]" in blob


# ---------- behavior found by clicking through the real site ----------

def test_error_pages_are_site_pages_not_json(client):
    for path in ("/no-such-page", "/job/not-a-number"):
        r = client.get(path)
        assert r.status_code in (400, 404), path
        assert "text/html" in r.headers["content-type"] and 'class="brand"' in r.text, path
        assert '"detail"' not in r.text
    r = client.get("/admin/approve/1")             # POST-only route opened as a link
    assert r.status_code == 405 and "text/html" in r.headers["content-type"]
    r = client.post("/post", data={"x": "1"})       # form with required fields missing
    assert r.status_code == 400 and "text/html" in r.headers["content-type"] and '"loc"' not in r.text


def test_rejected_submission_keeps_what_was_typed(client):
    r = submit(client, description="A very long careful description " * 5, apply_url="not a url", company="Bayside Dental")
    assert r.status_code == 400
    assert "valid http(s) URL" in r.text
    assert "A very long careful description" in r.text and "Bayside Dental" in r.text
    assert re.search(r'name="csrf" value="[^"]+"', r.text)       # fresh token, can resubmit at once


def test_expired_form_keeps_what_was_typed_and_resubmits(client):
    ensure_employer(client)
    r = client.post("/post", data=dict(title="Keep Me", company="Co", work_type="remote", description="Body text",
                                       csrf="1.stale"))
    assert r.status_code == 400 and "Keep Me" in r.text and "Body text" in r.text
    tok = csrf_from(r.text)
    ok = client.post("/post", data=dict(title="Keep Me", company="Co", work_type="remote", description="Body text",
                                        csrf=tok, direct="1"))
    assert ok.status_code == 200 and client.appmod.pending_count() == 1


def test_every_form_field_has_a_label(client):
    for path in ("/post", "/admin"):
        html = client.get(path).text
        for m in re.finditer(r'<input(?![^>]*type="hidden")[^>]*\bid="([^"]+)"|<(?:textarea|select)[^>]*\bid="([^"]+)"', html):
            field_id = m.group(1) or m.group(2)
            assert f'for="{field_id}"' in html, (path, field_id)
        assert not re.search(r'<(?:input|textarea|select)(?![^>]*type="hidden")(?![^>]*\bid=)', html), path


def test_stale_tab_cannot_flip_a_finished_decision(client):
    submit(client); login(client)
    csrf = csrf_from(client.get("/admin").text)
    client.post("/admin/reject/1", data={"csrf": csrf, "reason": "scam"})
    client.post("/admin/approve/1", data={"csrf": csrf})            # a second, stale tab
    assert client.appmod.public_count() == 0
    row = client.appmod.get_job(1)
    assert (row["review_status"], row["review_label"]) == ("rejected", "scam")
    # and a pending listing cannot be "removed" without ever having been live
    submit(client, title="Second")
    client.post("/admin/remove/2", data={"csrf": csrf})
    assert client.appmod.get_job(2)["review_status"] == "pending"


# ---------- accounts: students and employers ----------

@pytest.mark.parametrize("pw,missing", [
    ("Sh0rt!a", "at least 8 characters"),
    ("alllower1!x", "a capital letter"),
    ("NoDigits!here", "a number"),
    ("NoSymbol1here", "a symbol"),
    ("Password1!", "less guessable"),          # meets the character rules but is a top guess
    ("Boss9!boss", "less guessable"),          # contains the local part of the email below
])
def test_password_rules(client, pw, missing):
    problems = client.accounts.password_problems(pw, "boss@acme.example")
    assert any(missing in p for p in problems), problems


def test_good_password_passes(client):
    assert client.accounts.password_problems("Tr1cky!Horse", "a@b.co") == []


def test_only_the_exact_fsu_domain_counts_as_student(client):
    ok = client.accounts.is_fsu_email
    assert ok("jane@fsu.edu")
    for bad in ("jane@fsu.edu.evil.com", "jane@notfsu.edu", "jane@my.fsu.edu", "jane@fsu.edu@evil.com", "fsu.edu", "@fsu.edu"):
        assert not ok(bad), bad


def test_email_normalizing_blocks_header_injection(client):
    n = client.accounts.normalize_email
    assert n("  Jane@FSU.edu ") == "jane@fsu.edu"
    for bad in ("a@b.co\nBcc: x@y.co", "a b@c.co", "no-at-sign", "a@b", "x" * 300 + "@b.co", "<a>@b.co"):
        with pytest.raises(ValueError):
            n(bad)


def test_passwords_are_hashed_and_verify(client):
    h = client.accounts.hash_password(PW)
    assert PW not in h and h.startswith("scrypt$")
    assert client.accounts.verify_password(PW, h) and not client.accounts.verify_password("wrong", h)
    assert client.accounts.hash_password(PW) != h        # fresh salt each time
    assert not client.accounts.verify_password(PW, None) and not client.accounts.verify_password(PW, "garbage")


def signup(client, role, email, pw=PW, pw2=None, **over):
    tok = csrf_from(client.get(f"/signup/{role}").text)
    data = {"email": email, "password": pw, "password2": pw2 or pw, "csrf": tok, "next": "", "website": ""}
    data.update(over)
    return client.post(f"/signup/{role}", data=data)


def confirm(client, path="/verify", password=PW):
    link = mail_link(client, path)
    page = client.get(link)
    tok = csrf_from(page.text)
    token = re.search(r"token=([\w-]+)", link).group(1)
    return client.post("/verify", data={"token": token, "csrf": tok, "password": password})


def test_student_signup_needs_an_fsu_address(client):
    r = signup(client, "student", "jane@gmail.com")
    assert r.status_code == 400 and "@fsu.edu" in r.text and not client.mailer.outbox
    r = signup(client, "student", "jane@fsu.edu.evil.com")
    assert r.status_code == 400 and not client.mailer.outbox


def test_signup_enforces_password_rules_and_matching(client):
    for pw, needle in (("short", "8 characters"), ("nocapitals1!", "capital"), ("NoNumbers!!", "number"), ("NoSymbols11", "symbol")):
        r = signup(client, "student", "jane@fsu.edu", pw=pw)
        assert r.status_code == 400 and needle in r.text, (pw, r.text[:300])
    r = signup(client, "student", "jane@fsu.edu", pw2="Different1!x")
    assert r.status_code == 400 and "do not match" in r.text
    assert not client.mailer.outbox


def test_student_confirms_email_and_is_logged_in(client):
    r = signup(client, "student", "Jane@FSU.edu")
    assert r.status_code == 200 and "Check your email" in r.text
    assert [m["to"] for m in client.mailer.outbox] == ["jane@fsu.edu"]
    assert user_login(client, "student", "jane@fsu.edu").status_code == 403        # not confirmed yet
    link = mail_link(client, "/verify")
    page = client.get(link)                                                          # opening the link changes nothing
    assert "Confirm my email" in page.text and user_login(client, "student", "jane@fsu.edu").status_code == 403
    done = confirm(client)
    assert done.status_code == 200 and "Email confirmed" in done.text and "usession" in client.cookies
    assert confirm(client).status_code == 400                                        # link is single-use
    client.cookies.clear()
    assert user_login(client, "student", "jane@fsu.edu").status_code == 303


def test_signup_reveals_nothing_about_existing_accounts(client):
    make_verified(client, "student", "jane@fsu.edu")
    first = signup(client, "student", "new@fsu.edu")
    again = signup(client, "student", "jane@fsu.edu")
    assert first.status_code == again.status_code == 200
    strip = lambda t, e: re.sub(r"csrf\" value=\"[^\"]+", "", t.replace(e, "X"))
    assert strip(first.text, "new@fsu.edu") == strip(again.text, "jane@fsu.edu")
    assert any("already have" in m["subject"] for m in client.mailer.outbox if m["to"] == "jane@fsu.edu")


def test_login_errors_are_identical_for_unknown_and_wrong_password(client):
    make_verified(client, "student", "jane@fsu.edu")
    a = user_login(client, "student", "jane@fsu.edu", pw="Wrong1!pass")
    b = user_login(client, "student", "nobody@fsu.edu")
    assert a.status_code == b.status_code == 401
    msg = lambda r: re.search(r'role="alert">([^<]+)<', r.text).group(1)
    assert msg(a) == msg(b)


def test_student_and_employer_accounts_are_separate(client):
    make_verified(client, "student", "jane@fsu.edu")
    assert user_login(client, "employer", "jane@fsu.edu").status_code == 401
    make_verified(client, "employer", "jane@fsu.edu", pw="Other1!password")     # same address, other kind: allowed
    assert user_login(client, "employer", "jane@fsu.edu", pw="Other1!password").status_code == 303


def test_login_rate_limits(client):
    make_verified(client, "student", "jane@fsu.edu")
    codes = [user_login(client, "student", "jane@fsu.edu", pw="Wrong1!pass").status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429                     # per-account cap of 8 per 15 minutes
    assert user_login(client, "student", "jane@fsu.edu").status_code == 429   # even the right password waits


def test_forgot_and_reset_password(client):
    make_verified(client, "student", "jane@fsu.edu")
    def ask(email):
        tok = csrf_from(client.get("/forgot/student").text)
        return client.post("/forgot/student", data={"email": email, "csrf": tok})
    known, unknown = ask("jane@fsu.edu"), ask("nobody@fsu.edu")
    assert known.status_code == unknown.status_code == 200
    scrub = lambda h: re.sub(r'name="csrf" value="[^"]+"', "", h)
    assert scrub(known.text) == scrub(unknown.text)                # same page whether or not the account exists
    assert [m["to"] for m in client.mailer.outbox] == ["jane@fsu.edu"]
    link = mail_link(client, "/reset")
    token = re.search(r"token=([\w-]+)", link).group(1)
    page = client.get(link); tok = csrf_from(page.text)
    weak = client.post("/reset", data={"token": token, "password": "weak", "password2": "weak", "csrf": tok})
    assert weak.status_code == 400 and "8 characters" in weak.text
    ok = client.post("/reset", data={"token": token, "password": "N3w!Password", "password2": "N3w!Password", "csrf": tok})
    assert ok.status_code == 200 and "Password updated" in ok.text
    again = client.post("/reset", data={"token": token, "password": "An0ther!Pass", "password2": "An0ther!Pass", "csrf": tok})
    assert again.status_code == 400                                      # single use
    assert user_login(client, "student", "jane@fsu.edu").status_code == 401
    assert user_login(client, "student", "jane@fsu.edu", pw="N3w!Password").status_code == 303


def test_reset_logs_out_other_devices(client):
    make_verified(client, "student", "jane@fsu.edu")
    assert user_login(client, "student", "jane@fsu.edu").status_code == 303
    assert "Log out" in client.get("/about").text
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        uid = client.accounts.get_user(db, "jane@fsu.edu", "student")["id"]
        client.accounts.set_password(db, uid, "N3w!Password")
    assert "Log out" not in client.get("/about").text and "Log in" in client.get("/about").text


def test_tokens_and_sessions_are_stored_hashed(client):
    signup(client, "student", "jane@fsu.edu")
    raw = re.search(r"token=([\w-]+)", mail_link(client, "/verify")).group(1)
    confirm(client)
    session = client.cookies.get("usession")
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        blob = " ".join(str(v) for t in ("user_tokens", "user_sessions", "users") for row in db.execute(f"SELECT * FROM {t}") for v in row)
    assert raw not in blob and session not in blob and PW not in blob


def test_logout_needs_its_own_token(client):
    make_verified(client, "student", "jane@fsu.edu"); user_login(client, "student", "jane@fsu.edu")
    client.post("/logout", data={"csrf": "forged"})
    assert "Log out" in client.get("/jobs").text
    tok = csrf_from(client.get("/jobs").text)
    r = client.post("/logout", data={"csrf": tok})
    assert r.status_code == 303 and "Log out" not in client.get("/jobs").text


def test_next_parameter_cannot_leave_the_site(client):
    make_verified(client, "student", "jane@fsu.edu")
    for bad in ("https://evil.example", "//evil.example", "/admin", "javascript:alert(1)"):
        r = user_login(client, "student", "jane@fsu.edu", next=bad)
        assert r.status_code == 303 and r.headers["location"] in ("/", "/profile/setup"), bad
        client.cookies.clear()
    r = user_login(client, "student", "jane@fsu.edu", next="/job/7")
    assert r.headers["location"] == "/job/7"


# ---------- the submit-a-job gate ----------

def _post_data(client, **over):
    tok = csrf_from(client.get("/post").text)
    d = dict(title="Data Analyst", company="Acme", category="Other", work_type="remote", location="",
             description="Analyze data using SQL.", apply_url="https://acme.com/j", contact="", csrf=tok, website="", direct="1")
    d.update(over)
    return d


def test_post_page_says_login_comes_first(client):
    assert "log in or sign up before it sends" in client.get("/post").text
    ensure_employer(client)
    assert "Sending as boss@acme.example" in client.get("/post").text


def test_logged_out_submit_redirects_to_employer_login_and_stores_nothing(client):
    r = client.post("/post", data=_post_data(client))
    assert r.status_code == 303 and r.headers["location"] == "/login/employer?next=/post"
    assert client.appmod.pending_count() == 0 and "draft" in client.cookies
    page = client.get("/login/employer?next=/post").text
    assert "your listing is sent for review automatically" in page


def test_invalid_listing_is_rejected_before_any_login(client):
    r = client.post("/post", data=_post_data(client, apply_url="javascript:x"))
    assert r.status_code == 400 and "valid http(s) URL" in r.text and "draft" not in client.cookies


def test_new_employer_signup_then_confirm_sends_the_saved_listing(client):
    client.post("/post", data=_post_data(client, title="Saved While Logged Out"))
    r = signup(client, "employer", "hr@acme.example", next="/post")
    assert r.status_code == 200 and client.appmod.pending_count() == 0
    done = confirm(client)
    assert "Your listing was sent for review" in done.text
    rows = _rows(client)
    assert len(rows) == 1 and rows[0]["title"] == "Saved While Logged Out" and rows[0]["review_status"] == "pending"
    assert rows[0]["employer_id"] is not None
    assert any("We received your listing" in m["subject"] and m["to"] == "hr@acme.example" for m in client.mailer.outbox)
    assert confirm(client).status_code == 400
    assert len(_rows(client)) == 1                                        # the draft is used exactly once


def test_existing_employer_login_sends_the_saved_listing(client):
    make_verified(client, "employer", "hr@acme.example")
    client.post("/post", data=_post_data(client, title="Login Path"))
    r = user_login(client, "employer", "hr@acme.example")
    assert r.status_code == 303 and r.headers["location"] == "/submitted"
    assert [j["title"] for j in _rows(client)] == ["Login Path"]
    assert client.get("/submitted").status_code == 200


def test_student_account_cannot_post(client):
    make_verified(client, "student", "jane@fsu.edu"); user_login(client, "student", "jane@fsu.edu")
    r = client.post("/post", data=_post_data(client))
    assert r.status_code == 303 and "/login/employer" in r.headers["location"]
    assert client.appmod.pending_count() == 0
    nav = client.get("/jobs").text.split("</header>")[0]
    assert "Log out" in nav and "Post a job" not in nav          # students are not offered the post button


def test_reviewer_sees_which_confirmed_account_posted(client):
    submit(client)
    login(client)
    page = client.get("/admin").text
    assert "Posted by: boss@acme.example" in page


# ---------- only signed-in FSU students get the apply link ----------

def _approved_job(client):
    submit(client, apply_url="https://acme.example/secret-apply-link", contact="hr@acme.example")
    client.cookies.clear(); client._employer = None
    login(client)
    client.post("/admin/approve/1", data={"csrf": csrf_from(client.get("/admin").text)})
    client.cookies.clear()


def test_apply_link_is_hidden_from_visitors_and_employers(client):
    _approved_job(client)
    r = client.get("/job/1")
    assert r.status_code == 303 and "secret-apply-link" not in r.text                     # visitors don't see listings at all
    home = client.get("/").text                                                           # only a teaser: title, company, category
    assert "Data Analyst" in home and 'href="/login?next=/job/1"' in home and "secret-apply-link" not in home and "hr@acme.example" not in home
    make_verified(client, "employer", "other@corp.example"); user_login(client, "employer", "other@corp.example")
    assert "Log in as an FSU student to apply" in client.get("/job/1").text
    assert "secret-apply-link" not in client.get("/job/1").text


def test_signed_in_student_sees_the_apply_link(client):
    _approved_job(client)
    make_verified(client, "student", "jane@fsu.edu"); user_login(client, "student", "jane@fsu.edu")
    page = client.get("/job/1").text
    assert 'href="/job/1/apply"' in page and "Log in as an FSU student" not in page
    r = client.get("/job/1/apply", follow_redirects=False)       # counted once for the employer's totals, then on to the link
    assert r.status_code == 303 and r.headers["location"] == "https://acme.example/secret-apply-link"


def test_apply_link_is_not_leaked_to_visitors(client):
    _approved_job(client)
    r = client.get("/job/1/apply", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/job/1"
    assert "secret-apply-link" not in client.get("/job/1").text


# ---------- page policy ----------

def test_only_the_hashed_script_can_run_and_only_on_account_pages(client):
    csp = client.get("/").headers["content-security-policy"]
    assert f"script-src 'self' '{client.appmod.PAGE_SCRIPT_HASH}'" in csp and "unsafe-inline'" in csp.split("style-src")[1].split(";")[0]
    assert "script-src 'unsafe" not in csp
    import re
    # Public pages run no inline script; the only script is the same-origin decoration file (static/fx.js).
    for path in ("/", "/jobs", "/post", "/about", "/privacy"):
        tags = re.findall(r"<script[^>]*>", client.get(path).text)
        assert all(re.fullmatch(r'<script src="/static/fx\.js\?v=[0-9a-f]+" defer>', t) for t in tags) and len(tags) <= 1, path
    for path in ("/login/student", "/signup/employer", "/forgot/student"):
        html = client.get(path).text
        assert html.count("<script>") == 1 and f"<script>{client.appmod.PAGE_SCRIPT}</script>" in html, path
    import base64, hashlib
    assert client.appmod.PAGE_SCRIPT_HASH == "sha256-" + base64.b64encode(hashlib.sha256(client.appmod.PAGE_SCRIPT.encode()).digest()).decode()


def test_password_fields_have_show_buttons_and_labels(client):
    html = client.get("/signup/student").text
    assert html.count("data-showpw") >= 2 and 'for="f-password"' in html and "data-pwcheck" in html
    assert 'href="/forgot/student"' in client.get("/login/student").text


def test_unknown_role_is_404(client):
    for path in ("/login/admin", "/signup/hacker", "/forgot/root"):
        assert client.get(path).status_code == 404


def test_login_button_and_email_first_start(client):
    assert 'href="/login">Log in</a>' in client.get("/").text
    page = client.get("/login").text
    assert "Log in or sign up" in page and "Continue with email" in page and 'href="/employers"' in page
    emp = client.get("/employers").text
    assert "Create an employer account" in emp and 'href="/signup/employer"' in emp and 'href="/login/employer"' in emp
    # Students and employers have separate pages that point at each other, with no tabs between them.
    st, em = client.get("/login/student").text, client.get("/signup/employer").text
    assert "Student log in" in st and 'href="/employers"' in st and 'class="tabs"' not in st
    assert "Create your employer account" in em and 'href="/login">Log in with your @fsu.edu email' in em and 'class="tabs"' not in em
    head = client.get("/").text
    assert 'href="/employers">For employers</a>' in head and "Join with your FSU email" in head
    tok = csrf_from(page)
    r = client.post("/login", data={"csrf": tok, "email": "Jane@FSU.edu"})         # no SSO configured: straight to the student password page
    assert r.status_code == 200 and 'action="/login/student"' in r.text and 'value="jane@fsu.edu"' in r.text
    r = client.post("/login", data={"csrf": tok, "email": "hr@acme.example"})
    assert 'action="/login/employer"' in r.text and "isn't an @fsu.edu address" in r.text
    assert client.post("/login", data={"csrf": tok, "email": "nope"}).status_code == 400
    assert client.post("/login", data={"csrf": "bad", "email": "jane@fsu.edu"}).status_code == 400
    assert "jane@fsu.edu" not in r.headers.get("location", "")


def test_unconfirmed_accounts_are_purged_after_a_week(client):
    signup(client, "student", "jane@fsu.edu")
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        db.execute("UPDATE users SET created_at = ?", (time.time() - 8 * 86400,)); db.commit()
        client.accounts.purge_expired(db)
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_expired_draft_is_not_sent(client):
    make_verified(client, "employer", "hr@acme.example")
    client.post("/post", data=_post_data(client))
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        db.execute("UPDATE drafts SET expires_at = ?", (time.time() - 5,)); db.commit()
    assert user_login(client, "employer", "hr@acme.example").headers["location"] in ("/", "/profile/setup")
    assert client.appmod.pending_count() == 0


def test_turnstile_is_off_by_default_and_enforced_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "development"); monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ts.db")); monkeypatch.setenv("OUTBOX_LOG", str(tmp_path / "o.log"))
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key"); monkeypatch.setenv("TURNSTILE_SECRET", "secret")
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import security, app as appmod
    from fastapi.testclient import TestClient
    with TestClient(appmod.app, follow_redirects=False) as c:
        for lim in security.ALL_LIMITERS:
            lim.reset_all()
        csp = c.get("/").headers["content-security-policy"]
        assert "https://challenges.cloudflare.com" in csp and "frame-src" in csp
        page = c.get("/signup/student").text
        assert 'class="cf-turnstile"' in page and "challenges.cloudflare.com/turnstile/v0/api.js" in page
        tok = csrf_from(page)
        data = {"email": "jane@fsu.edu", "password": PW, "password2": PW, "csrf": tok, "next": "", "website": ""}
        assert c.post("/signup/student", data=data).status_code == 400        # no token: refused
        monkeypatch.setattr(security, "verify_turnstile", lambda token, ip: token == "good")
        monkeypatch.setattr(appmod.security, "verify_turnstile", security.verify_turnstile)
        assert c.post("/signup/student", data={**data, "cf-turnstile-response": "bad"}).status_code == 400
        assert c.post("/signup/student", data={**data, "cf-turnstile-response": "good"}).status_code == 200


def test_pre_registration_of_someone_elses_address_cannot_be_used(client):
    # An attacker signs up the victim's address with the attacker's password...
    signup(client, "employer", "victim@bigco.example", pw="Attack3r!pass")
    stale_link = mail_link(client, "/verify")
    # ...then the victim signs up for real. The newest sign-up wins and the old link dies.
    client.cookies.clear()
    signup(client, "employer", "victim@bigco.example", pw="Bl00m!ng#Tree")
    assert client.get(stale_link).status_code == 400
    # Even with the new link, only the victim's password confirms the account.
    link = mail_link(client, "/verify")
    tok = csrf_from(client.get(link).text); token = re.search(r"token=([\w-]+)", link).group(1)
    bad = client.post("/verify", data={"token": token, "csrf": tok, "password": "Attack3r!pass"})
    assert bad.status_code == 401 and "usession" not in client.cookies
    assert user_login(client, "employer", "victim@bigco.example", pw="Attack3r!pass").status_code in (401, 403)
    good = client.post("/verify", data={"token": token, "csrf": tok, "password": "Bl00m!ng#Tree"})
    assert good.status_code == 200 and "Email confirmed" in good.text


def test_confirming_needs_the_password(client):
    signup(client, "student", "jane@fsu.edu")
    link = mail_link(client, "/verify")
    tok = csrf_from(client.get(link).text); token = re.search(r"token=([\w-]+)", link).group(1)
    r = client.post("/verify", data={"token": token, "csrf": tok, "password": ""})
    assert r.status_code == 401 and "usession" not in client.cookies
    assert client.get(link).status_code == 200                      # a wrong try does not use the link up


def test_reviewer_pill_names_aggregators_instead_of_score_zero(client):
    import json as _json
    pill = client.appmod._score_pill
    assert ">Scam risk 60 · flagged<" in pill({"score": 0, "scam_status": "flagged", "findings_json": _json.dumps([{"rule_id": "lead_gen"}])})
    assert ">Scam risk 96 · held<" in pill({"score": 100, "scam_status": "held", "findings_json": "[]"})
    assert ">Scam risk 40 · flagged<" in pill({"score": 40, "scam_status": "flagged", "findings_json": _json.dumps([{"rule_id": "lead_gen"}])})



def test_font_and_effects_are_self_hosted(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "font-src 'self'" in csp and "fonts.googleapis" not in csp
    r = client.get("/static/fonts/archivo.woff2")
    assert r.status_code == 200 and r.headers["content-type"] == "font/woff2" and r.content[:4] == b"wOF2"
    r = client.get("/static/fx.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript") and "immutable" in r.headers["cache-control"]


def test_landing_pages_carry_the_new_blocks(client):
    home = client.get("/").text
    assert "data-cine" in home and 'class="marquee"' in home and "data-scan" in home and 'class="how-bento"' in home
    assert home.count('class="chapter"') == 2 and 'href="/check"' in home
    assert "—" not in re.sub(r"<title>.*?</title>", "", home)          # no em-dashes in visible copy
    emp = client.get("/employers").text
    assert 'class="how-bento three"' in emp and 'class="chapter top"' in emp and 'class="gets"' in emp


def test_landing_media_is_served_and_cached(client):
    import ui
    home = client.get("/").text
    for name in ("arch-000.webp", f"arch-{ui.CINE_FRAMES - 1:03d}.webp", "night-1920.webp", "fair-960.webp", "office-1920.webp"):
        r = client.get(f"/static/media/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert "immutable" in r.headers["cache-control"] and r.content[:4] == b"RIFF"
    assert f"/static/media/arch-000.webp?v={ui.MEDIA_VERSION}" in home and ui.MEDIA_VERSION != "1"
    # Only files that exist can be named: no paths, no other folders.
    for bad in ("../app.py", "..%2Fapp.py", "nope.webp", "arch-000.png"):
        assert client.get(f"/static/media/{bad}").status_code == 404


def test_scanner_flags_come_from_the_detector():
    """The landing-page scanner shows what the public scam check finds in the sample listing, nothing written by hand.
    Each expected rule must still fire AND underline its own phrase; a rule change that breaks that fails here."""
    import ui, msgcheck
    r = ui.scan_findings()
    by_id = {f["rule_id"]: f for f in r["findings"]}
    for rid, phrase in ui.SCAN_EXPECTED.items():
        assert rid in by_id, f"the detector no longer catches {rid}"
        spans = by_id[rid]["spans"]
        start = r["text"].lower().index(phrase.lower())
        assert any(a <= start < b or start <= a < start + len(phrase) for a, b in spans), f"{rid} no longer underlines {phrase!r}"
    s = ui.SCAN_SAMPLE
    direct = msgcheck.check_listing(s["title"], s["body"], s["company"], contact=s["apply"])
    html = ui.scan_block("")
    for f in direct["findings"]:                     # every title shown is the checker's own wording
        assert ui.esc(f["title"]) in html
    assert f"Scam risk {direct['score']}/100 from {len(direct['findings'])} signals" in html
    assert html.count(ui.esc(direct["title"])) == 2 and ui.esc(direct["steps"][0]) in html   # stamp, verdict, advice


def test_scanner_is_served_finished(client):
    """Without JS (or with reduced motion) the scene must read complete: fx.js alone adds armed/pinned."""
    home = client.get("/").text
    scene = home[home.index("<section class=\"scan\""):]
    scene = scene[:scene.index("</section>")]
    assert 'class="scan armed' not in scene and "pinned" not in scene
    assert "Here's what the scam check found in it." in scene and 'class="scan-stamp"' in scene
    assert scene.count('<li class=') == 8 and "--b" not in scene and "rotate" not in scene
    assert scene.count("<mark") >= len(__import__("ui").SCAN_EXPECTED) - 1
