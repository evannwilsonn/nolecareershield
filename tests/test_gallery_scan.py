"""The Guardian: the student Gallery, per-listing Security Reports with the pure-CSS scan, hide-from-gallery,
and the scam check's result in the same HUD (guardian.py, css_guardian.py)."""
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, admin, employer, net, student, ucsrf  # noqa: E402,F401

SCAMMY = ("Remote social media intern. Plan posts and write captions. Text our HR on WhatsApp to get started today. "
          "$22/hour. Apply on our careers page.")


def _db(n):
    return closing(sqlite3.connect(n.app.DB_PATH))


def test_gallery_shows_curated_listings_with_true_stats(net):
    s, sid = student(net)
    emp, eid = employer(net)
    other, oid = employer(net, "hr@coastal.example", company="Coastal Policy Lab")
    a = add_job(net, eid)
    b = add_job(net, eid, title="Data Engineering Intern", desc="Internship building Python and SQL pipelines. $20/hour. Apply on our careers page.")
    c = add_job(net, oid, title="Research Assistant", desc="Part-time research assistant using R and Python for survey data. $17/hour.")
    home = s.get("/").text
    assert 'class="gal"' in home and "the curated gallery" in home and "worth your time, <em>Jordan.</em>" in home
    assert "Three roles" in home                                              # the number actually shown, in words
    assert 'action="/jobs"' in home and 'name="search"' in home and 'href="/jobs?kind=internship"' in home and 'href="/jobs?work_type=remote"' in home
    assert "Verified employers" in home and "Threats intercepted this week" in home and "Saved jobs" in home
    assert "$18<small>/hour</small>" in home and "$17<small>/hour</small>" in home      # pay only when the listing states it
    assert home.count('class="card gcard"') == 3 and "% match" in home and "Verified employer" in home
    # one listing per employer comes first: both employers are in, and three cards means Acme's second one filled the last slot
    for j in (a, b, c):
        assert f'href="/job/{j}"' in home
    # chips are idle until the student opens the report, and link to it (the first run plays the scan)
    assert f'href="/job/{a}/report?scan=1"' in home and "Run scan" in home and "See all jobs" in home
    assert "Needs your attention" not in home                                 # nothing needs attention yet


def test_gallery_empty_state_and_attention_strip(net):
    s, sid = student(net)
    home = s.get("/").text
    assert "The gallery is quiet" in home and "Nothing to show yet" in home
    emp, eid = employer(net)
    r = emp.post("/messages/new", data={"csrf": ucsrf(emp), "to": sid, "body": "Hi Jordan, would you like to chat about our internship?"})
    assert r.status_code in (200, 303)
    home = s.get("/").text
    assert "Needs your attention" in home and "1 unread message" in home and 'href="/messages"' in home


def test_security_report_uses_the_real_scanner_output(net):
    s, sid = student(net)
    emp, eid = employer(net)
    j = add_job(net, eid, title="Social Media Intern", desc=SCAMMY)
    with _db(net) as db:
        row = db.execute("SELECT findings_json, ruleset_version, scam_status FROM jobs WHERE id = ?", (j,)).fetchone()
    findings = json.loads(row[0])
    assert findings, "the listing should trip at least one rule"
    first = s.get(f"/job/{j}/report").text
    # first visit: the scan plays (pure CSS), then the report
    assert 'class="gd-stage anim"' in first and 'class="gd-scan" aria-hidden="true"' in first and "Guardian scan engine" in first
    assert "<script" not in first.replace('<script src="/static/fx.js', "").replace('<script src="/static/app.js', "")
    assert "Security report · #AA-" in first and "Detection matrix" in first and "Evidence" in first
    assert f"Ruleset {row[1]}" in first and "Reviewed by a person before publishing" in first
    for f in findings:
        assert f["title"].replace("'", "&#x27;") in first.replace("'", "&#x27;") or f["title"] in first
    matched = [m for f in findings for m in f.get("matched", []) if m and m != "user-observed"]
    assert any(f"“{m.strip(chr(34))}”" in first for m in matched)             # the exact words it caught
    assert "Contact" in first and "Pay" in first and "Employer" in first and "Verified by a reviewer" in first
    assert "Domain" not in first and "whois" not in first                     # never a check the scanner didn't run
    # later visits open the report directly; ?scan=1 replays
    again = s.get(f"/job/{j}/report").text
    assert 'class="gd-stage"' in again and 'class="gd-scan"' not in again
    assert 'class="gd-stage anim"' in s.get(f"/job/{j}/report?scan=1").text
    # once opened, the chip shows the real result on the board, the gallery and the job page
    for page in (s.get("/jobs").text, s.get("/").text, s.get(f"/job/{j}").text):
        assert f'href="/job/{j}/report"' in page and ("Caution" in page or "Secure" in page or "Threat" in page)
    assert "Open security report" in s.get(f"/job/{j}").text
    with _db(net) as db:
        assert db.execute("SELECT COUNT(*) FROM report_views WHERE user_id = ? AND job_id = ?", (sid, j)).fetchone()[0] == 1


def test_report_access_rules(net):
    s, sid = student(net)
    emp, eid = employer(net)
    other, oid = employer(net, "hr@other.example", company="Other Co")
    j = add_job(net, eid)
    assert s.get(f"/job/{j}/report").status_code == 200
    assert emp.get(f"/job/{j}/report").status_code == 200 and "Back to your listing" in emp.get(f"/job/{j}/report").text
    assert other.get(f"/job/{j}/report").status_code == 404
    a = admin(net)
    assert a.get(f"/job/{j}/report").status_code == 200 and "Back to the review queue" in a.get(f"/job/{j}/report").text
    visitor = net.client()
    r = visitor.get(f"/job/{j}/report")
    assert r.status_code in (302, 303) and "/login" in r.headers["location"]
    # a pending listing isn't open to students, but its employer and reviewers can see its report
    p = net.app.add_job({"title": "Pending role", "company": "Acme Analytics", "category": "Other", "work_type": "remote", "location": "",
                         "description": "A pending listing for testing the report access rules here.", "apply_url": "", "contact": ""}, employer_id=eid)["id"]
    assert s.get(f"/job/{p}/report").status_code == 404
    assert "Waiting for a reviewer" in emp.get(f"/job/{p}/report").text


def test_hide_from_gallery_and_data_rights(net):
    s, sid = student(net)
    emp, eid = employer(net)
    j = add_job(net, eid)
    t = ucsrf(s)
    assert s.post(f"/job/{j}/hide", data={"csrf": "nope"}).headers["location"] == f"/job/{j}/report"   # CSRF checked
    r = s.post(f"/job/{j}/hide", data={"csrf": t})
    assert r.status_code == 303 and r.headers["location"] == f"/job/{j}/report?hidden=1"
    home = s.get("/").text
    assert f'href="/job/{j}"' not in home and "The gallery is quiet" in home and "hidden every live listing" in home
    page = s.get(f"/job/{j}/report?hidden=1").text
    assert "Hidden from your gallery" in page and "Show in my gallery again" in page
    s.get(f"/job/{j}/report")
    data = json.loads(s.get("/profile/export").text)
    assert data["hidden_from_gallery"][0]["job_id"] == j and data["security_reports_opened"][0]["job_id"] == j
    s.post(f"/job/{j}/unhide", data={"csrf": t})
    assert f'href="/job/{j}"' in s.get("/").text
    s.post(f"/job/{j}/hide", data={"csrf": t})
    # deleting the account removes both
    import store
    with _db(net) as db:
        store.delete_account(db, sid)
        assert db.execute("SELECT COUNT(*) FROM report_views WHERE user_id = ?", (sid,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM gallery_hidden WHERE user_id = ?", (sid,)).fetchone()[0] == 0


def test_purge_drops_rows_for_deleted_listings(net):
    s, sid = student(net)
    emp, eid = employer(net)
    j = add_job(net, eid)
    s.get(f"/job/{j}/report")
    s.post(f"/job/{j}/hide", data={"csrf": ucsrf(s)})
    import store
    with _db(net) as db:
        db.execute("DELETE FROM jobs WHERE id = ?", (j,))
        db.commit()
        store.purge(db)
        assert db.execute("SELECT COUNT(*) FROM report_views").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM gallery_hidden").fetchone()[0] == 0


def test_scan_css_works_without_script_and_respects_reduced_motion():
    import ui
    import css_guardian  # noqa: F401
    css = ui.THEME_CSS
    assert css.index("/* ---------- guardian: the gallery") > css.index(".statrow{")        # lands after the theme
    assert "@keyframes gd-in" in css and "2.7s both" in css and "@keyframes gd-spin" in css
    assert re.search(r"prefers-reduced-motion:reduce\)\{\.gd-stage\.anim \.gd-scan\{display:none\}\.gd-stage\.anim \.gd-report\{animation:none\}", css)


def test_modules_only_show_what_ran():
    import guardian
    mods = guardian.modules([], link_ran=False, comp={"status": "no_pay_found"})
    keys = [m["key"] for m in mods]
    assert keys == ["language", "payment", "contact", "pay", "identity"] and all(m["st"] == "o" for m in mods)
    assert mods[3]["value"] == "No pay figure stated"
    f = [{"rule_id": "fake_check_funds", "severity": "critical", "weight": 30, "title": "They'll send you money to buy things", "why": "x", "matched": ["mail you a check"]},
         {"rule_id": "pay_anomaly", "severity": "warning", "weight": 17, "title": "The stated pay is out of band", "why": "y", "matched": []}]
    mods = {m["key"]: m for m in guardian.modules(f, link_ran=True, comp={"status": "flagged", "ratio_to_median": 2.6}, employer="none")}
    assert mods["payment"]["st"] == "r" and mods["pay"]["st"] == "w" and mods["pay"]["value"] == "2.6× national median"
    assert mods["link"]["st"] == "o" and mods["employer"]["value"] == "No employer account" and "model" not in mods
    assert guardian.pay_of("Pays $18-22/hr, hybrid") == ("$18–22", "/hour") and guardian.pay_of("$500 weekly") == ("$500", "/week")
    assert guardian.pay_of("Competitive pay") is None


def test_scam_check_result_uses_the_hud(net):
    c = net.client()
    page = c.get("/check").text
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = c.post("/check/listing", data={"csrf": tok, "title": "Remote Admin Assistant", "company": "QuickCash Staffing",
                                       "description": "Part-time remote assistant, $500 weekly, no experience needed. We will send you a check to buy office "
                                                      "equipment from our vendor. Deposit it and send the rest by Zelle.", "url": "", "contact": ""})
    assert r.status_code == 200 and 'class="gd-stage gd-check"' in r.text and "Not on NoleCareerShield · SCANNED FROM YOUR TEXT" in r.text
    assert "Threat level · CRITICAL" in r.text and "Remote Admin Assistant" in r.text and "Detection matrix" in r.text
    assert "Found:" not in r.text                                                 # visitors never get the matched words
