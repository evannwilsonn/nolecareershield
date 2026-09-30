"""Interview scheduling inside Messages and employer message templates."""
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401


def _convo(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    r = emp.post("/messages/new", data={"csrf": ucsrf(emp), "to": sid, "job": job, "body": "Hello, we'd like to talk about our summer analytics internship."})
    assert r.status_code == 303
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    return s, sid, emp, eid, cid


def _day(days=3):
    import scheduling
    return scheduling.to_et(time.time() + days * 86400).date().isoformat()


def _propose(emp, cid, **over):
    data = {"csrf": ucsrf(emp, f"/messages/{cid}"), "format": "video", "location": "https://acme.zoom.us/j/99887766",
            "note": "You'll meet Pat and our data lead.", "d1": _day(3), "t1": "14:00", "m1": "30", "d2": _day(4), "t2": "10:30", "m2": "45"}
    data.update(over)
    return emp.post(f"/messages/{cid}/interview", data=data)


def _db(net):
    return closing(sqlite3.connect(net.app.DB_PATH))


def test_eastern_time_rules():
    import datetime as dt
    import scheduling as s
    # DST: 2:00 PM on Oct 6 2026 is 18:00 UTC; Dec 25 is standard time (UTC-5).
    assert dt.datetime.fromtimestamp(s.from_et(dt.datetime(2026, 10, 6, 14, 0)), dt.timezone.utc).hour == 18
    assert dt.datetime.fromtimestamp(s.from_et(dt.datetime(2026, 12, 25, 9, 15)), dt.timezone.utc).hour == 14
    ts = s.from_et(dt.datetime(2026, 10, 6, 14, 0))
    assert s.fmt_slot(ts, 30) == "Tue, Oct 6 · 2:00 – 2:30 PM ET"
    assert s.fmt_slot(s.from_et(dt.datetime(2026, 10, 6, 11, 30)), 45) == "Tue, Oct 6 · 11:30 AM – 12:15 PM ET"
    assert s.to_et(ts) == dt.datetime(2026, 10, 6, 14, 0)
    # Only exact https links to the well-known meeting hosts are clickable.
    assert s.meeting_link("https://fsu.zoom.us/j/1?pwd=x") and s.meeting_link("https://meet.google.com/abc-defg-hij")
    assert s.meeting_link("https://teams.microsoft.com/l/meetup-join/x")
    for bad in ("http://zoom.us/j/1", "https://evilzoom.us/j/1", "https://meet.google.com.evil.example/x", "https://user@zoom.us/j/1",
                "https://zoom.us/j/1 and more", "https://acme.example/meet"):
        assert not s.meeting_link(bad), bad


def test_propose_pick_confirm_ics_and_upcoming(net):
    s, sid, emp, eid, cid = _convo(net)
    page = emp.get(f"/messages/{cid}").text
    assert f'href="/messages/{cid}/interview"' in page and "Propose interview times" in page
    assert "Propose interview times" not in s.get(f"/messages/{cid}").text          # students can't propose
    assert s.get(f"/messages/{cid}/interview").status_code == 403
    form = emp.get(f"/messages/{cid}/interview").text
    assert "America/New_York" in form and 'name="d5"' in form and 'name="d6"' not in form
    net.mailer.outbox.clear()
    r = _propose(emp, cid)
    assert r.status_code == 303, r.text[:500]
    assert any(m["to"] == "jordan@fsu.edu" and "proposed interview times" in m["subject"] for m in net.mailer.outbox)
    assert not any("zoom.us" in m["body"] for m in net.mailer.outbox)                  # links stay on the site
    sp = s.get(f"/messages/{cid}").text
    assert "Interview times proposed" in sp and sp.count('class="iv-pick"') == 2 and "proposed 2 interview times" in sp
    # The zoom link is clickable, with rel=noopener.
    assert '<a href="https://acme.zoom.us/j/99887766" target="_blank" rel="noopener noreferrer">' in sp
    with _db(net) as db:
        pid, = db.execute("SELECT id FROM interview_proposals WHERE conversation_id = ?", (cid,)).fetchone()
        slots = [r[0] for r in db.execute("SELECT id FROM interview_slots WHERE proposal_id = ? ORDER BY starts_at", (pid,))]
    # Only the conversation's student can pick; the employer can't.
    t = ucsrf(emp, f"/messages/{cid}")
    assert emp.post(f"/messages/{cid}/interview/{pid}/pick", data={"csrf": t, "slot": slots[0]}).status_code == 403
    other, _ = student(net, "other@fsu.edu", "Other O.")
    assert other.post(f"/messages/{cid}/interview/{pid}/pick", data={"csrf": ucsrf(other), "slot": slots[0]}).status_code == 404
    # A slot from another proposal is refused; a real one confirms.
    st = ucsrf(s, f"/messages/{cid}")
    assert s.post(f"/messages/{cid}/interview/{pid}/pick", data={"csrf": st, "slot": 999999}).status_code == 400
    net.mailer.outbox.clear()
    r = s.post(f"/messages/{cid}/interview/{pid}/pick", data={"csrf": st, "slot": slots[1]})
    assert r.status_code == 303
    confirmed = [m for m in net.mailer.outbox if m["subject"].startswith("Interview confirmed")]
    assert {m["to"] for m in confirmed} == {"jordan@fsu.edu", "recruiter@acme.example"} and "10:30 – 11:15 AM ET" in confirmed[0]["body"]
    # In-site Emails keep a copy.
    assert "Interview confirmed" in s.get("/emails").text
    sp = s.get(f"/messages/{cid}").text
    assert "Interview confirmed" in sp and "picked" in sp and "invite.ics" in sp and 'class="iv-pick"' not in sp
    # Picking again after confirmation is refused.
    assert s.post(f"/messages/{cid}/interview/{pid}/pick", data={"csrf": st, "slot": slots[0]}).status_code == 409
    # Calendar file: text/calendar, UTC times, CRLF lines, only for the two participants.
    r = s.get(f"/messages/{cid}/interview/{pid}/invite.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR\r\n" in r.text and re.search(r"DTSTART:\d{8}T\d{4}00Z", r.text) and "SUMMARY:Interview with Acme Analytics" in r.text
    assert "URL:https://acme.zoom.us/j/99887766" in r.text and all(len(line.encode()) <= 75 for line in r.text.split("\r\n"))
    assert emp.get(f"/messages/{cid}/interview/{pid}/invite.ics").status_code == 200
    assert other.get(f"/messages/{cid}/interview/{pid}/invite.ics").status_code == 404
    # Upcoming lists on /messages for both sides, and the helper.
    for c in (s, emp):
        assert "Upcoming interviews" in c.get("/messages").text
    import scheduling, store
    with store.db() as conn:
        up = scheduling.upcoming_interviews(conn, sid)
        assert len(up) == 1 and up[0]["other_name"] == "Acme Analytics" and up[0]["link"] == "https://acme.zoom.us/j/99887766"
        assert scheduling.upcoming_interviews(conn, eid)[0]["other_name"] == "Jordan R."
    # Export includes the interview.
    assert s.get("/profile/export").json()["interviews"][0]["status"] == "confirmed"
    # The employer cancels: both see it, the student gets an email, the list empties.
    net.mailer.outbox.clear()
    assert emp.post(f"/messages/{cid}/interview/{pid}/cancel", data={"csrf": ucsrf(emp, f"/messages/{cid}")}).status_code == 303
    assert any(m["to"] == "jordan@fsu.edu" and "cancelled" in m["subject"] for m in net.mailer.outbox)
    assert "Upcoming interviews" not in s.get("/messages").text
    assert "cancelled the interview" in s.get(f"/messages/{cid}").text
    assert s.get(f"/messages/{cid}/interview/{pid}/invite.ics").status_code == 404


def test_decline_reschedule_and_past_slots(net):
    s, sid, emp, eid, cid = _convo(net)
    assert _propose(emp, cid).status_code == 303
    with _db(net) as db:
        pid, = db.execute("SELECT id FROM interview_proposals").fetchone()
    st = ucsrf(s, f"/messages/{cid}")
    # A scam note from the student is refused.
    r = s.post(f"/messages/{cid}/interview/{pid}/decline", data={"csrf": st, "note": "Text me on WhatsApp so we can move faster https://wa.me/18505550142"})
    assert r.status_code == 400
    net.mailer.outbox.clear()
    r = s.post(f"/messages/{cid}/interview/{pid}/decline", data={"csrf": st, "note": "I'm free weekday afternoons after 3."})
    assert r.status_code == 303
    assert any(m["to"] == "recruiter@acme.example" and "different interview times" in m["subject"] for m in net.mailer.outbox)
    ep = emp.get(f"/messages/{cid}").text
    assert "None of these times worked" in ep and "weekday afternoons" in ep and "Propose new times" in ep
    # Reschedule: the old proposal is replaced, the student gets new times.
    net.mailer.outbox.clear()
    r = _propose(emp, cid, re=str(pid), d2="", t2="")
    assert r.status_code == 303
    assert any("new interview times" in m["subject"] for m in net.mailer.outbox)
    with _db(net) as db:
        rows = db.execute("SELECT id, status FROM interview_proposals ORDER BY id").fetchall()
        assert [x[1] for x in rows] == ["rescheduled", "open"]
        new_pid = rows[1][0]
        slot, = db.execute("SELECT id FROM interview_slots WHERE proposal_id = ?", (new_pid,)).fetchone()
        # Make the time pass: it can't be picked any more.
        db.execute("UPDATE interview_slots SET starts_at = ? WHERE id = ?", (time.time() - 3600, slot))
        db.commit()
    sp = s.get(f"/messages/{cid}").text
    assert "Passed" in sp and "All of these times have passed" in sp
    assert s.post(f"/messages/{cid}/interview/{new_pid}/pick", data={"csrf": st, "slot": slot}).status_code == 400


def test_propose_validation_and_permissions(net):
    s, sid, emp, eid, cid = _convo(net)
    past = __import__("scheduling").to_et(time.time() - 86400).date().isoformat()
    cases = [({"d1": past}, "in the past"), ({"t1": ""}, "needs both"), ({"m1": "90"}, "15, 30, 45 or 60"),
             ({"format": "fax"}, "Pick a format"), ({"location": ""}, "meeting link"),
             ({"format": "in_person", "location": ""}, "address"),
             ({"note": "You will receive a check to deposit for equipment, then send the rest back in gift cards."}, "scam patterns"),
             ({"location": "https://bit.ly/abc123"}, "Chat-app, shortened"),
             ({"d1": "", "t1": "", "d2": "", "t2": ""}, "at least one time")]
    for over, want in cases:
        r = _propose(emp, cid, **over)
        assert r.status_code == 400 and want in r.text, (over, r.text[:300])
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM interview_proposals").fetchone()[0] == 0
    # Other hosts are allowed but shown as plain text; a phone call needs no location.
    assert _propose(emp, cid, format="phone", location="").status_code == 303
    assert _propose(emp, cid, format="in_person", location="https://acme.example/visit").status_code == 303
    sp = s.get(f"/messages/{cid}").text
    assert "https://acme.example/visit" in sp and 'href="https://acme.example/visit"' not in sp
    # Bad CSRF does nothing.
    r = emp.post(f"/messages/{cid}/interview", data={"csrf": "x", "format": "phone", "d1": _day(), "t1": "09:00", "m1": "30"})
    assert r.status_code == 303
    # An unapproved employer can't propose.
    pend, pid = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    with _db(net) as db:
        db.execute("INSERT INTO conversations (student_id, employer_id, job_id, subject, started_by, created_at, last_at) VALUES (?,?,0,'',?,?,?)",
                   (sid, pid, sid, time.time(), time.time()))
        db.commit()
        bcid, = db.execute("SELECT id FROM conversations WHERE employer_id = ?", (pid,)).fetchone()
    assert pend.get(f"/messages/{bcid}/interview").status_code == 403
    assert _propose(pend, bcid).status_code == 403
    # A blocked conversation can't get new times.
    assert s.post(f"/messages/{cid}/block", data={"csrf": ucsrf(s, f"/messages/{cid}")}).status_code == 303
    assert _propose(emp, cid).status_code == 403


def test_templates_defaults_crud_scan_and_insert(net):
    s, sid, emp, eid, cid = _convo(net)
    assert s.get("/messages/templates").status_code in (303, 403)
    page = emp.get("/messages/templates").text
    for title in ("Thanks for applying", "Next steps", "Not moving forward", "Interview confirmation"):
        assert title in page
    assert "4 of 30 templates" in page
    # The composer's no-JS picker: a link that reloads the conversation with the filled text.
    conv = emp.get(f"/messages/{cid}").text
    assert "Insert template" in conv and "Insert template" not in s.get(f"/messages/{cid}").text
    with _db(net) as db:
        tpls = db.execute("SELECT id, title FROM message_templates WHERE employer_id = ? ORDER BY id", (eid,)).fetchall()
    tid = tpls[0][0]
    assert f'href="/messages/{cid}?tpl={tid}#m-body"' in conv and 'data-tpl-fill="Hi Jordan,' in conv
    filled = emp.get(f"/messages/{cid}?tpl={tid}").text
    assert "Hi Jordan," in filled and "Data Analyst Intern role at Acme Analytics" in filled and "{first_name}" not in filled
    assert "Hi Jordan" not in s.get(f"/messages/{cid}?tpl={tid}").text           # students can't use it
    # New-message page picker keeps to/job.
    new = emp.get(f"/messages/new?to={sid}").text
    assert "Insert template" in new
    # Edit, scan-block, delete, create, limit.
    t = ucsrf(emp, "/messages/templates")
    r = emp.post(f"/messages/templates/{tid}", data={"csrf": t, "title": "Thanks!", "body": "Hi {first_name}, thanks for applying to {job_title}."})
    assert r.status_code == 303
    r = emp.post(f"/messages/templates/{tid}", data={"csrf": t, "title": "Pay", "body": "You will receive a check to deposit, buy gift cards and send the codes. Pay the training fee."})
    assert r.status_code == 400 and "scam patterns" in r.text
    r = emp.post("/messages/templates", data={"csrf": t, "title": "x" * 81, "body": "Hello"})
    assert r.status_code == 400 and "80 characters" in r.text
    r = emp.post("/messages/templates", data={"csrf": t, "title": "Long", "body": "a" * 2001})
    assert r.status_code == 400 and "2,000" in r.text
    assert emp.post(f"/messages/templates/{tpls[1][0]}/delete", data={"csrf": t}).status_code == 303
    for i in range(27):
        assert emp.post("/messages/templates", data={"csrf": t, "title": f"T{i}", "body": f"Follow-up {i} for {{first_name}}."}).status_code == 303
    r = emp.post("/messages/templates", data={"csrf": t, "title": "One too many", "body": "Hello"})
    assert r.status_code == 400 and "up to 30" in r.text
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM message_templates WHERE employer_id = ?", (eid,)).fetchone()[0] == 30
    # Deleted defaults don't come back.
    assert "Next steps" not in emp.get("/messages/templates").text
    # Another employer can't edit these.
    other, _ = employer(net, "hr@gamma.example", company="Gamma Co")
    assert other.post(f"/messages/templates/{tid}", data={"csrf": ucsrf(other, "/messages/templates"), "title": "Hacked", "body": "x"}).status_code == 303
    with _db(net) as db:
        assert db.execute("SELECT title FROM message_templates WHERE id = ?", (tid,)).fetchone()[0] == "Thanks!"
    assert emp.get("/profile/export").json()["message_templates"][0]["title"] == "Thanks!"


def test_delete_account_and_purge_clear_scheduling(net):
    s, sid, emp, eid, cid = _convo(net)
    assert _propose(emp, cid).status_code == 303
    emp.get("/messages/templates")
    t = ucsrf(emp, "/profile")
    assert emp.post("/profile/delete", data={"csrf": t, "password": __import__("test_app").PW}).status_code == 200
    with _db(net) as db:
        for table in ("interview_proposals", "interview_slots", "interview_events", "message_templates", "template_seeds"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    import store
    with store.db() as conn:
        now = time.time()
        conn.execute("INSERT INTO interview_proposals (conversation_id, employer_id, student_id, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (cid, 999, sid, now - 400 * 86400, now - 400 * 86400))
        conn.execute("INSERT INTO interview_slots (proposal_id, starts_at, minutes) VALUES (last_insert_rowid(), ?, 30)", (now - 390 * 86400,))
        conn.execute("INSERT INTO interview_slots (proposal_id, starts_at, minutes) VALUES (424242, ?, 30)", (now,))
        store.purge(conn)
        assert conn.execute("SELECT COUNT(*) FROM interview_proposals").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM interview_slots").fetchone()[0] == 0


def test_messages_pages_have_no_inline_script_and_fit_phones(net):
    s, sid, emp, eid, cid = _convo(net)
    assert _propose(emp, cid).status_code == 303
    for c, path in ((s, f"/messages/{cid}"), (emp, f"/messages/{cid}"), (emp, "/messages/templates"), (emp, f"/messages/{cid}/interview")):
        html = c.get(path).text
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), path
        assert "/* ---------- messages: interview cards" in html
