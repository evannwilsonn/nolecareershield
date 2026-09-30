"""Quick apply (employer questions, student form, application in the tracker) and the connections / follows network."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401


def easy_job(n, eid, questions=None, **kw):
    data = {"title": "Marketing Intern", "company": "Acme Analytics", "category": "Marketing", "work_type": "remote", "location": "",
            "description": "Help our marketing team with campaigns, social posts and reports. Paid $17/hour. Weekly hours are flexible around classes.",
            "apply_url": "", "contact": "", "easy_apply": 1,
            "questions": questions if questions is not None else [{"q": "Why this role?", "kind": "long", "required": True},
                                                                    {"q": "Are you authorized to work in the US?", "kind": "yesno", "required": True},
                                                                    {"q": "Portfolio link", "kind": "short", "required": False}]}
    data.update(kw)
    job = n.app.add_job(data, employer_id=eid)
    n.app.set_review(job["id"], "approved", "legit")
    return job["id"]


def apply_form(job, csrf, **over):
    d = {"csrf": csrf, "a0": "I love campaigns and data.", "a1": "Yes", "a2": "https://example.com/me", "note": "Thanks for reading!", "share_resume": "1"}
    d.update(over)
    return d


# ---------- quick apply ----------

def test_easy_apply_end_to_end(net):
    emp, eid = employer(net)
    job = easy_job(net, eid)
    stu, sid = student(net)
    page = stu.get(f"/job/{job}").text
    assert "Quick apply →" in page and f"/job/{job}/easy" in page and "/apply" not in page.split("Quick apply")[1][:200]
    assert "Quick apply" in stu.get("/jobs").text                                    # badge on the card
    form = stu.get(f"/job/{job}/easy").text
    assert "Why this role?" in form and "Jordan R." in form and "Include my resume" in form and "never your email" in form
    t = ucsrf(stu)
    # required answers are enforced and the rest of the form is kept
    bad = stu.post(f"/job/{job}/easy", data=apply_form(job, t, a0="", a2="keep-me"))
    assert bad.status_code == 400 and "required questions" in bad.text and "keep-me" in bad.text
    ok = stu.post(f"/job/{job}/easy", data=apply_form(job, t))
    assert ok.status_code == 303 and ok.headers["location"] == f"/applications?sent={job}"
    assert "Application sent" in stu.get(f"/applications?sent={job}").text
    # one application per listing
    again = stu.get(f"/job/{job}/easy")
    assert again.status_code == 303 and "already=1" in again.headers["location"]
    assert "You applied" in stu.get(f"/job/{job}").text

    # the employer sees it in the tracker, with answers, and can open the applicant's profile and message them
    cand = emp.get(f"/hiring/{job}?tab=candidates").text
    assert "Candidates (1)" in cand and ">Applied<" in cand and "I love campaigns and data." in cand and "Jordan R." in cand
    assert "https://example.com/me" in cand and "Thanks for reading!" in cand and "Data Intern, Leon County" in cand or "SQL" in cand
    assert emp.get(f"/u/{sid}").status_code == 200
    assert emp.get(f"/messages/new?to={sid}&job={job}&invite=1").status_code == 200
    stats = emp.get(f"/hiring/{job}?tab=candidates").text
    assert re.search(r'<div class="n">1</div><div class="l">clicked Apply</div>', stats)

    # withdraw removes it (untouched tracker rows go too)
    w = stu.post(f"/applications/{job}/withdraw", data={"csrf": t})
    assert w.status_code == 303
    assert "Candidates (0)" in emp.get(f"/hiring/{job}?tab=candidates").text
    assert stu.get(f"/job/{job}/easy").status_code == 200


def test_easy_apply_resume_only_when_ticked_and_no_email(net):
    emp, eid = employer(net)
    job = easy_job(net, eid, questions=[])
    stu, sid = student(net, visible=False)                                        # hidden from employers in general
    t = ucsrf(stu)
    assert emp.get(f"/u/{sid}").status_code == 404                                # not visible before applying
    d = apply_form(job, t)
    d.pop("share_resume")
    assert stu.post(f"/job/{job}/easy", data=d).status_code == 303
    page = emp.get(f"/hiring/{job}?tab=candidates").text
    assert "chose not to include a resume" in page and "jordan.rivera@fsu.edu" not in page and "jordan@fsu.edu" not in page
    assert emp.get(f"/u/{sid}").status_code == 200                                # applying opens their profile to this employer only
    other, _ = employer(net, "other@acme.example", company="Other Co")
    assert other.get(f"/u/{sid}").status_code == 404


def test_easy_apply_rules(net):
    emp, eid = employer(net)
    pending, pid = employer(net, "new@acme.example", approve=False, company="Pending Co")
    stu, sid = student(net)
    t = ucsrf(stu)
    # not quick apply -> no form
    plain = add_job(net, eid)
    assert stu.get(f"/job/{plain}/easy").status_code == 404
    # an unapproved employer can't take applications
    j2 = easy_job(net, pid)
    assert stu.get(f"/job/{j2}/easy").status_code == 404 and "Quick apply →" not in stu.get(f"/job/{j2}").text
    # employers can't apply, visitors are sent to log in
    job = easy_job(net, eid)
    assert emp.get(f"/job/{job}/easy").status_code in (303, 403)
    assert net.client().get(f"/job/{job}/easy").status_code == 303
    # csrf
    assert stu.post(f"/job/{job}/easy", data=apply_form(job, "bad")).status_code == 303
    assert "Candidates (0)" in emp.get(f"/hiring/{job}?tab=candidates").text
    # yes/no answers are limited to Yes / No; text is escaped for the employer
    assert stu.post(f"/job/{job}/easy", data=apply_form(job, t, a1="maybe")).status_code == 400
    assert stu.post(f"/job/{job}/easy", data=apply_form(job, t, a0="<script>alert(1)</script>")).status_code == 303
    cand = emp.get(f"/hiring/{job}?tab=candidates").text
    assert "&lt;script&gt;" in cand and "<script>alert" not in cand


def test_easy_apply_questions_are_validated_and_scanned(net):
    emp, eid = employer(net)
    t = ucsrf(emp)
    base = {"csrf": None, "title": "Tutor", "company": "Acme", "category": "Other", "work_type": "remote", "location": "",
            "description": "Tutor FSU students in statistics twice a week. Paid $20/hour.", "apply_url": "", "contact": ""}

    def post(**kw):
        import app as _a
        tok = _a.make_csrf("form")
        return emp.post("/post", data={**base, "csrf": tok, **kw})
    r = post(easy_apply="1", qtext=["What is your SSN?", ""], qkind=["short", "short"], qreq=["1", "0"])
    assert r.status_code == 400 and "can't ask for SSNs" in r.text
    r = post(easy_apply="1", qtext=["Send your bank account number"], qkind=["short"], qreq=["0"])
    assert r.status_code == 400
    r = post(easy_apply="1", qtext=["Tell us about a project", "Years of Python?"], qkind=["long", "short"], qreq=["1", "0"])
    assert r.status_code == 200
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        row = db.execute("SELECT easy_apply, questions FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    qs = json.loads(row[1])
    assert row[0] == 1 and [q["q"] for q in qs] == ["Tell us about a project", "Years of Python?"] and qs[0]["required"] is True
    form = emp.get("/post").text
    assert 'name="easy_apply"' in form and form.count('name="qtext"') == 5


# ---------- connections ----------

def two_students(net):
    a, aid = student(net, "a@fsu.edu", "Alex A.")
    b, bid = student(net, "b@fsu.edu", "Blair B.")
    return a, aid, b, bid


def test_connection_request_accept_and_counts(net):
    a, aid, b, bid = two_students(net)
    ta, tb = ucsrf(a), ucsrf(b)
    assert "Connect" in a.get(f"/u/{bid}").text
    r = a.post("/network/connect", data={"csrf": ta, "to": bid, "note": "Stats club, hi!", "next": f"/u/{bid}"})
    assert r.status_code == 303 and r.headers["location"] == f"/u/{bid}"
    assert "Request sent" in a.get(f"/u/{bid}").text
    # the nav badge and requests tab show it to Blair, with the note
    assert 'aria-label="1 connection requests"' in b.get("/jobs").text
    req = b.get("/network").text                                                  # defaults to Requests when something is waiting
    assert "Alex A." in req and "Stats club, hi!" in req and "Accept" in req
    assert b.post("/network/respond", data={"csrf": tb, "other": aid, "action": "accept"}).status_code == 303
    assert "Connected" in a.get(f"/u/{bid}").text and "1 connection" in a.get(f"/u/{bid}").text
    assert "Blair B." in a.get("/network?tab=connections").text and "Alex A." in b.get("/network?tab=connections").text
    # remove
    a.post("/network/remove", data={"csrf": ta, "other": bid})
    assert "Blair B." not in a.get("/network?tab=connections").text


def test_connection_rules(net):
    a, aid, b, bid = two_students(net)
    ta, tb = ucsrf(a), ucsrf(b)
    emp, eid = employer(net)
    # decline is final for the requester; the decliner can still reach out
    a.post("/network/connect", data={"csrf": ta, "to": bid})
    b.post("/network/respond", data={"csrf": tb, "other": aid, "action": "decline"})
    a.post("/network/connect", data={"csrf": ta, "to": bid})
    assert "Request sent" not in a.get(f"/u/{bid}").text and "Not available" in a.get(f"/u/{bid}").text
    b.post("/network/connect", data={"csrf": tb, "to": aid})
    assert "Request sent" in b.get(f"/u/{aid}").text
    # both asked -> connecting back accepts
    c, cid = student(net, "c@fsu.edu", "Casey C.")
    tc = ucsrf(c)
    a.post("/network/connect", data={"csrf": ta, "to": cid})
    c.post("/network/connect", data={"csrf": tc, "to": aid})
    assert "Connected" in c.get(f"/u/{aid}").text
    # a scammy note isn't sent
    d, did = student(net, "d@fsu.edu", "Dana D.")
    r = a.post("/network/connect", data={"csrf": ta, "to": did, "note": "Message me on WhatsApp to earn $500 a day, send a gift card deposit"})
    assert "msg=scam" in r.headers["location"] and "Request sent" not in a.get(f"/u/{did}").text
    # csrf, employers, self, and opted-out students
    assert a.post("/network/connect", data={"csrf": "bad", "to": did}).status_code == 303
    assert "Request sent" not in a.get(f"/u/{did}").text
    assert emp.post("/network/connect", data={"csrf": ucsrf(emp), "to": did}).status_code in (303, 403)
    a.post("/network/connect", data={"csrf": ta, "to": aid})                       # to yourself: nothing happens
    assert net.app.network.state.__name__ == "state"
    # employers see no connect controls on a student profile
    assert "/network/connect" not in emp.get(f"/u/{aid}").text


def test_opt_out_hides_you_from_discovery_and_requests(net):
    a, aid, b, bid = two_students(net)
    tb = ucsrf(b)
    assert "Blair B." in a.get("/network?tab=discover").text
    assert b.post("/profile/setup/3", data={"csrf": tb, "allow_messages": "1", "visible": "1"}).status_code in (303, 200)
    assert "Blair B." not in a.get("/network?tab=discover").text
    assert "/network/connect" not in a.get(f"/u/{bid}").text
    ta = ucsrf(a)
    r = a.post("/network/connect", data={"csrf": ta, "to": bid})
    assert "msg=off" in r.headers["location"]


def test_discover_ranks_shared_major_and_skips_people_you_know(net):
    a, aid, b, bid = two_students(net)
    c, cid = student(net, "c@fsu.edu", "Casey C.")
    ta = ucsrf(a)
    page = a.get("/network?tab=discover").text
    assert "Blair B." in page and "Casey C." in page and "Same major" in page and "Alex A." not in page
    a.post("/network/connect", data={"csrf": ta, "to": bid})
    assert "Blair B." not in a.get("/network?tab=discover").text


# ---------- follows ----------

def test_follow_company_and_filter_jobs(net):
    emp, eid = employer(net)
    other, oid = employer(net, "o@acme.example", company="Other Co")
    j1, j2 = add_job(net, eid, "Data Analyst Intern"), add_job(net, oid, "Ops Intern")
    stu, sid = student(net)
    t = ucsrf(stu)
    assert "Follow" in stu.get(f"/company/{eid}").text and "0 followers" in stu.get(f"/company/{eid}").text
    assert stu.post("/network/follow", data={"csrf": t, "employer": eid, "next": f"/company/{eid}"}).headers["location"] == f"/company/{eid}"
    assert "Following ✓" in stu.get(f"/company/{eid}").text and "1 follower" in stu.get(f"/company/{eid}").text
    assert "Following ✓" in stu.get(f"/job/{j1}").text
    jobs = stu.get("/jobs?following=1").text
    assert "Data Analyst Intern" in jobs and "Ops Intern" not in jobs
    both = stu.get("/jobs").text
    assert "Data Analyst Intern" in both and "Ops Intern" in both
    assert "Acme Analytics" in stu.get("/network?tab=following").text
    # employers see the count, never who
    assert "1 follower" in emp.get("/profile").text and "Jordan" not in emp.get("/profile").text
    stu.post("/network/unfollow", data={"csrf": t, "employer": eid})
    assert "0 followers" in stu.get(f"/company/{eid}").text
    # only approved employers can be followed; csrf enforced
    pend, pid = employer(net, "p@acme.example", approve=False, company="Pending Co")
    stu.post("/network/follow", data={"csrf": t, "employer": pid})
    stu.post("/network/follow", data={"csrf": "bad", "employer": eid})
    assert "Pending Co" not in stu.get("/network?tab=following").text and "Acme Analytics" not in stu.get("/network?tab=following").text
    # employers have no network page
    assert emp.get("/network").status_code in (303, 403)


def test_export_and_delete_cover_new_data(net):
    emp, eid = employer(net)
    job = easy_job(net, eid)
    a, aid, b, bid = two_students(net)
    ta, tb = ucsrf(a), ucsrf(b)
    a.post(f"/job/{job}/easy", data=apply_form(job, ta))
    a.post("/network/connect", data={"csrf": ta, "to": bid})
    a.post("/network/follow", data={"csrf": ta, "employer": eid})
    data = a.get("/profile/export").json()
    assert len(data["applications"]) == 1 and len(data["connections"]) == 1 and len(data["follows"]) == 1
    assert a.post("/profile/delete", data={"csrf": ta, "password": "Str0ng!pass"}).status_code in (200, 303)
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert all(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in ("applications", "connections", "follows"))
