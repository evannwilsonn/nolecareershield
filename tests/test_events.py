"""Events: employer create -> reviewer approve -> students RSVP (waitlist, .ics, cancel), reminders, feed / company page,
edits and cancellation, and the data rules (purge, export, delete)."""
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, admin, admin_csrf, employer, net, student, ucsrf  # noqa: E402,F401


def _ev():
    import events
    return events


def when(days=2, clock="18:00"):
    ev = _ev()
    d = ev.local(time.time() + days * 86400)
    return d.strftime("%Y-%m-%d"), clock


def form(csrf, **over):
    day, clock = when()
    d = {"csrf": csrf, "title": "Summer data internships: info session", "kind": "info_session",
         "description": "Meet our analytics team, hear about summer internships and bring a resume. Pizza provided.",
         "date": day, "time": clock, "duration": "60", "format": "in_person", "location": "Career Center, room 2",
         "meeting_url": "", "capacity": "", "majors": "Statistics, Computer Science", "job_id": ""}
    d.update(over)
    return d


def create(c, **over):
    r = c.post("/events/new", data=form(ucsrf(c, "/events/new"), **over))
    assert r.status_code == 303, re.findall(r'class="banner[^>]*>([^<]*)', r.text)
    return int(re.search(r"/events/(\d+)", r.headers["location"]).group(1))


def approve(n, eid):
    a = admin(n)
    assert "Events" in a.get("/admin/events").text
    assert a.post(f"/admin/events/{eid}/approve", data={"csrf": admin_csrf(a, "/admin/events")}).status_code == 303


def db(n):
    return closing(sqlite3.connect(n.app.DB_PATH))


def test_create_review_rsvp_and_employer_view(net):
    emp, eid_emp = employer(net)
    s, sid = student(net)
    eid = create(emp)
    page = emp.get(f"/events/{eid}?saved=1").text
    assert "Waiting for review" in page and "Submitted" in page
    # Pending: students can't see it anywhere.
    assert s.get(f"/events/{eid}").status_code == 404
    assert "Summer data internships" not in s.get("/events").text
    a = admin(net)
    q = a.get("/admin/events").text
    assert "Summer data internships" in q and "Career Center, room 2" in q
    assert re.search(r'href="/admin/events".*?<span class="n[^"]*">1<', a.get("/admin").text, re.S)
    approve(net, eid)
    assert any("Your event is live" in m["subject"] for m in net.mailer.outbox)
    lst = s.get("/events").text
    assert "Summer data internships" in lst and 'href="/events"' in lst and "Garnet" not in lst
    detail = s.get(f"/events/{eid}").text
    assert "RSVPing shares your name, major and class year with Acme Analytics" in detail
    t = ucsrf(s)
    r = s.post(f"/events/{eid}/rsvp", data={"csrf": t, "status": "going", "next": f"/events/{eid}"})
    assert r.status_code == 303 and "msg=going" in r.headers["location"]
    assert "Cancel RSVP" in s.get(f"/events/{eid}").text
    # The employer sees who is going: name, major, class year, and a way to message them.
    own = emp.get(f"/events/{eid}").text
    assert "Jordan R." in own and "Statistics" in own and "Class of 2027" in own and f"/messages/new?to={sid}" in own
    # Other employers never see the RSVP list.
    other, _ = employer(net, "hr@other.example", company="Other Co")
    assert "Jordan R." not in other.get(f"/events/{eid}").text
    # .ics download
    ics = s.get(f"/events/{eid}/event.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in ics.text and "DTSTART:" in ics.text and "Career Center" in ics.text
    # Cancel RSVP
    s.post(f"/events/{eid}/cancel-rsvp", data={"csrf": t, "next": f"/events/{eid}"})
    with db(net) as d:
        assert d.execute("SELECT COUNT(*) FROM event_rsvps").fetchone()[0] == 0


def test_capacity_waitlist_and_promotion(net):
    emp, _ = employer(net)
    eid = create(emp, capacity="1")
    approve(net, eid)
    a, aid = student(net, "a@fsu.edu", "Alex A.")
    b, bid = student(net, "b@fsu.edu", "Blair B.")
    ta, tb = ucsrf(a), ucsrf(b)
    a.post(f"/events/{eid}/rsvp", data={"csrf": ta, "status": "going"})
    r = b.post(f"/events/{eid}/rsvp", data={"csrf": tb, "status": "going"})
    assert "msg=waitlist" in r.headers["location"]
    assert "On the waitlist" in b.get(f"/events/{eid}").text
    net.mailer.outbox.clear()
    a.post(f"/events/{eid}/cancel-rsvp", data={"csrf": ta})
    with db(net) as d:
        assert d.execute("SELECT status FROM event_rsvps WHERE student_id = ?", (bid,)).fetchone()[0] == "going"
    assert any(m["to"] == "b@fsu.edu" and "You're in" in m["subject"] for m in net.mailer.outbox)
    # Can't go is recorded and not shown to the employer.
    a.post(f"/events/{eid}/rsvp", data={"csrf": ta, "status": "not_going"})
    assert "Alex A." not in emp.get(f"/events/{eid}").text


def test_rules_scam_text_unapproved_employer_and_meeting_links(net):
    emp, _ = employer(net)
    t = ucsrf(emp, "/events/new")
    r = emp.post("/events/new", data=form(t, description="Paid training! Send a $50 registration fee by Zelle and we will mail you a check to deposit for equipment."))
    assert r.status_code == 400 and "scam patterns" in r.text
    r = emp.post("/events/new", data=form(t, date="2020-01-01"))
    assert r.status_code == 400 and "30 minutes from now" in r.text
    r = emp.post("/events/new", data=form(t, format="virtual", meeting_url=""))
    assert r.status_code == 400 and "meeting link" in r.text
    pending, _ = employer(net, "new@pending.example", approve=False, company="Pending Co")
    assert "once a reviewer approves" in pending.get("/events/new").text
    # Virtual events: a known meeting service is clickable, and only for students who are going.
    z = create(emp, format="virtual", meeting_url="https://us02web.zoom.us/j/123456789", location="")
    o = create(emp, title="Resume workshop", kind="workshop", format="virtual", meeting_url="https://meet.example-video.io/abc", location="")
    approve(net, z)
    approve(net, o)
    s, _ = student(net)
    assert "us02web.zoom.us" not in s.get(f"/events/{z}").text
    t = ucsrf(s)
    s.post(f"/events/{z}/rsvp", data={"csrf": t, "status": "going"})
    s.post(f"/events/{o}/rsvp", data={"csrf": t, "status": "going"})
    assert 'href="https://us02web.zoom.us/j/123456789"' in s.get(f"/events/{z}").text
    other = s.get(f"/events/{o}").text
    assert "meet.example-video.io/abc" in other and 'href="https://meet.example-video.io' not in other and "isn't clickable" in other


def test_reminders_are_sent_once_and_show_in_emails(net):
    emp, _ = employer(net)
    eid = create(emp)
    approve(net, eid)
    s, sid = student(net)
    s.post(f"/events/{eid}/rsvp", data={"csrf": ucsrf(s), "status": "going"})
    ev = _ev()
    assert ev.send_event_reminders() == 0                         # two days out: not yet
    with db(net) as d:
        d.execute("UPDATE events SET starts_at = ? WHERE id = ?", (time.time() + 20 * 3600, eid))
        d.commit()
    net.mailer.outbox.clear()
    assert ev.send_event_reminders() == 1
    assert ev.send_event_reminders() == 0                         # idempotent
    net.app.purge_old()                                            # the daily maintenance runs it too
    assert sum("Reminder:" in m["subject"] for m in net.mailer.outbox) == 1
    assert "Reminder: Summer data internships" in s.get("/emails").text


def test_feed_company_page_filters_and_nav(net):
    emp, empid = employer(net)
    eid = create(emp)
    create(emp, title="Coffee chat with the data team", kind="coffee_chat", majors="Marketing")
    approve(net, eid)
    s, _ = student(net)
    feed = s.get("/feed").text
    assert 'class="fd-post fd-ev"' in feed and "Summer data internships" in feed and "ev-date" in feed
    assert 'class="fd-post fd-ev"' in s.get("/feed?tab=foryou").text
    assert 'class="fd-post fd-ev"' not in s.get("/feed?f=employers").text
    # RSVP from the feed card goes back to the feed.
    r = s.post(f"/events/{eid}/rsvp", data={"csrf": ucsrf(s), "status": "going", "next": "/feed"})
    assert r.headers["location"] == "/feed"
    assert "✓ Going" in s.get("/feed").text
    assert "Upcoming events" in s.get(f"/company/{empid}").text
    assert 'href="/events"' in s.get("/jobs").text                                        # student sidebar
    assert 'href="/events/manage"' in emp.get("/jobs").text                              # employer sidebar
    later = create(emp, title="Spring career fair table", kind="career_fair", date=when(60)[0])
    approve(net, later)
    assert "Spring career fair table" in s.get("/events").text
    assert "Spring career fair table" not in s.get("/events?when=month").text and "Spring career fair table" not in s.get("/events?when=week").text
    assert "Summer data internships" in s.get("/events?type=info_session").text
    assert "Summer data internships" not in s.get("/events?type=workshop").text
    assert "Summer data internships" in s.get("/events?major=1").text                     # Jordan studies Statistics
    assert "Your events" in emp.get("/events/manage").text and "Coffee chat" in emp.get("/events/manage").text


def test_edit_rereview_and_cancel_notifies(net):
    emp, _ = employer(net)
    eid = create(emp)
    approve(net, eid)
    s, _ = student(net)
    s.post(f"/events/{eid}/rsvp", data={"csrf": ucsrf(s), "status": "going"})
    t = ucsrf(emp)
    r = emp.post(f"/events/{eid}/edit", data=form(t, capacity="30"))
    assert "msg=edited" in r.headers["location"]
    with db(net) as d:
        assert d.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()[0] == "approved"
    r = emp.post(f"/events/{eid}/edit", data=form(t, description="Meet our analytics team and learn about internships. New: a live dashboard demo."))
    assert "msg=review" in r.headers["location"]
    with db(net) as d:
        assert d.execute("SELECT status FROM events WHERE id = ?", (eid,)).fetchone()[0] == "pending"
    assert s.get(f"/events/{eid}").status_code == 404
    approve(net, eid)
    net.mailer.outbox.clear()
    emp.post(f"/events/{eid}/cancel", data={"csrf": t})
    assert any(m["to"] == "jordan@fsu.edu" and m["subject"].startswith("Cancelled:") for m in net.mailer.outbox)
    page = s.get(f"/events/{eid}").text
    assert "cancelled by the employer" in page and "Cancel RSVP" not in page


def test_purge_export_and_delete(net):
    emp, empid = employer(net)
    eid = create(emp)
    approve(net, eid)
    s, sid = student(net)
    t = ucsrf(s)
    s.post(f"/events/{eid}/rsvp", data={"csrf": t, "status": "going"})
    assert len(s.get("/profile/export").json()["event_rsvps"]) == 1
    assert len(emp.get("/profile/export").json()["events"]) == 1
    # Deleting the employer cancels the event (RSVPs are emailed) and removes it and its RSVPs.
    net.mailer.outbox.clear()
    assert emp.post("/profile/delete", data={"csrf": ucsrf(emp), "password": "Str0ng!pass"}).status_code in (200, 303)
    assert any(m["to"] == "jordan@fsu.edu" and m["subject"].startswith("Cancelled:") for m in net.mailer.outbox)
    with db(net) as d:
        assert d.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert d.execute("SELECT COUNT(*) FROM event_rsvps").fetchone()[0] == 0
    # Past events go a year after they happened.
    emp2, _ = employer(net, "hr@two.example", company="Two Co")
    e2 = create(emp2)
    s.post(f"/events/{e2}/rsvp", data={"csrf": t, "status": "going"})
    with db(net) as d:
        d.execute("UPDATE events SET starts_at = ? WHERE id = ?", (time.time() - 400 * 86400, e2))
        d.execute("INSERT INTO event_rsvps (event_id, student_id, status, created_at, updated_at) VALUES (?,?,?,?,?)", (e2, sid, "going", 0, 0))
        d.commit()
    net.app.purge_old()
    with db(net) as d:
        assert d.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert d.execute("SELECT COUNT(*) FROM event_rsvps").fetchone()[0] == 0
    # A student deleting their account removes their RSVPs.
    e3 = create(emp2)
    approve(net, e3)
    s.post(f"/events/{e3}/rsvp", data={"csrf": t, "status": "going"})
    s.post("/profile/delete", data={"csrf": t, "password": "Str0ng!pass"})
    with db(net) as d:
        assert d.execute("SELECT COUNT(*) FROM event_rsvps").fetchone()[0] == 0


def test_time_helpers_eastern():
    ev = _ev()
    ts = ev.to_ts("2026-07-04", "18:30")                          # EDT, UTC-4
    assert time.strftime("%H:%M", time.gmtime(ts)) == "22:30"
    ts = ev.to_ts("2026-12-04", "18:30")                          # EST, UTC-5
    assert time.strftime("%H:%M", time.gmtime(ts)) == "23:30"
    assert ev.local(ts).strftime("%H:%M") == "18:30"
    assert ev.to_ts("2026-02-30", "10:00") is None
    assert ev.meeting_host_ok("https://us02web.zoom.us/j/1") and ev.meeting_host_ok("https://teams.microsoft.com/l/x")
    assert not ev.meeting_host_ok("https://zoom.us.evil.example/j/1") and not ev.meeting_host_ok("http://meet.google.com/abc")
    fake = {"id": 1, "title": "A, B; C", "company": "Acme", "description": "Line one\nLine two " + "x" * 200, "starts_at": ts, "duration_min": 60,
            "format": "virtual", "location": "", "meeting_url": "https://meet.google.com/abc-defg-hij", "status": "approved"}
    out = ev.ics(fake, True)
    assert "SUMMARY:A\\, B\\; C (Acme)" in out and "meet.google.com" in out.replace("\r\n ", "")
    assert all(len(line.encode()) <= 75 for line in out.split("\r\n"))
    assert "meet.google.com" not in ev.ics(fake, False).replace("\r\n ", "")
