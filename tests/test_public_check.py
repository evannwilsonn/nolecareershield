"""The scam check is public, but visitors get the verdict and plain reasons only; FSU students get the full evidence."""
import re, sqlite3, sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from, make_verified, user_login  # noqa: E402,F401

SCAM = ("Congratulations! You have been pre-selected for a remote personal assistant position, $400 weekly. "
        "We will mail you a check to buy equipment from our vendor; deposit it and send the balance by Zelle. "
        "Text me on WhatsApp at 850-555-0142 and reply from your personal email.")


def _check(c, text=SCAM, sender="careers.fsu@gmail.com"):
    page = c.get("/check").text
    return c.post("/check", data={"csrf": csrf_from(page), "text": text, "sender": sender})


def test_visitors_get_the_verdict_not_the_evidence(client):
    r = _check(client)
    assert r.status_code == 200 and "Verdict" in r.text and "Scam" in r.text
    reasons = re.findall(r'<ul class="reasons">(.*?)</ul>', r.text, re.S)[0]
    assert reasons.count("<li>") <= 3 and "Found:" not in r.text and "strong signal" not in reasons
    assert "FSU students see" in r.text and "more signal" in r.text and 'href="/login"' in r.text
    assert "Want NoleCareerShield at your school?" in r.text


def test_students_get_the_full_breakdown(client):
    make_verified(client, "student", "jane@fsu.edu"); user_login(client, "student", "jane@fsu.edu")
    r = _check(client)
    reasons = re.findall(r'<ul class="reasons">(.*?)</ul>', r.text, re.S)[0]
    assert reasons.count("<li>") > 3 and "Found:" in r.text and "FSU students see" not in r.text
    assert "Want NoleCareerShield at your school?" not in r.text


def test_unapproved_employers_get_the_public_view(client):
    make_verified(client, "employer", "hr@newco.example"); user_login(client, "employer", "hr@newco.example")
    assert "FSU students see" in _check(client).text


def test_visitors_have_a_daily_limit(client):
    for _ in range(10):
        assert _check(client).status_code == 200
    r = _check(client)
    assert r.status_code == 429


def test_school_requests_keep_only_the_name(client):
    page = client.get("/check").text
    tok = csrf_from(page)
    r = client.post("/check/school", data={"csrf": tok, "school": "  University of   Florida "})
    assert r.status_code == 200 and "We'll count University of Florida" in r.text
    client.post("/check/school", data={"csrf": tok, "school": "university of florida"})
    client.post("/check/school", data={"csrf": tok, "school": "FAMU"})
    client.security.school_limiter.reset_all()
    for bad in ("x", "<script>", "http://spam.example", "12345", "me@uf.edu"):
        assert client.post("/check/school", data={"csrf": tok, "school": bad}).status_code == 400, bad
    assert client.post("/check/school", data={"csrf": tok, "school": "UCF"}).status_code == 429     # 5 a day per visitor
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        cols = [r[1] for r in db.execute("PRAGMA table_info(school_requests)")]
        assert cols == ["id", "school", "created_at"]
        assert db.execute("SELECT COUNT(*) FROM school_requests").fetchone()[0] == 3
    a = client
    a.cookies.clear()
    tok = csrf_from(a.get("/admin").text)
    a.post("/admin/login", data={"password": "correct-horse-battery", "csrf": tok})
    page = a.get("/admin/schools").text
    assert re.search(r"University of Florida</b></td><td>2<", page) and "FAMU" in page


SCAM_LISTING = {"title": "Remote Admin Assistant", "company": "QuickCash Staffing",
                "description": "Part-time remote assistant, $500 weekly, no experience needed. We will send you a check to buy office equipment "
                               "from our vendor. Deposit it and send the rest by Zelle.", "url": "", "contact": "quickcash.hiring@gmail.com"}
LEADGEN = {"title": "Sales Lead Specialist", "company": "JobMatch Network", "contact": "",
           "description": "Create a free profile to see the employer and apply to hundreds of similar openings. Sign up to unlock full job details. "
                          "Our partners will contact you about matching roles.", "url": "example.com/jobmatch/signup?ref=track123&utm_source=feed"}
REAL = {"title": "Data Analyst Intern", "company": "Garnet Analytics", "contact": "", "url": "https://garnetanalytics.example/careers",
        "description": "Summer internship building SQL dashboards for city clients. $18/hour, 20 hours a week, hybrid in Tallahassee. Apply on our careers page."}


def _listing(c, data):
    page = c.get("/check?kind=listing").text
    assert "Is this job listing a scam?" in page and 'href="/check?kind=listing"' in page and 'action="/check/listing"' in page
    return c.post("/check/listing", data={"csrf": csrf_from(page), **data})


def test_listing_check_for_visitors_and_students(client):
    r = _listing(client, SCAM_LISTING)
    assert r.status_code == 200 and "Scam. Stop here." in r.text and "Don&#x27;t apply, reply or send anything." in r.text.replace("'", "&#x27;")
    assert "FSU students see" in r.text and "Found:" not in r.text and "Want NoleCareerShield at your school?" in r.text
    assert 'value="Remote Admin Assistant"' in r.text                                 # the form keeps the listing for another try
    lg = _listing(client, LEADGEN)
    assert "Be careful" in lg.text and "aggregator or lead-generation ad" in lg.text
    ok = _listing(client, REAL)
    assert "No known scam signs" in ok.text and "careers page" in ok.text
    make_verified(client, "student", "jane@fsu.edu"); user_login(client, "student", "jane@fsu.edu")
    full = _listing(client, SCAM_LISTING)
    assert "Found:" in full.text and "FSU students see" not in full.text


def test_listing_check_validation_and_shared_limit(client):
    page = client.get("/check?kind=listing").text
    tok = csrf_from(page)
    assert client.post("/check/listing", data={"csrf": tok, "title": "", "description": "short"}).status_code == 400
    assert client.post("/check/listing", data={"csrf": tok, **REAL, "url": "not a link at all"}).status_code == 400
    assert client.post("/check/listing", data={"csrf": "x", **REAL}).status_code == 400
    client.security.public_check_limiter.reset_all()
    for _ in range(5):
        assert _listing(client, REAL).status_code == 200
    for _ in range(5):
        assert _check(client).status_code == 200
    assert _listing(client, REAL).status_code == 429                                  # 10 a day across messages and listings
