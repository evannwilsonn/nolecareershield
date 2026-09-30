"""Listing controls: pause / resume / close / duplicate / edit / expiry, the one visibility rule
(store.live_where / store.visible_listing) everywhere listings are shown, and expiry reminders."""
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, admin, admin_csrf, employer, net, student, ucsrf  # noqa: E402,F401
from test_easy_network import apply_form, easy_job  # noqa: E402


def _db(n):
    return closing(sqlite3.connect(n.app.DB_PATH))


def _job(n, jid):
    return n.app.get_job(jid)


def _on_board(stu, jid):
    return f'href="/job/{jid}"' in stu.get("/jobs").text and stu.get(f"/job/{jid}").status_code == 200


def test_approval_sets_expiry_and_helper_agrees(net):
    emp, eid = employer(net)
    jid = add_job(net, eid)
    j = _job(net, jid)
    assert j["listing_status"] == "open" and abs(j["expires_at"] - (time.time() + 60 * 86400)) < 120
    import store
    assert store.visible_listing(j) and store.listing_state(j) == "live"
    for patch, state in (({"listing_status": "paused"}, "paused"), ({"listing_status": "closed"}, "closed"),
                         ({"expires_at": time.time() - 5}, "expired"), ({"review_status": "pending"}, "pending")):
        assert store.listing_state(dict(j, **patch)) == state and not store.visible_listing(dict(j, **patch))
    # the SQL twin says the same thing
    with store.db() as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {store.live_where()}").fetchone()[0] == 1


def test_pause_resume_close_hide_listing_everywhere_and_keep_applicants(net):
    emp, eid = employer(net)
    jid = easy_job(net, eid)
    stu, sid = student(net)
    assert stu.post(f"/job/{jid}/easy", data=apply_form(jid, ucsrf(stu))).status_code == 303
    t = ucsrf(emp)
    over = emp.get("/hiring").text
    assert f'action="/hiring/{jid}/status"' in over and ">Pause<" in over and ">Duplicate<" in over and "Ends " in over
    assert _on_board(stu, jid) and f'/job/{jid}"' in stu.get(f"/company/{eid}").text

    r = emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "pause", "back": "list"})
    assert r.headers["location"] == "/hiring?done=paused"
    assert ">Paused<" in emp.get("/hiring").text and ">Resume<" in emp.get("/hiring").text
    assert not _on_board(stu, jid)
    assert stu.get(f"/job/{jid}/easy").status_code == 404                                # can't apply to a paused listing
    assert net.app.public_count() == 0
    # the assistant, company page and apply link don't show it either
    assert stu.get(f"/job/{jid}/apply", follow_redirects=False).headers["location"] == f"/job/{jid}"
    co = stu.get(f"/company/{eid}")
    assert co.status_code == 200 and f'/job/{jid}"' not in co.text
    import store
    with store.db() as conn:
        assert all(j["id"] != jid for j in store.live_jobs(conn))                           # what the assistant and resume tools use
    # applicants stay; the student's application says it's paused
    assert "Candidates (1)" in emp.get(f"/hiring/{jid}?tab=candidates").text
    assert "Paused" in stu.get("/applications").text

    r = emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "resume"})
    assert r.headers["location"] == f"/hiring/{jid}?done=resumed" and _on_board(stu, jid)
    emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "close"})
    assert not _on_board(stu, jid) and _job(net, jid)["listing_status"] == "closed"
    apps = stu.get("/applications").text
    assert "Closed" in apps and "closed this listing" in apps
    page = emp.get(f"/hiring/{jid}").text
    assert ">Closed<" in page and ">Resume<" not in page and ">Pause<" not in page        # closed is final; duplicate to repost
    # a closed listing can't be resumed by posting the form anyway
    emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "resume"})
    assert _job(net, jid)["listing_status"] == "closed"
    # another employer and bad CSRF change nothing
    other, _ = employer(net, "hr@beta.example", company="Beta Co")
    jid2 = add_job(net, eid, title="Research Assistant")
    other.post(f"/hiring/{jid2}/status", data={"csrf": ucsrf(other), "do": "pause"})
    emp.post(f"/hiring/{jid2}/status", data={"csrf": "bad", "do": "pause"})
    assert _job(net, jid2)["listing_status"] == "open"


def test_expiry_drops_off_board_extend_and_date(net):
    emp, eid = employer(net)
    jid = add_job(net, eid)
    stu, _ = student(net)
    t = ucsrf(emp)
    with _db(net) as db:
        db.execute("UPDATE jobs SET expires_at = ? WHERE id = ?", (time.time() - 60, jid))
        db.commit()
    assert not _on_board(stu, jid)
    over = emp.get("/hiring").text
    assert ">Expired<" in over and "Extend 30 days" in over
    r = emp.post(f"/hiring/{jid}/expiry", data={"csrf": t, "days": "30", "back": "list"})
    assert r.headers["location"] == "/hiring?done=extended" and _on_board(stu, jid)
    assert abs(_job(net, jid)["expires_at"] - (time.time() + 30 * 86400)) < 120
    # out-of-range choices are refused
    for bad in ("3", "121", "abc"):
        r = emp.post(f"/hiring/{jid}/expiry", data={"csrf": t, "days": bad})
        assert r.headers["location"].endswith("done=badexpiry")
    # an end date between 7 and 120 days out
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 20 * 86400))
    emp.post(f"/hiring/{jid}/expiry", data={"csrf": t, "days": "30", "date": day})
    assert time.strftime("%Y-%m-%d", time.gmtime(_job(net, jid)["expires_at"])) == day
    far = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 200 * 86400))
    assert emp.post(f"/hiring/{jid}/expiry", data={"csrf": t, "date": far}).headers["location"].endswith("done=badexpiry")
    # the post form lets employers choose 7-120 days up front; it's used when the reviewer approves
    form = emp.get("/post").text
    assert 'name="expiry_days"' in form and '<option value="120">' in form and '<option value="7">' in form
    new = net.app.add_job({"title": "Lab Assistant", "company": "Acme Analytics", "category": "Other", "work_type": "on-site",
                           "location": "Tallahassee, FL", "description": "Help run the lab front desk and log samples. Paid $15/hour.",
                           "apply_url": "https://acme.example/careers", "contact": "", "expiry_days": 14}, employer_id=eid)["id"]
    assert "Runs 14 days once approved" in emp.get("/hiring").text
    net.app.set_review(new, "approved", "legit")
    assert abs(_job(net, new)["expires_at"] - (time.time() + 14 * 86400)) < 120


def test_expiry_reminder_is_sent_once_and_lands_in_emails(net):
    emp, eid = employer(net)
    jid = add_job(net, eid)
    net.mailer.outbox.clear()
    assert net.app.send_expiry_reminders() == 0                                           # 60 days out: nothing yet
    with _db(net) as db:
        db.execute("UPDATE jobs SET expires_at = ? WHERE id = ?", (time.time() + 4 * 86400, jid))
        db.commit()
    assert net.app.send_expiry_reminders() == 1
    assert net.app.send_expiry_reminders() == 0                                           # idempotent
    net.app.daily_maintenance()                                                           # the daily hook runs it too
    sent = [m for m in net.mailer.outbox if "ends in" in str(m)]
    assert len(sent) == 1 and "Data Analyst Intern" in str(sent[0]) and f"/hiring/{jid}" in str(sent[0])
    assert "ends in 4 days" in emp.get("/emails").text                                     # in-site copy
    # extending re-arms it; a paused or closed listing gets no reminder
    t = ucsrf(emp)
    emp.post(f"/hiring/{jid}/expiry", data={"csrf": t, "days": "7"})
    with _db(net) as db:
        db.execute("UPDATE jobs SET expires_at = ? WHERE id = ?", (time.time() + 3 * 86400, jid))
        db.commit()
    emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "pause"})
    assert net.app.send_expiry_reminders() == 0
    emp.post(f"/hiring/{jid}/status", data={"csrf": t, "do": "resume"})
    assert net.app.send_expiry_reminders() == 1


def test_duplicate_goes_through_scan_and_review(net):
    emp, eid = employer(net)
    jid = easy_job(net, eid, requirements=[{"kind": "skill", "label": "Excel", "must": True}], poster_name="Dana Whitfield",
                   poster_title="Campus Recruiter", show_email=1)
    t = ucsrf(emp)
    r = emp.post(f"/hiring/{jid}/duplicate", data={"csrf": t})
    new = int(re.search(r"/hiring/(\d+)\?done=copied", r.headers["location"]).group(1))
    a, b = _job(net, jid), _job(net, new)
    assert new != jid and b["review_status"] == "pending" and b["expires_at"] is None
    for k in ("title", "description", "questions", "requirements", "poster_name", "poster_title", "show_email", "easy_apply"):
        assert a[k] == b[k], k
    assert b["findings_json"] is not None and b["score"] is not None                         # scanned
    assert "Copied" in emp.get(r.headers["location"]).text
    adm = admin(net)
    assert "Marketing Intern" in adm.get("/admin").text                                     # waits for a reviewer
    # bad CSRF or someone else's listing: nothing copied
    other, _ = employer(net, "hr@beta.example", company="Beta Co")
    other.post(f"/hiring/{jid}/duplicate", data={"csrf": ucsrf(other)})
    emp.post(f"/hiring/{jid}/duplicate", data={"csrf": "bad"})
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def _edit_data(emp, jid, **over):
    form = emp.get(f"/hiring/{jid}/edit").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', form.split('action="/hiring/')[1]).group(1)
    grab = lambda name: re.search(rf'name="{name}"[^>]*value="([^"]*)"', form)          # noqa: E731
    desc = re.search(r'<textarea id="f-description" name="description"[^>]*>(.*?)</textarea>', form, re.S).group(1)
    d = {"csrf": csrf, "title": grab("title").group(1), "company": grab("company").group(1), "category": "Data & Analytics", "work_type": "remote",
         "location": "Tallahassee, FL", "description": desc.replace("&#x27;", "'").replace("&amp;", "&"), "apply_url": grab("apply_url").group(1),
         "contact": "", "poster_name": "Pat Lee", "poster_title": "Campus Recruiter", "direct": "1"}
    d.update(over)
    return d


def test_edit_minor_fields_stay_live_major_changes_go_back_to_review(net):
    emp, eid = employer(net)
    jid = add_job(net, eid)
    stu, _ = student(net)
    form = emp.get(f"/hiring/{jid}/edit")
    assert form.status_code == 200 and "Edit listing" in form.text and "Data Analyst Intern" in form.text
    assert 'action="/hiring/%d/edit"' % jid in form.text and 'name="expiry_days"' not in form.text
    before = _job(net, jid)
    r = emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, poster_name="Dana Whitfield", show_email="1", location="Remote"))
    assert r.status_code == 303 and r.headers["location"] == f"/hiring/{jid}?done=saved"
    after = _job(net, jid)
    assert after["poster_name"] == "Dana Whitfield" and after["show_email"] == 1 and after["location"] == "Remote"
    assert after["review_status"] == "approved" and after["expires_at"] == before["expires_at"] and _on_board(stu, jid)
    # changing the description re-scans it and sends it back to review; it leaves the board until approved again
    r = emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, description=before["description"] + " Mentorship from our senior analysts."))
    assert r.headers["location"] == f"/hiring/{jid}?done=review"
    j = _job(net, jid)
    assert j["review_status"] == "pending" and "Mentorship" in j["description"] and j["expires_at"] is None
    assert not _on_board(stu, jid) and "sent back for review" in emp.get(r.headers["location"]).text
    net.app.set_review(jid, "approved", "legit")
    assert _on_board(stu, jid)
    # a scam edit is caught by the scanner like a new listing
    emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, description="Remote assistant. We send you a check, deposit it and send the rest by Zelle. $500 weekly, no experience."))
    j = _job(net, jid)
    assert j["review_status"] == "pending" and j["scam_status"] in ("flagged", "held")
    # validation errors re-show the form with the typed values; others can't edit
    bad = emp.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, description="We are a staffing agency hiring on behalf of our client."))
    assert bad.status_code == 400 and "staffing" in bad.text.lower()
    other, _ = employer(net, "hr@beta.example", company="Beta Co")
    assert other.get(f"/hiring/{jid}/edit").status_code == 404
    assert other.post(f"/hiring/{jid}/edit", data=_edit_data(emp, jid, title="Hacked")).status_code == 404
    assert _job(net, jid)["title"] == "Data Analyst Intern"
