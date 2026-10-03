"""Direct-employer posting, the poster on the listing, in-site emails and connections on profiles."""
import sqlite3
from contextlib import closing

from test_easy_network import apply_form, easy_job, two_students
from test_network import add_job, employer, net, student, ucsrf  # noqa: F401


def _post(emp, **kw):
    from test_app import csrf_from
    base = {"title": "Tutor", "company": "Acme Analytics", "category": "Other", "work_type": "remote", "location": "",
            "description": "Tutor FSU students in statistics twice a week. Paid $20/hour.", "apply_url": "", "contact": "",
            "csrf": csrf_from(emp.get("/post").text), "direct": "1"}
    base.update(kw)
    return emp.post("/post", data=base)


def test_only_the_hiring_company_can_post(net):
    emp, eid = employer(net)
    assert 'name="direct"' in emp.get("/post").text
    r = _post(emp, direct="")
    assert r.status_code == 400 and "work directly for this company" in r.text
    r = _post(emp, description="We are posting on behalf of our client, a Fortune 500 firm. Paid $20/hour.")
    assert r.status_code == 400 and "third-party" in r.text
    r = _post(emp, description="Our staffing agency places students in great roles. Paid $20/hour.")
    assert r.status_code == 400
    r = _post(emp, company="Globex Corporation")
    assert r.status_code == 400 and "your own organization" in r.text
    r = _post(emp, company="Acme Analytics, Inc.", poster_name="Dana Whitfield", poster_title="Campus Recruiter", show_email="1")
    assert r.status_code == 200
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        row = db.execute("SELECT poster_name, poster_title, show_email FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("Dana Whitfield", "Campus Recruiter", 1)


def test_poster_on_listing_email_optional_and_dm_after_applying(net):
    emp, eid = employer(net)
    s, sid = student(net)
    j = easy_job(net, eid, poster_name="Dana Whitfield", poster_title="Campus Recruiter", show_email=0)
    page = s.get(f"/job/{j}").text
    assert "Meet the poster" in page and "Dana Whitfield" in page and "Campus Recruiter at Acme Analytics" in page
    assert "recruiter@acme.example" not in page and "message Dana once you apply" in page
    assert "Quick apply makes job applications short and sweet. However, experts recommend applying directly on company websites." in page
    assert "Easy apply" not in page
    j2 = easy_job(net, eid, poster_name="Dana Whitfield", show_email=1, title="Social Intern")
    assert "mailto:recruiter@acme.example" in s.get(f"/job/{j2}").text
    t = ucsrf(s)
    r = s.post(f"/job/{j}/easy", data=apply_form(j, t))
    assert r.status_code in (200, 303)
    page = s.get(f"/job/{j}").text
    assert f"/messages/new?to={eid}&amp;job={j}" in page and "Message Dana" in page and "short and sweet" not in page


def test_employer_sees_which_requirements_each_applicant_meets(net):
    emp, eid = employer(net)
    s, sid = student(net)
    j = easy_job(net, eid, requirements=[{"kind": "skill", "label": "SQL", "must": True}, {"kind": "skill", "label": "Figma", "must": False}])
    t = ucsrf(s)
    s.post(f"/job/{j}/easy", data=apply_form(j, t))
    page = emp.get(f"/hiring/{j}?tab=candidates").text + emp.get(f"/hiring/{j}").text
    assert "of your requirements" in page and "Required" in page and "% match" in page


def test_emails_are_copied_into_the_site_without_sign_in_links(net):
    s, sid = student(net)
    import mailer
    mailer.send("jordan@fsu.edu", "Reset your NoleCareerShield password", "Choose a new password:\n\nhttp://x/reset?token=abc123\n\nBye")
    mailer.send("jordan@fsu.edu", "You have a new message on NoleCareerShield", "Someone wrote to you.")
    mailer.send("nobody@fsu.edu", "Hello", "not an account")
    page = s.get("/emails").text
    assert "You have a new message on NoleCareerShield" in page and "Reset your NoleCareerShield password" in page
    assert 'aria-label="2 unread emails"' in page
    import re
    eid = re.search(r'href="/emails\?id=(\d+)"', page).group(1)
    one = s.get(f"/emails?id={eid}").text
    assert "abc123" not in one
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 2
        assert "abc123" not in " ".join(r[0] for r in db.execute("SELECT body FROM emails"))
    assert "emails" in s.get("/profile/export").json()
    other, _ = student(net, "b@fsu.edu", "Blair B.")
    assert "Someone wrote to you" not in other.get(f"/emails?id={eid}").text


def test_connections_show_on_profile(net):
    a, aid, b, bid = two_students(net)
    assert "No connections yet" in a.get("/profile").text
    a.post("/network/connect", data={"csrf": ucsrf(a), "to": bid, "note": "", "next": "/network"})
    b.post("/network/respond", data={"csrf": ucsrf(b), "other": aid, "action": "accept", "next": "/network"})
    mine = a.get("/profile").text
    assert "Connections" in mine and "1 connection" in mine and f'href="/u/{bid}"' in mine and "Blair B." in mine
    c, cid = student(net, "c@fsu.edu", "Casey C.")
    theirs = c.get(f"/u/{aid}").text
    assert "1 connection" in theirs and "Blair B." in theirs
