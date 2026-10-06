"""PRIVATE_BETA_CODE: the site runs live but closed until the code is entered."""
import re, sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import LOCAL_MODULES, PW, csrf_from, make_verified  # noqa: E402


@pytest.fixture()
def beta(tmp_path, monkeypatch):
    for k, v in {"ENV": "development", "ADMIN_PASSWORD": "correct-horse-battery", "SECRET_KEY": "x" * 40,
                 "DB_PATH": str(tmp_path / "b.db"), "CONTACT_EMAIL": "ops@example.org", "OUTBOX_LOG": str(tmp_path / "o.log"),
                 "PRIVATE_BETA_CODE": "noles-only-2026"}.items():
        monkeypatch.setenv(k, v)
    for k in ("SMTP_HOST", "SMTP_FROM", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
        monkeypatch.delenv(k, raising=False)
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import security, app as appmod, accounts
    from fastapi.testclient import TestClient
    for lim in security.ALL_LIMITERS:
        lim.reset_all()
    with TestClient(appmod.app, follow_redirects=False) as c:
        c.appmod, c.accounts, c.security = appmod, accounts, security
        yield c
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)


def enter(c, code, nxt=""):
    tok = csrf_from(c.get("/beta" + (f"?next={nxt}" if nxt else "")).text)
    return c.post("/beta", data={"code": code, "csrf": tok, "next": unquote(nxt)})


def test_everything_is_closed_until_the_code_is_entered(beta):
    for path in ("/", "/jobs", "/check", "/login/student", "/privacy", "/terms"):
        r = beta.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/beta"), path
    assert beta.post("/login/student", data={"email": "a@fsu.edu", "password": "x"}).status_code == 403
    assert beta.get("/healthz").text == "ok" and beta.get("/static/app.js").status_code == 200
    assert beta.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
    assert "noindex" in beta.get("/beta").headers.get("x-robots-tag", "")
    assert beta.get("/admin").status_code == 200                     # the reviewer desk has its own password


def test_the_right_code_opens_the_site_and_keeps_email_link_tokens(beta):
    r = beta.get("/verify?token=abc123")
    nxt = re.search(r"next=([^&]+)", r.headers["location"]).group(1)
    assert enter(beta, "wrong-code", nxt).status_code == 401
    ok = enter(beta, "noles-only-2026", nxt)
    assert ok.status_code == 303 and ok.headers["location"] == "/verify?token=abc123"
    assert beta.get("/").status_code == 200 and beta.get("/jobs").status_code in (200, 303)
    make_verified(beta, "student", "tester@fsu.edu")
    tok = csrf_from(beta.get("/login/student").text)
    assert beta.post("/login/student", data={"email": "tester@fsu.edu", "password": PW, "csrf": tok, "next": ""}).status_code == 303


def test_next_can_never_leave_the_site(beta):
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example"):
        assert beta.appmod._beta_next(bad) == ""
    r = enter(beta, "noles-only-2026", "%2F%2Fevil.example")
    assert r.headers["location"] == "/"


def test_guessing_the_code_is_rate_limited(beta):
    codes = [enter(beta, f"guess{i}").status_code for i in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_a_forged_or_old_cookie_doesnt_work(beta):
    beta.cookies.set("ncs_beta", "0" * 40)
    assert beta.get("/").status_code == 303
