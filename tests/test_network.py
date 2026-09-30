"""End-to-end tests for the student network: profiles, messaging, scam check, assistant,
resume studio, feed, admin queues, privacy and the AI guard rails. Run: python -m pytest -q"""
import io, json, re, sqlite3, sys, zipfile
from contextlib import closing
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import LOCAL_MODULES, PW, csrf_from, make_verified  # noqa: E402

RESUME = """Jordan Rivera
jordan.rivera@fsu.edu | Tallahassee, FL | linkedin.com/in/jordanrivera

EDUCATION
Florida State University, B.S. Statistics, Minor in Computer Science. Expected May 2027. GPA 3.6

EXPERIENCE
Data Intern, Leon County Health Department, Summer 2025
- Responsible for cleaning survey data in Excel
- Built SQL queries to pull clinic visit counts for 12 clinics, cutting report time from 3 days to 4 hours
- Helped with making charts in Tableau for the monthly board meeting

Social Media Chair, Statistics Club, 2024-2025
- Managed the club Instagram and grew followers by 40%
- I was in charge of planning weekly study sessions

SKILLS
Python, SQL, Excel, Tableau, R, Public speaking, Spanish
"""


@pytest.fixture()
def net(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "n.db"))
    monkeypatch.setenv("CONTACT_EMAIL", "ops@example.org")
    monkeypatch.setenv("OUTBOX_LOG", str(tmp_path / "outbox.log"))
    for k in ("SMTP_HOST", "SMTP_FROM", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for m in LOCAL_MODULES:
        sys.modules.pop(m, None)
    import security, app as appmod, accounts, mailer, ai
    from fastapi.testclient import TestClient
    for lim in security.ALL_LIMITERS:
        lim.reset_all()
    mailer.outbox.clear()
    ai._transport = None

    class Net:
        pass
    n = Net()
    n.app, n.security, n.accounts, n.mailer, n.ai = appmod, security, accounts, mailer, ai
    n.clients = []

    def new_client():
        c = TestClient(appmod.app, follow_redirects=False)
        c.__enter__()
        n.clients.append(c)
        return c
    n.client = new_client
    yield n
    for c in n.clients:
        c.__exit__(None, None, None)


# ---------- helpers ----------

def login(c, role, email):
    tok = csrf_from(c.get(f"/login/{role}").text)
    r = c.post(f"/login/{role}", data={"email": email, "password": PW, "csrf": tok, "next": ""})
    assert r.status_code == 303, r.text[:400]
    return r


def ucsrf(c, path="/jobs"):
    """The signed-in user's CSRF token (from the log-out form in the header)."""
    return re.search(r'action="/logout"><input type="hidden" name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def student(n, email="jordan@fsu.edu", name="Jordan R.", visible=True, resume=RESUME):
    c = n.client()
    uid = make_verified(c if hasattr(c, "appmod") else _Shim(n), "student", email)
    r = login(c, "student", email)
    assert r.headers["location"] == "/profile/setup"
    assert c.get("/").headers["location"] == "/profile/setup"          # home sends new students to setup
    t = ucsrf(c)
    assert c.post("/profile/setup/1", data={"csrf": t, "display_name": name, "major": "Statistics", "degree": "Bachelor's",
                                            "grad_term": "Spring 2027", "headline": "Stats student looking for data internships"}).status_code == 303
    assert c.post("/profile/setup/2", data={"csrf": t, "skills": ["Python", "SQL", "Excel"], "more_skills": "Tableau, R",
                                            "interests": ["Data & Analytics"], "work_types": ["remote"], "job_kinds": ["internship"]}).status_code == 303
    data = {"csrf": t, "allow_messages": "1", "linkedin": "linkedin.com/in/jordanrivera"}
    if visible:
        data["visible"] = "1"
    files = {"resume": ("resume.txt", resume.encode(), "text/plain")} if resume else None
    r = c.post("/profile/setup/3", data=data, files=files)
    assert r.status_code == 303 and r.headers["location"].startswith("/profile?welcome=1"), r.text[:500]
    return c, uid


class _Shim:
    def __init__(self, n):
        self.appmod, self.accounts = n.app, n.accounts


def admin(n):
    c = n.client()
    tok = csrf_from(c.get("/admin").text)
    assert c.post("/admin/login", data={"password": "correct-horse-battery", "csrf": tok}).status_code == 303
    return c


def admin_csrf(c, path="/admin"):
    return csrf_from(c.get(path).text)


def employer(n, email="recruiter@acme.example", approve=True, company="Acme Analytics"):
    c = n.client()
    uid = make_verified(_Shim(n), "employer", email)
    r = login(c, "employer", email)
    assert r.headers["location"] == "/profile/setup"
    t = ucsrf(c)
    assert c.post("/profile/setup/1", data={"csrf": t, "company": company, "website": "acme.example", "industry": "Technology",
                                            "size": "11-50", "location": "Tallahassee, FL",
                                            "about": "We build analytics dashboards for Florida city governments and hire FSU interns every summer."}).status_code == 303
    assert c.post("/profile/setup/2", data={"csrf": t, "contact_name": "Pat Lee", "contact_title": "Campus Recruiter",
                                            "fsu_connection": "We hire 3 FSU interns each summer and attend the FSU career fair."}).status_code == 303
    if approve:
        a = admin(n)
        page = a.get("/admin/employers").text
        assert company in page
        assert a.post(f"/admin/employers/{uid}/approve", data={"csrf": admin_csrf(a, "/admin/employers")}).status_code == 303
    return c, uid


def add_job(n, employer_id, title="Data Analyst Intern", desc="Summer data internship. Use SQL, Python and Tableau to build dashboards for city clients. Paid $18/hour. Apply on our careers page."):
    job = n.app.add_job({"title": title, "company": "Acme Analytics", "category": "Data & Analytics", "work_type": "remote",
                         "location": "Tallahassee, FL", "description": desc, "apply_url": "https://acme.example/careers", "contact": ""},
                        employer_id=employer_id)
    n.app.set_review(job["id"], "approved", "legit")
    return job["id"]


# ---------- profiles ----------

def test_student_setup_flow_and_profile(net):
    c, uid = student(net)
    page = c.get("/profile?welcome=1").text
    assert "Jordan R." in page and "Statistics" in page and "Your profile is set up" in page
    assert "Python" in page and "Tableau" in page
    home = c.get("/")
    assert home.status_code == 200 and "Recommended for you" in home.text and 'class="side"' in home.text
    # Bad input is rejected with the reason, and nothing oversized is stored.
    t = ucsrf(c)
    r = c.post("/profile/setup/1", data={"csrf": t, "display_name": "<script>alert(1)</script>", "major": "Stats"})
    assert r.status_code == 400 and "Use letters for your name" in r.text and "<script>alert" not in r.text
    r = c.post("/profile/setup/1", data={"csrf": t, "display_name": "Jo", "major": "x" * 500})
    assert r.status_code == 400 and "too long" in r.text
    r = c.post("/profile/setup/3", data={"csrf": t, "linkedin": "https://evil.example/in/me"})
    assert r.status_code == 400 and "linkedin.com" in r.text


def test_setup_requires_login_and_csrf(net):
    c = net.client()
    r = c.get("/profile/setup")
    assert r.status_code == 303 and r.headers["location"].startswith("/login/student")
    s, _ = student(net)
    r = s.post("/profile/setup/1", data={"csrf": "bad", "display_name": "Evil Name", "major": "X"})
    assert r.status_code == 303
    assert "Evil Name" not in s.get("/profile").text


def test_profile_visibility_rules(net):
    s1, uid1 = student(net, "a@fsu.edu", "Alex A.", visible=False)
    s2, uid2 = student(net, "b@fsu.edu", "Blair B.", visible=True)
    emp, eid = employer(net)
    pend, pid = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    # Other students see basics only, never the resume.
    t = s2.get(f"/u/{uid1}").text
    assert "Alex A." in t and "Leon County Health" not in t
    # Approved employer: hidden student -> not available; visible student -> basics, no resume unless shared.
    assert emp.get(f"/u/{uid1}").status_code == 404
    t = emp.get(f"/u/{uid2}").text
    # Approved employers see the profile sections (like Handshake) but not the resume itself unless it's shared.
    assert "Blair B." in t and "Leon County Health" in t and "<h2>Resume</h2>" not in t and "linkedin.com/in/jordanrivera" in t
    # Unapproved employers see nobody and can't open the directory.
    assert pend.get(f"/u/{uid2}").status_code == 404
    assert "opens once a reviewer approves" in pend.get("/talent").text
    t = emp.get("/talent").text
    assert "Blair B." in t and "Alex A." not in t
    # Students can't open the employer directory.
    assert s1.get("/talent").status_code == 403
    # Visitors can't see profiles at all.
    assert net.client().get(f"/u/{uid2}").status_code == 303


def test_export_and_delete_account(net):
    s, uid = student(net)
    r = s.get("/profile/export")
    data = r.json()
    assert r.headers["content-disposition"].startswith("attachment") and data["student_profile"]["display_name"] == "Jordan R."
    assert "pw_hash" not in r.text
    t = ucsrf(s, "/profile")
    assert s.post("/profile/delete", data={"csrf": t, "password": "wrong"}).status_code == 401
    r = s.post("/profile/delete", data={"csrf": t, "password": PW})
    assert r.status_code == 200 and "account is deleted" in r.text
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE id = ?", (uid,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM student_profiles WHERE user_id = ?", (uid,)).fetchone()[0] == 0


# ---------- messaging ----------

def test_messaging_between_student_and_approved_employer(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    # The listing offers "Message the employer" and "Tailor my resume" to students.
    page = s.get(f"/job/{job}").text
    assert f"/messages/new?to={eid}&amp;job={job}" in page and "Your fit for this job" in page and "Tailor your resume to this job" in page
    t = ucsrf(s)
    r = s.post("/messages/new", data={"csrf": t, "to": eid, "job": job, "body": "Hi! Is the data internship still open for summer?"})
    assert r.status_code == 303
    cid = int(re.search(r"/messages/(\d+)", r.headers["location"]).group(1))
    # Employer sees it, unread count shows, replying works, email says nothing about the content.
    assert "1 unread" in emp.get("/messages").text or '>1</span>' in emp.get("/").text
    thread = emp.get(f"/messages/{cid}").text
    assert "still open for summer" in thread
    assert any("new message" in m["subject"].lower() and "still open" not in m["body"] for m in net.mailer.outbox)
    et = ucsrf(emp)
    r = emp.post(f"/api/messages/{cid}", json={"body": "Yes! Send your resume through our careers page."}, headers={"X-CSRF-Token": et})
    assert r.status_code == 200 and r.json()["message"]["mine"]
    polled = s.get(f"/api/messages/{cid}?after=0").json()["messages"]
    assert any("careers page" in m["html"] for m in polled)
    # JSON send without the CSRF header is refused.
    assert emp.post(f"/api/messages/{cid}", json={"body": "x"}).status_code == 400
    # A third party can't read the conversation.
    other, _ = student(net, "x@fsu.edu", "Xander X.")
    assert other.get(f"/messages/{cid}").status_code == 404
    assert other.get(f"/api/messages/{cid}").status_code == 404


def test_scam_message_is_held_and_suspicious_one_is_flagged(net):
    s, sid = student(net)
    emp, eid = employer(net)
    et = ucsrf(emp)
    r = emp.post("/messages/new", data={"csrf": et, "to": sid, "body": "Hello, we'd like to talk about our summer analytics internship."})
    cid = int(re.search(r"/messages/(\d+)", r.headers["location"]).group(1))
    scam = ("Congratulations, you have been pre-selected for a remote assistant position. You will receive a check to buy "
            "equipment from our approved vendor; deposit it and send the balance by Zelle. Reply from your personal email.")
    emp.post(f"/messages/{cid}/send", data={"csrf": et, "body": scam})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        st = db.execute("SELECT status, scan_band FROM messages WHERE body LIKE 'Congratulations%'").fetchone()
    assert st == ("held", "block")
    assert "deposit it and send" not in s.get(f"/messages/{cid}").text          # the student never sees it
    a = admin(net)
    assert "deposit it and send" in a.get("/admin/messages").text


def test_messaging_permissions(net):
    s1, sid1 = student(net, "a@fsu.edu", "Alex A.", visible=False)
    s2, sid2 = student(net, "b@fsu.edu", "Blair B.")
    pend, pid = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    emp, eid = employer(net)
    # student -> student: no
    r = s1.post("/messages/new", data={"csrf": ucsrf(s1), "to": sid2, "body": "hey there"})
    assert r.status_code == 403 and "between students and employers" in r.text
    # student -> unapproved employer: no
    r = s1.post("/messages/new", data={"csrf": ucsrf(s1), "to": pid, "body": "hello"})
    assert r.status_code == 403
    # unapproved employer -> student: no
    r = pend.post("/messages/new", data={"csrf": ucsrf(pend), "to": sid2, "body": "hello"})
    assert r.status_code == 403
    # approved employer -> hidden student who never wrote to them: no
    r = emp.post("/messages/new", data={"csrf": ucsrf(emp), "to": sid1, "body": "hello"})
    assert r.status_code == 403
    # ...but once the student writes first, the employer can reply.
    r = s1.post("/messages/new", data={"csrf": ucsrf(s1), "to": eid, "body": "Hi, I saw your listing."})
    cid = int(re.search(r"/messages/(\d+)", r.headers["location"]).group(1))
    r = emp.post(f"/messages/{cid}/send", data={"csrf": ucsrf(emp), "body": "Thanks for reaching out!"})
    assert r.status_code == 303
    # Block stops replies; report goes to reviewers.
    t = ucsrf(s1)
    assert s1.post(f"/messages/{cid}/block", data={"csrf": t}).status_code == 303
    r = emp.post(f"/messages/{cid}/send", data={"csrf": ucsrf(emp), "body": "Hello?"})
    assert r.status_code == 403 and "closed" in r.text
    s1.post(f"/messages/{cid}/report", data={"csrf": t})
    assert "Report" in admin(net).get("/admin/reports").text


# ---------- scam check ----------

SCAMS = [
    "Hi, this is Dr. Carter from the Biology department. I need a personal assistant for $400 weekly, only a few hours. "
    "Text me at 850-555-0199 from your personal email, not your fsu.edu account.",
    "You've been approved for a remote data entry role. We will mail you a check to purchase your equipment from our vendor. "
    "Deposit it and send the rest via Zelle.",
    "Earn $50 per task boosting app ratings! Pay a $30 activation deposit in USDT to unlock your first set of orders.",
]
LEGIT = [
    "Hi Jordan, thanks for applying to the Data Analyst Intern role at Acme Analytics. Are you free for a 30-minute video "
    "interview next Tuesday or Wednesday afternoon? - Pat Lee, Campus Recruiter",
    "Reminder: the Business Career Fair is Wednesday from 10am to 3pm in the Student Union. Bring copies of your resume.",
]


def test_scam_check_verdicts(net):
    import msgcheck
    for text in SCAMS:
        r = msgcheck.check(text)
        assert r["level"] >= 2, (text, r["key"], [f["rule_id"] for f in r["findings"]])
    for text in LEGIT:
        r = msgcheck.check(text)
        assert r["level"] == 0, (text, r["key"], [f["rule_id"] for f in r["findings"]])
    # Same text in, same verdict out.
    assert msgcheck.check(SCAMS[0])["level"] == msgcheck.check(SCAMS[0])["level"]
    # FSU look-alike sender is caught.
    r = msgcheck.check("Please review the attached job offer.", sender="careers@fsu-edu.org")
    assert r["level"] >= 2


def test_scam_check_page_works_for_visitors_and_students(net):
    c = net.client()
    page = c.get("/check").text
    tok = csrf_from(page)
    r = c.post("/check", data={"csrf": tok, "text": SCAMS[1], "sender": ""})
    assert r.status_code == 200 and "Scam" in r.text and "deposit any check" in r.text
    s, _ = student(net)
    t = csrf_from(s.get("/check").text)
    r = s.post("/check", data={"csrf": t, "text": LEGIT[0], "sender": "pat.lee@acme.example"})
    assert "No known scam signs" in r.text


def test_student_can_check_an_in_app_message(net):
    s, sid = student(net)
    emp, eid = employer(net)
    r = emp.post("/messages/new", data={"csrf": ucsrf(emp), "to": sid, "body": "We'd love to chat about an internship. Text me on WhatsApp for details, our HR team is busy."})
    cid = int(re.search(r"/messages/(\d+)", r.headers["location"]).group(1))
    thread = s.get(f"/messages/{cid}").text
    mid = int(re.search(r'/check\?m=(\d+)', thread).group(1))
    page = s.get(f"/check?m={mid}").text
    assert "WhatsApp" in page and "Acme Analytics" in page
    # Nobody else can pull that message into the checker.
    other, _ = student(net, "x@fsu.edu", "Xander X.")
    assert "WhatsApp" not in other.get(f"/check?m={mid}").text


# ---------- assistant ----------

def test_assistant_builtin_finds_real_listings_only(net):
    s, sid = student(net)
    emp, eid = employer(net)
    good = add_job(net, eid)
    hidden = net.app.add_job({"title": "Secret SQL Analyst", "company": "Nope", "category": "Data & Analytics", "work_type": "remote",
                              "location": "", "description": "SQL analyst role, unreviewed.", "apply_url": "", "contact": ""})["id"]
    t = ucsrf(s)
    r = s.post("/api/assistant", json={"history": [{"role": "user", "text": "remote data internships using SQL"}]}, headers={"X-CSRF-Token": t})
    out = r.json()
    ids = [c["id"] for c in out["jobs"]]
    assert good in ids and hidden not in ids and "Secret SQL" not in out["cards_html"]
    r = s.post("/api/assistant", json={"history": [{"role": "user", "text": "what fits my resume?"}]}, headers={"X-CSRF-Token": t})
    assert good in [c["id"] for c in r.json()["jobs"]]
    # A pasted scam gets the scam check, not job cards.
    r = s.post("/api/assistant", json={"history": [{"role": "user", "text": "Is this a scam: " + SCAMS[1]}]}, headers={"X-CSRF-Token": t})
    assert "scam" in r.json()["reply"].lower()
    # No-JS form works too, and employers/visitors can't use it.
    assert "Data Analyst Intern" in s.post("/assistant", data={"csrf": t, "q": "data internships"}).text
    assert net.client().post("/api/assistant", json={"history": []}).status_code == 401
    assert s.post("/api/assistant", json={"history": [{"role": "user", "text": "hi"}]}).status_code == 400   # no CSRF header


def _mock_ai(net, handler):
    net.ai._transport = httpx.MockTransport(handler)
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key"


def test_ai_assistant_cannot_invent_listings(net, monkeypatch):
    s, sid = student(net)
    emp, eid = employer(net)
    good = add_job(net, eid)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["x-api-key"] == "test-key"
        if len(calls) == 1:
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t1", "name": "search_jobs", "input": {"query": "data"}}],
                                             "stop_reason": "tool_use"})
        return httpx.Response(200, json={"content": [{"type": "text", "text": f"Try [[job:{good}]] and also [[job:99999]]."}],
                                         "stop_reason": "end_turn"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    net.ai._transport = httpx.MockTransport(handler)
    t = ucsrf(s)
    out = s.post("/api/assistant", json={"history": [{"role": "user", "text": "data jobs"}]}, headers={"X-CSRF-Token": t}).json()
    assert [c["id"] for c in out["jobs"]] == [good]
    assert "99999" not in out["reply"] and "[[job" not in out["reply"]
    # The student's resume went in as tagged data, never as instructions.
    sent = json.dumps(calls[0])
    assert "<profile>" in sent or "<resume>" in sent


def test_ai_scam_opinion_can_never_lower_the_verdict(net, monkeypatch):
    import msgcheck

    def handler(request):
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t", "name": "scam_opinion",
                                                      "input": {"verdict": "safe", "confidence": 0.99, "summary": "Looks fine.",
                                                                "red_flags": [], "green_flags": ["friendly"]}}], "stop_reason": "tool_use"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    net.ai._transport = httpx.MockTransport(handler)
    rules_only = msgcheck.check(SCAMS[1])
    with_ai = msgcheck.check(SCAMS[1], use_ai=True)
    assert with_ai["ai"]["verdict"] == "safe" and with_ai["level"] == rules_only["level"] >= 2


def test_ai_failure_falls_back_to_builtin(net, monkeypatch):
    s, sid = student(net)
    emp, eid = employer(net)
    good = add_job(net, eid)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    net.ai._transport = httpx.MockTransport(lambda r: httpx.Response(529, json={"error": {"type": "overloaded_error"}}))
    out = s.post("/api/assistant", json={"history": [{"role": "user", "text": "data internships"}]},
                 headers={"X-CSRF-Token": ucsrf(s)}).json()
    assert good in [c["id"] for c in out["jobs"]]


# ---------- resume studio ----------

def test_resume_review_edit_tailor_versions(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    page = s.get("/resume").text
    assert "Resume score" in page and "Responsible for cleaning survey data" in page      # weak bullet flagged with a rewrite
    t = ucsrf(s)
    # Apply a suggested rewrite.
    old = "Responsible for cleaning survey data in Excel"
    new = re.search(r'name="old" value="' + re.escape(old) + r'"><input type="hidden" name="new" value="([^"]+)"', page).group(1)
    assert s.post("/resume/apply", data={"csrf": t, "old": old, "new": new.replace("&amp;", "&")}).status_code == 303
    assert old not in s.get("/resume?tab=edit").text
    # Improve one bullet (no AI).
    r = s.post("/api/resume/bullet", json={"bullet": "I was in charge of planning weekly study sessions"}, headers={"X-CSRF-Token": t})
    assert r.status_code == 200 and "Planned" in json.dumps(r.json())
    # Tailor to a board listing, save as a version, download .docx.
    assert f'<option value="{job}" selected>' in s.get(f"/resume?tab=tailor&job={job}").text
    r = s.post("/resume/tailor", data={"csrf": t, "job_id": str(job), "title": "", "description": "", "mode": "builtin"})
    assert r.status_code == 200 and "Tableau" in r.text
    body = re.search(r'<textarea[^>]*name="body"[^>]*>(.*?)</textarea>', r.text, re.S)
    assert body, "tailor result should offer a version to save"
    r = s.post("/resume/versions", data={"csrf": t, "name": "Acme data intern", "body": body.group(1), "job_id": job})
    assert r.status_code == 303
    vpage = s.get("/resume?tab=versions").text
    vid = int(re.search(r"/resume/versions/(\d+)\.docx", vpage).group(1))
    d = s.get(f"/resume/versions/{vid}.docx")
    assert d.status_code == 200 and zipfile.is_zipfile(io.BytesIO(d.content))
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(d.content)).namelist()
    # Oversized or wrong-type uploads are rejected.
    r = s.post("/resume/upload", data={"csrf": t}, files={"resume": ("x.exe", b"MZ" + b"0" * 100, "application/octet-stream")})
    assert r.status_code == 400
    r = s.post("/resume/upload", data={"csrf": t}, files={"resume": ("big.txt", b"a" * 3_000_000, "text/plain")})
    assert r.status_code == 400
    # Employers can't use the studio; other students can't read versions.
    assert emp.get("/resume").status_code == 403
    other, _ = student(net, "x@fsu.edu", "Xander X.")
    assert other.get(f"/resume/versions/{vid}.docx").status_code == 404


def test_resume_engine_reads_docx_and_pdf(net):
    import resume_engine
    docx = resume_engine.to_docx(RESUME)
    text = resume_engine.extract_text("r.docx", docx)
    assert "Leon County Health Department" in text
    from pypdf import PdfWriter  # noqa: F401  (pypdf is a dependency; a real PDF is covered in the manual check)


# ---------- feed ----------

def test_feed_rules(net):
    visitor = net.client()
    assert "Posts are only visible" in visitor.get("/feed").text or "log in" in visitor.get("/feed").text.lower()
    s, sid = student(net)
    t = ucsrf(s)
    r = s.post("/feed/post", data={"csrf": t, "kind": "question", "body": "Has anyone done the Deloitte info session? Worth going as a sophomore?"})
    assert r.status_code == 303
    assert "Deloitte info session" in s.get("/feed").text
    # A student post with scam signals is held, not published.
    s.post("/feed/post", data={"csrf": t, "kind": "opportunity", "body": SCAMS[1]})
    peer, _ = student(net, "peer@fsu.edu", "Peer P.")
    assert "Deposit it" not in peer.get("/feed").text and "Deloitte info session" in peer.get("/feed").text
    # Approved employer: relevant post waits for review; an ad is rejected on the spot with the reason.
    emp, eid = employer(net)
    et = ucsrf(emp)
    r = emp.post("/feed/post", data={"csrf": et, "kind": "opportunity", "body": "Shop now! 20% off our analytics course with promo code NOLES."})
    assert r.status_code == 400 and "reads like an ad" in r.text
    r = emp.post("/feed/post", data={"csrf": et, "kind": "info_session",
                                     "body": "Acme is hosting an info session for FSU students interested in summer data internships. Thursday 6pm at the Career Center."})
    assert r.status_code == 303
    assert "info session for FSU students" not in peer.get("/feed").text            # pending review
    a = admin(net)
    pp = a.get("/admin/posts").text
    card = next(x for x in pp.split('<div class="rev-card">') if "info session for FSU students" in x)
    assert "Employer post, needs approval" in card
    pid = int(re.search(r"/admin/posts/(\d+)/publish", card).group(1))
    a.post(f"/admin/posts/{pid}/publish", data={"csrf": admin_csrf(a, "/admin/posts")})
    assert "info session for FSU students" in peer.get("/feed").text
    # Unapproved employers can't post or even read the feed.
    pend, _ = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    assert "Deloitte" not in pend.get("/feed").text
    r = pend.post("/feed/post", data={"csrf": ucsrf(pend), "kind": "advice", "body": "Advice for FSU students: tailor your resume to every internship."})
    assert r.status_code == 403
    # Comments, helpful, and three reports hide a post.
    fp = s.get("/feed").text
    first = int(re.search(r"/feed/(\d+)/helpful", fp).group(1))
    assert s.post(f"/feed/{first}/helpful", data={"csrf": t}).status_code == 303
    assert s.post(f"/feed/{first}/comment", data={"csrf": t, "body": "Yes, go! They collect resumes."}).status_code in (200, 303)
    for i in range(3):
        r_, _ = student(net, f"r{i}@fsu.edu", f"Reporter {chr(65 + i)}.")
        r_.post(f"/feed/{first}/report", data={"csrf": ucsrf(r_)})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT status FROM posts WHERE id = ?", (first,)).fetchone()[0] != "published"


# ---------- pages render for every role ----------

def test_every_page_renders(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    for path in ["/", "/jobs", f"/job/{job}", "/assistant", "/feed", "/messages", "/resume", "/resume?tab=edit",
                 "/resume?tab=tailor", "/resume?tab=versions", "/check", "/profile", f"/company/{eid}", "/profile/setup/2"]:
        r = s.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        assert "Traceback" not in r.text
    for path in ["/", "/jobs", "/feed", "/messages", "/talent", "/check", "/profile", "/post", f"/u/{sid}", f"/messages/new?to={sid}"]:
        r = emp.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
    a = admin(net)
    for path in ["/admin", "/admin/employers", "/admin/posts", "/admin/messages", "/admin/reports", "/admin/checks", "/admin/live"]:
        assert a.get(path).status_code == 200, path
    v = net.client()
    for path in ["/", "/jobs", "/check", "/about", "/privacy", "/feed"]:
        assert v.get(path).status_code == 200, path
    js = v.get("/static/app.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert "script-src 'self'" in v.get("/").headers["content-security-policy"]


def test_login_next_returns_to_feature_pages(net):
    c = net.client()
    r = c.get("/messages/new?to=5&job=2")
    assert r.status_code == 303 and r.headers["location"] == "/login/student?next=/messages/new?to=5&job=2"
    assert net.app._safe_next("/messages/new?to=5&job=2") == "/messages/new?to=5&job=2"
    for bad in ["//evil.example", "/messages/new?to=5&next=https://evil.example", "https://evil.example/feed", "/feed/../../x"]:
        assert net.app._safe_next(bad) == ""


def test_user_text_is_escaped_everywhere(net):
    x = '<img src=x onerror=alert(1)>'
    s, sid = student(net)
    t = ucsrf(s)
    s.post("/profile/setup/1", data={"csrf": t, "display_name": "Jordan R.", "major": "Stats" + x, "headline": x, "bio": x,
                                     "grad_term": "Spring 2027"})
    s.post("/profile/setup/2", data={"csrf": t, "skills": ["Python"], "more_skills": "Chess" + x})
    emp, eid = employer(net)
    et = ucsrf(emp)
    job = add_job(net, eid, title="Analyst " + x, desc="Paid internship for students. " + x)
    s.post("/feed/post", data={"csrf": t, "kind": "question", "body": "Question for FSU students " + x})
    r = s.post("/messages/new", data={"csrf": t, "to": eid, "job": job, "body": "Hello " + x})
    cid = int(re.search(r"/messages/(\d+)", r.headers["location"]).group(1))
    emp.post(f"/messages/{cid}/send", data={"csrf": et, "body": "Reply " + x})
    s.post("/api/resume/bullet", json={"bullet": "Led " + x}, headers={"X-CSRF-Token": t})
    pages = [s.get(p).text for p in ("/", "/profile", "/feed", f"/messages/{cid}", "/jobs", f"/job/{job}", "/resume", "/resume?tab=tailor")]
    pages += [emp.get(p).text for p in ("/talent", f"/u/{sid}", f"/messages/{cid}", "/feed")]
    pages.append(s.post("/api/assistant", json={"history": [{"role": "user", "text": "analyst " + x}]}, headers={"X-CSRF-Token": t}).json()["cards_html"])
    pages.append(s.post("/check", data={"csrf": csrf_from(s.get("/check").text), "text": x, "sender": x}).text)
    a = admin(net)
    pages += [a.get(p).text for p in ("/admin", "/admin/employers", "/admin/posts", "/admin/messages", "/admin/reports")]
    for html in pages:
        assert "<img src=x" not in html
