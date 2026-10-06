"""Regression tests for the October 2026 security audit: lockout races, lockout abuse, parser blow-ups,
employer renames, and the smaller injection and leak fixes."""
import asyncio, io, sqlite3, sys, time, zipfile
from contextlib import closing
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import PW, client, csrf_from, make_verified  # noqa: E402,F401
from test_network import admin, employer, login, net, student, ucsrf  # noqa: E402,F401


# ---------- log-in lockout ----------

def test_parallel_bad_logins_cant_race_past_the_lockout(client):
    """Slots are reserved when a request arrives, so a burst of simultaneous guesses still gets only 5 tries."""
    for i in range(20):
        make_verified(client, "student", f"p{i}@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)

    async def burst():
        transport = httpx.ASGITransport(app=client.appmod.app, client=("10.9.8.7", 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            return await asyncio.gather(*[ac.post("/login/student", data={"email": f"p{i}@fsu.edu", "password": "Wrong1!pass",
                                                                         "csrf": tok, "next": ""}) for i in range(20)])
    codes = [r.status_code for r in asyncio.run(burst())]
    assert codes.count(401) <= 5 and codes.count(429) >= 15


def test_someone_else_cant_lock_you_out_of_your_account(client, monkeypatch):
    """Failed guesses from an attacker's address don't block the owner logging in from theirs."""
    monkeypatch.setattr(client.security, "TRUST_PROXY", True)
    make_verified(client, "student", "victim@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)
    post = lambda ip, pw: client.post("/login/student", headers={"x-forwarded-for": ip},
                                      data={"email": "victim@fsu.edu", "password": pw, "csrf": tok, "next": ""})
    assert [post("203.0.113.9", "Wrong1!pass").status_code for _ in range(6)][-1] == 429
    assert post("198.51.100.4", PW).status_code == 303              # the owner, from their own address, gets in


def test_account_cap_across_many_addresses(client, monkeypatch):
    """Slow guessing spread over many addresses still stops at ACCOUNT_MAX_FAILS for that account."""
    monkeypatch.setattr(client.security, "TRUST_PROXY", True)
    make_verified(client, "student", "target@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)
    cap = client.security.ACCOUNT_MAX_FAILS
    codes = [client.post("/login/student", headers={"x-forwarded-for": f"192.0.2.{i}"},
                         data={"email": "target@fsu.edu", "password": "Wrong1!pass", "csrf": tok, "next": ""}).status_code
             for i in range(cap + 1)]
    assert codes[:cap] == [401] * cap and codes[cap] == 429
    # (the owner's own known browser still gets in: test_after_the_account_cap_only_the_owners_own_browser_gets_a_check)


def test_one_ip_reading_for_every_limit(client, monkeypatch):
    """Two X-Forwarded-For header lines: the guard and the app must agree on which address is the client."""
    monkeypatch.setattr(client.security, "TRUST_PROXY", True)
    from starlette.requests import Request
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"1.1.1.1"), (b"x-forwarded-for", b"2.2.2.2")], "client": ("9.9.9.9", 1)}
    assert client.security.client_ip(Request(scope)) == "2.2.2.2"


# ---------- parsers can't freeze the site ----------

def test_parsing_runs_in_a_killable_process():
    import sandbox
    t = time.time()
    with pytest.raises(sandbox.ParseTimeout):
        sandbox.run(time.sleep, 30, timeout=1)
    assert time.time() - t < 5
    assert sandbox.run(divmod, 7, 2) == (3, 1)
    with pytest.raises(ZeroDivisionError):
        sandbox.run(divmod, 1, 0)


def test_only_a_few_files_are_parsed_at_once(monkeypatch):
    import threading, sandbox
    monkeypatch.setattr(sandbox, "_slots", threading.BoundedSemaphore(1))
    sandbox._slots.acquire()                         # one parse already running
    try:
        t = time.time()
        with pytest.raises(sandbox.ParseBusy):
            sandbox.run(divmod, 7, 2)
        assert time.time() - t < 4                   # turned away quickly instead of queueing
    finally:
        sandbox._slots.release()
    assert sandbox.run(divmod, 7, 2) == (3, 1)


def _docx(xml: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
    return b.getvalue()


def test_word_file_with_unclosed_tags_reads_in_linear_time():
    import resume_engine
    t = time.time()
    resume_engine._docx_text(_docx("<w:p >" * 1_000_000))
    resume_engine._docx_text(_docx("<w:p><w:t>" * 300_000))
    assert time.time() - t < 5                       # the old regex took hours on the first one
    xml = ('<w:p><w:pPr><w:numPr>1</w:numPr></w:pPr><w:r><w:t>Led</w:t></w:r><w:r><w:t xml:space="preserve"> a team &amp; more</w:t>'
           '</w:r></w:p><w:p/><w:p w:x="1"><w:r><w:t>Two</w:t></w:r></w:p>')
    assert resume_engine._docx_text(_docx(xml)) == "• Led a team & more\n\nTwo"


def test_upload_parsing_goes_through_the_sandbox(monkeypatch):
    import resume_engine, sandbox
    def slow(*a, **k):
        raise sandbox.ParseTimeout("too slow")
    monkeypatch.setattr(sandbox, "run", slow)
    with pytest.raises(resume_engine.ResumeError, match="too long to read"):
        resume_engine.extract_text_safely("r.docx", _docx("<w:p><w:t>x</w:t></w:p>"))
    import msgcheck
    out = msgcheck.analyze_upload_safely(b"%PDF-1.4", "x.pdf", "application/pdf")
    assert out["kind"] == "unsupported" and "too long" in out["notes"][0]


# ---------- employer identity ----------

def _status(n, uid):
    with closing(sqlite3.connect(n.app.DB_PATH)) as db:
        return db.execute("SELECT company, status FROM employer_profiles WHERE user_id = ?", (uid,)).fetchone()


def test_renaming_an_approved_employer_sends_it_back_to_review(net):
    emp, uid = employer(net, company="SmallCo Analytics")
    assert _status(net, uid) == ("SmallCo Analytics", "approved")
    t = ucsrf(emp)
    about = "We build analytics dashboards for Florida city governments and hire FSU interns every summer."
    keep = {"csrf": t, "website": "acme.example", "industry": "Technology", "size": "11-50", "location": "Tallahassee, FL", "about": about}
    assert emp.post("/profile/setup/1", data={**keep, "company": "SmallCo Analytics", "tagline": "Data for cities"}).status_code == 303
    assert _status(net, uid) == ("SmallCo Analytics", "approved")          # other edits keep the approval
    assert emp.post("/profile/setup/1", data={**keep, "company": "Google"}).status_code == 303
    assert _status(net, uid) == ("Google", "pending")


def test_changing_an_approved_employers_website_sends_it_back_to_review(net):
    emp, uid = employer(net)
    about = "We build analytics dashboards for Florida city governments and hire FSU interns every summer."
    assert emp.post("/profile/setup/1", data={"csrf": ucsrf(emp), "company": "Acme Analytics", "website": "https://google.com",
                                              "industry": "Technology", "size": "11-50", "location": "Tallahassee, FL",
                                              "about": about}).status_code == 303
    assert _status(net, uid)[1] == "pending"


# ---------- smaller fixes ----------

def test_calendar_text_has_no_bare_carriage_returns():
    import scheduling
    out = scheduling._ics_text("Bring ID\rURL:https://evil.example\r\nThanks")
    assert "\r" not in out and "\n" not in out


def test_assistant_links_stay_on_this_site():
    import assistant
    assert 'href="/jobs"' in assistant.md("[Jobs](/jobs)")
    assert "href" not in assistant.md("[Click](//evil.example/x)")


def test_listing_edit_needs_the_signed_in_token(net):
    from test_network import add_job
    from test_listing_controls import _edit_data
    emp, eid = employer(net)
    jid = add_job(net, eid)
    import security
    shared = emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, csrf=security.make_csrf("form"), location="Remote"))
    assert "done=saved" not in shared.headers.get("location", "")          # the shared, anyone-can-fetch token is refused
    ok = emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, location="Remote"))
    assert ok.status_code == 303 and "done=saved" in ok.headers["location"]


def test_private_resume_text_isnt_searchable_in_talent(net):
    emp, _ = employer(net)
    stu, sid = student(net)
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE student_profiles SET share_resume = 0, resume_text = resume_text || ' secretphrase917' WHERE user_id = ?", (sid,))
        db.commit()
    assert "Jordan" not in emp.get("/talent?skill=secretphrase917").text
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE student_profiles SET share_resume = 1 WHERE user_id = ?", (sid,))
        db.commit()
    assert "Jordan" in emp.get("/talent?skill=secretphrase917").text


# ---------- client address behind Render / Cloudflare ----------

def test_render_uses_the_cloudflare_client_header(monkeypatch):
    import security
    monkeypatch.setattr(security, "TRUST_PROXY", True)
    monkeypatch.setattr(security, "CLIENT_IP_HEADERS", ["cf-connecting-ip", "true-client-ip"])
    h = {"cf-connecting-ip": "81.97.145.24", "x-forwarded-for": "81.97.145.24, 172.71.195.123, 10.226.90.65"}
    assert security.resolve_ip("10.0.0.1", lambda n: h.get(n, "")) == ("81.97.145.24", "cf-connecting-ip")
    h = {"true-client-ip": "2001:db8::7", "x-forwarded-for": "10.1.1.1"}
    assert security.resolve_ip("10.0.0.1", lambda n: h.get(n, ""))[0] == "2001:db8::7"
    h = {"cf-connecting-ip": "not-an-ip", "x-forwarded-for": "9.9.9.9"}
    assert security.resolve_ip("10.0.0.1", lambda n: h.get(n, ""))[0] == "9.9.9.9"     # junk header ignored
    monkeypatch.setattr(security, "TRUST_PROXY", False)
    assert security.resolve_ip("10.0.0.1", lambda n: h.get(n, "")) == ("10.0.0.1", "connection")


def test_proxy_hops_picks_the_right_forwarded_entry(monkeypatch):
    import security
    monkeypatch.setattr(security, "TRUST_PROXY", True)
    monkeypatch.setattr(security, "CLIENT_IP_HEADERS", [])
    monkeypatch.setattr(security, "PROXY_HOPS", 3)
    h = {"x-forwarded-for": "1.2.3.4, 81.97.145.24, 172.71.195.123, 10.226.90.65"}
    assert security.resolve_ip("p", lambda n: h.get(n, ""))[0] == "81.97.145.24"


def test_admin_can_see_which_address_the_limits_use(client):
    tok = csrf_from(client.get("/admin").text)
    assert client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": tok}).status_code == 303
    r = client.get("/admin/client-ip", headers={"cf-connecting-ip": "81.97.145.24"})
    assert r.status_code == 200 and "Address the limits use" in r.text and "81.97.145.24" in r.text
    client.cookies.clear()
    assert client.get("/admin/client-ip").status_code == 303


# ---------- known devices on a shared network ----------

def test_known_devices_dont_share_the_campus_lockout(client):
    """Five strangers' typos on the campus address lock out new browsers there, not students who've logged in before."""
    make_verified(client, "student", "regular@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)
    ok = client.post("/login/student", data={"email": "regular@fsu.edu", "password": PW, "csrf": tok, "next": ""})
    assert ok.status_code == 303 and "ncs_dev" in client.cookies
    known = client.cookies.get("ncs_dev")
    from fastapi.testclient import TestClient
    with TestClient(client.appmod.app, follow_redirects=False) as stranger:
        t2 = csrf_from(stranger.get("/login/student").text)
        codes = [stranger.post("/login/student", data={"email": f"x{i}@fsu.edu", "password": "Wrong1!pass", "csrf": t2,
                                                          "next": ""}).status_code for i in range(6)]
        assert codes[-1] == 429
    client.cookies.clear()
    client.cookies.set("ncs_dev", known)
    tok = csrf_from(client.get("/login/student").text)
    assert client.post("/login/student", data={"email": "regular@fsu.edu", "password": PW, "csrf": tok, "next": ""}).status_code == 303


def test_device_cookies_only_come_from_real_logins_and_cant_be_forged(client):
    tok = csrf_from(client.get("/login").text)
    client.post("/login", data={"email": "someone@fsu.edu", "csrf": tok})       # step one: no log-in happens
    assert "ncs_dev" not in client.cookies
    import security
    assert security.device_id("abcdefghijklmnop.1.0000") == ""
    good = security.new_device_cookie(7)
    assert security.device_id(good) != ""
    dev, uid, sig = good.split(".")
    assert security.device_id(f"{dev}.8.{sig}") == ""                # can't re-bind it to another account


def test_rotating_device_cookies_buys_no_extra_guesses_at_someone_elses_account(client):
    """An attacker logs into their own account over and over to collect device cookies, then uses each one to guess
    at a victim's password from the same address. The victim's account still only gets 5 tries per address."""
    make_verified(client, "employer", "attacker@evil.example")
    victim = make_verified(client, "student", "victim@fsu.edu")
    from fastapi.testclient import TestClient
    cookies = []
    for _ in range(4):
        with TestClient(client.appmod.app, follow_redirects=False) as c:
            t = csrf_from(c.get("/login/employer").text)
            assert c.post("/login/employer", data={"email": "attacker@evil.example", "password": PW, "csrf": t,
                                                   "next": ""}).status_code == 303
            cookies.append(c.cookies.get("ncs_dev"))
    assert len(set(cookies)) == 4
    codes = []
    for ck in cookies:
        with TestClient(client.appmod.app, follow_redirects=False) as c:
            c.cookies.set("ncs_dev", ck)
            t = csrf_from(c.get("/login/student").text)
            codes += [c.post("/login/student", data={"email": "victim@fsu.edu", "password": "Wrong1!pass", "csrf": t,
                                                     "next": ""}).status_code for _ in range(5)]
    assert codes.count(401) == 5                                     # the 6th onward never reaches a password check
    import security
    assert security.login_identity("1.2.3.4", cookies[0], victim) == "1.2.3.4"


def test_after_the_account_cap_only_the_owners_own_browser_gets_a_check(client, monkeypatch):
    """Guessing from many addresses fills the account cap. Then a stranger with the right password gets no answer
    (no oracle), while the owner's usual browser still logs in."""
    monkeypatch.setattr(client.security, "TRUST_PROXY", True)
    monkeypatch.setattr(client.security, "CLIENT_IP_HEADERS", [])
    make_verified(client, "student", "owner@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)
    post = lambda ip, pw: client.post("/login/student", headers={"x-forwarded-for": ip},
                                      data={"email": "owner@fsu.edu", "password": pw, "csrf": tok, "next": ""})
    assert post("198.51.100.1", PW).status_code == 303                 # the owner's browser earns its device cookie
    owned = client.cookies.get("ncs_dev")
    client.cookies.clear()
    tok = csrf_from(client.get("/login/student").text)
    cap = client.security.ACCOUNT_MAX_FAILS
    for i in range(cap):
        assert post(f"192.0.2.{i}", "Wrong1!pass").status_code == 401
    assert post("203.0.113.5", PW).status_code == 429                 # right password, unknown browser: no check
    client.cookies.set("ncs_dev", owned)
    tok = csrf_from(client.get("/login/student").text)
    assert post("198.51.100.1", PW).status_code == 303


def test_known_devices_on_one_address_have_a_shared_ceiling(client, monkeypatch):
    import security
    monkeypatch.setattr(security.login_shared_limiter, "max_attempts", 7)
    from fastapi.testclient import TestClient
    codes = []
    for d in range(3):
        with TestClient(client.appmod.app, follow_redirects=False) as c:
            c.cookies.set("ncs_dev", security.new_device_cookie(900 + d))
            t = csrf_from(c.get("/login/student").text)
            codes += [c.post("/login/student", data={"email": f"d{d}{i}@fsu.edu", "password": "Wrong1!pass", "csrf": t,
                                                      "next": ""}).status_code for i in range(3)]
    assert codes.count(401) == 7 and codes[-1] == 429


# ---------- shared limit store ----------

def test_sqlite_store_is_shared_between_processes(tmp_path):
    """Two stores on one file stand in for two worker processes: a limit used up in one holds in the other."""
    import security
    a, b = security._SqliteStore(str(tmp_path / "rl.db")), security._SqliteStore(str(tmp_path / "rl.db"))
    assert [a.take("login", "1.2.3.4", 5, 900)[0] for _ in range(3)] == [True] * 3
    assert [b.take("login", "1.2.3.4", 5, 900)[0] for _ in range(3)] == [True, True, False]
    b.refund("login", "1.2.3.4")
    assert a.take("login", "1.2.3.4", 5, 900)[0] is True
    assert a.take("other", "1.2.3.4", 5, 900)[0] is True           # limiters don't share counts
    ok, wait = a.take("login", "1.2.3.4", 5, 900)
    assert not ok and 0 < wait <= 901
    a.reset("login")
    assert b.take("login", "1.2.3.4", 5, 900)[0] is True


def test_sqlite_store_survives_a_broken_file(tmp_path):
    import security
    st = security._SqliteStore(str(tmp_path / "rl.db"))
    st._local.conn.close()
    st._local.conn = None
    st.path = str(tmp_path / "missing-dir" / "rl.db")              # can't be opened: falls back to memory
    assert st.take("x", "k", 1, 60) == (True, 0) and st.take("x", "k", 1, 60)[0] is False


def test_the_app_runs_on_the_sqlite_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORE", "sqlite")
    monkeypatch.setenv("RATE_LIMIT_DB", str(tmp_path / "rl.db"))
    from test_app import LOCAL_MODULES
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import security
    assert isinstance(security.STORE, security._SqliteStore)
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)


def test_the_full_login_lockout_on_the_sqlite_store(client, tmp_path, monkeypatch):
    monkeypatch.setattr(client.security, "STORE", client.security._SqliteStore(str(tmp_path / "rl.db")))
    make_verified(client, "student", "jane@fsu.edu")
    tok = csrf_from(client.get("/login/student").text)
    codes = [client.post("/login/student", data={"email": "jane@fsu.edu", "password": "Wrong1!pass", "csrf": tok,
                                                 "next": ""}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


# ---------- login CSRF ----------

def test_log_in_tokens_only_work_in_the_browser_they_were_issued_to(client):
    """Login CSRF: an attacker's own valid token can't be planted in a victim's browser."""
    make_verified(client, "student", "attacker@fsu.edu")
    attacker_tok = csrf_from(client.get("/login/student").text)
    from fastapi.testclient import TestClient
    with TestClient(client.appmod.app, follow_redirects=False) as victim:
        victim.get("/login/student")                                 # the victim has their own browser cookie
        r = victim.post("/login/student", data={"email": "attacker@fsu.edu", "password": PW, "csrf": attacker_tok, "next": ""})
        assert r.status_code == 400 and "usession" not in victim.cookies
        cold = TestClient(client.appmod.app, follow_redirects=False)  # and a browser with no cookie at all
        assert cold.post("/login/student", data={"email": "attacker@fsu.edu", "password": PW, "csrf": attacker_tok,
                                                 "next": ""}).status_code == 400
    assert client.post("/login/student", data={"email": "attacker@fsu.edu", "password": PW, "csrf": attacker_tok,
                                               "next": ""}).status_code == 303


def test_browsing_sets_no_cookies_but_forms_do(client):
    assert "set-cookie" not in client.get("/jobs").headers
    assert "set-cookie" not in client.get("/static/app.js").headers
    r = client.get("/login/student")
    assert "ncs_pre=" in r.headers.get("set-cookie", "") and "HttpOnly" in r.headers["set-cookie"]


# ---------- AI cost controls ----------

def test_ai_uses_the_fast_model_for_small_jobs_caches_instructions_and_logs_usage(tmp_path, monkeypatch):
    import json as _json, httpx, ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.delenv("AI_MODEL", raising=False); monkeypatch.delenv("AI_MODEL_FAST", raising=False)
    seen = []

    def handler(req):
        body = _json.loads(req.content); seen.append(body)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "relevance", "input": {"ok": True}}],
                                         "usage": {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 900}})
    monkeypatch.setattr(ai, "_transport", httpx.MockTransport(handler))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert ai.structured("Judge it.", "post text", "relevance", schema, tier="fast") == {"ok": True}
    ai.structured("Judge it.", "post text", "relevance", schema)
    assert seen[0]["model"].startswith("claude-haiku") and seen[1]["model"] == ai.model()
    assert seen[0]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert seen[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    rows = {(r["model"], r["feature"]): r for r in ai.usage_rows()}
    fast = rows[(seen[0]["model"], "relevance")]
    assert fast["requests"] == 1 and fast["input_tokens"] == 120 and fast["output_tokens"] == 30 and fast["cache_read"] == 900
    monkeypatch.setenv("AI_MODEL_FAST", "")
    assert ai.model("fast") == ai.model()                              # blank falls back to the main model


def test_admin_ai_usage_page(client):
    import ai
    ai._record_usage("claude-haiku-4-5-20251001", "relevance", {"input_tokens": 10, "output_tokens": 5})
    assert client.get("/admin/ai").status_code == 303
    tok = csrf_from(client.get("/admin").text)
    client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": tok})
    page = client.get("/admin/ai").text
    assert "AI usage" in page and "relevance" in page and "claude-haiku" in page
