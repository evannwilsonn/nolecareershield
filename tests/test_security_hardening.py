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
    # ...but the owner, with the right password from an address of their own, still gets in.
    owner = client.post("/login/student", headers={"x-forwarded-for": "198.51.100.77"},
                        data={"email": "target@fsu.edu", "password": PW, "csrf": tok, "next": ""})
    assert owner.status_code == 303


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
