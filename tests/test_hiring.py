"""Employer hiring tools: ranked matches, invite to apply, candidate tracker, listing stats."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401

NURSE = "Patient care assistant. Must hold CNA and CPR certification. Nursing students preferred. Vital signs and charting in Epic."


def test_ranked_matches_invite_and_candidates(net):
    s1, sid1 = student(net)                                             # Jordan: stats + SQL resume, visible
    s2, sid2 = student(net, "b@fsu.edu", "Blair B.", resume=None)       # visible, thin profile
    s3, sid3 = student(net, "c@fsu.edu", "Casey C.", visible=False)     # hidden from employers
    emp, eid = employer(net)
    job = add_job(net, eid)
    page = emp.get(f"/hiring/{job}").text
    assert "Ranked matches" in page and "students viewed" in page
    assert "Jordan R." in page and "Casey C." not in page                # only visible students are ranked
    assert page.index("Jordan R.") < page.index("Blair B.")              # best fit first
    assert re.search(r"<b>SQL</b> <span class=faint>\(", page)           # evidence, not just a number
    assert f"/messages/new?to={sid1}&amp;job={job}&amp;invite=1" in page

    # Invite: prefilled, and sending it puts Jordan in the tracker as invited.
    inv = emp.get(f"/messages/new?to={sid1}&job={job}&invite=1").text
    assert "Hi Jordan!" in inv and "Data Analyst Intern" in inv
    t = ucsrf(emp)
    body = re.search(r'<textarea id="n-body"[^>]*>(.*?)</textarea>', inv, re.S).group(1).replace("&#x27;", "'").replace("&amp;", "&")
    assert emp.post("/messages/new", data={"csrf": t, "to": sid1, "job": job, "body": body}).status_code == 303
    # Save Blair from matches; hidden Casey can't be saved even by posting the form.
    emp.post(f"/hiring/{job}/save", data={"csrf": t, "student": sid2})
    emp.post(f"/hiring/{job}/save", data={"csrf": t, "student": sid3})
    cand = emp.get(f"/hiring/{job}?tab=candidates").text
    assert "Candidates (2)" in cand and "You invited" in cand and "Saved from matches" in cand and "Casey C." not in cand
    # Move Jordan to interviewing with a private note; the note is escaped and never shown to the student.
    emp.post(f"/hiring/{job}/stage", data={"csrf": t, "student": sid1, "stage": "interviewing", "note": "<b>great</b> SQL"})
    cand = emp.get(f"/hiring/{job}?tab=candidates").text
    assert 'value="interviewing" selected' in cand and "&lt;b&gt;great&lt;/b&gt; SQL" in cand
    assert "great" not in s1.get(f"/job/{job}").text and "great" not in s1.get("/messages").text
    emp.post(f"/hiring/{job}/stage", data={"csrf": t, "student": sid1, "stage": "bogus"})
    assert 'value="interviewing" selected' in emp.get(f"/hiring/{job}?tab=candidates").text

    # A student messaging about the listing lands in the tracker too.
    s4, sid4 = student(net, "d@fsu.edu", "Dana D.")
    t4 = ucsrf(s4)
    s4.post("/messages/new", data={"csrf": t4, "to": eid, "job": job, "body": "Hi! Is the Data Analyst Intern role still open?"})
    cand = emp.get(f"/hiring/{job}?tab=candidates").text
    assert "Dana D." in cand and "Messaged you" in cand


def test_listing_stats_count_views_and_apply_clicks_without_names(net):
    emp, eid = employer(net)
    job = add_job(net, eid)
    s1, _ = student(net)
    s2, _ = student(net, "b@fsu.edu", "Blair B.")
    for c in (s1, s1, s2):
        c.get(f"/job/{job}")
    s1.get(f"/job/{job}/apply", follow_redirects=False)
    s1.get(f"/job/{job}/apply", follow_redirects=False)                 # counted once per student
    net.client().get(f"/job/{job}")                                      # visitors aren't counted
    page = emp.get(f"/hiring/{job}?tab=candidates").text
    nums = dict((label, int(n)) for n, label in re.findall(r'<div class="n">(\d+)</div><div class="l">([^<]+)</div>', page))
    assert nums["students viewed"] == 2 and nums["clicked Apply"] == 1 and nums["messaged you"] == 0
    assert "50% of viewers" in page
    over = emp.get("/hiring").text
    assert "Data Analyst Intern" in over and "Live" in over


def test_hiring_pages_are_the_employers_own(net):
    emp, eid = employer(net)
    other, oid = employer(net, "hr@beta.example", company="Beta Co")
    pend, pid = employer(net, "hr@gamma.example", approve=False, company="Gamma Co")
    job = add_job(net, eid)
    student(net)
    assert other.get(f"/hiring/{job}").status_code == 404
    t = ucsrf(other)
    other.post(f"/hiring/{job}/stage", data={"csrf": t, "student": 1, "stage": "hired"})
    s, _ = student(net, "z@fsu.edu", "Zed Z.")
    try:                                                                 # the app renders Forbidden as a 403 page
        assert s.get("/hiring").status_code == 403
    except Exception as e:                                               # (or the test client re-raises it, depending on load order)
        assert type(e).__name__ == "Forbidden"
    # An unapproved employer sees stats but not student profiles.
    pjob = add_job(net, pid, title="Front Desk Assistant")
    page = pend.get(f"/hiring/{pjob}").text
    assert "open once a reviewer approves your organization" in page and "Jordan R." not in page
    # The listing page points its owner to the hiring tools.
    assert f'href="/hiring/{job}"' in emp.get(f"/job/{job}").text


def test_deleting_accounts_clears_hiring_data(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    s.get(f"/job/{job}")
    t = ucsrf(emp)
    emp.post(f"/hiring/{job}/save", data={"csrf": t, "student": sid})
    import store
    with store.db() as conn:
        store.delete_account(conn, sid)
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM job_views").fetchone()[0] == 0


def test_signed_in_pages_carry_the_new_pieces(net):
    """Welcome bands, fit badges, the listing funnel, the candidate pipeline and the reviewer desk."""
    from test_network import admin
    s1, sid1 = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    s1.get(f"/job/{job}")
    home = s1.get("/").text
    assert 'class="gal"' in home and 'class="statrow"' in home and "% match" in home and "worth your time" in home     # The Gallery
    ehome = emp.get("/").text
    assert 'class="ed-hello"' in ehome and "Candidate pipeline" in ehome and "viewed" in ehome        # the hiring dashboard
    t = ucsrf(emp)
    emp.post(f"/hiring/{job}/save", data={"csrf": t, "student": sid1})
    page = emp.get(f"/hiring/{job}?tab=candidates").text
    assert 'class="stats funnel' in page and 'style="--f:1.000"' in page         # one viewer, measured against itself
    assert 'class="pipe"' in page and "Not moving forward" in page
    a = admin(net)
    queue = a.get("/admin").text
    assert 'class="desk"' in queue and "<kbd>J</kbd>" in queue and 'class="qtabs"' in queue


def test_risk_gauge_follows_the_score():
    import ui
    assert [ui.risk_position(x)[0] for x in (0, 25, 26, 50, 51, 75, 76, 100)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert ui.risk_position(37)[1] == 37 and ui.risk_position(100, "held")[1] == 96      # the marker sits at the score, never 0 or 100
    assert ui.risk_position(0)[1] == 4
    zone, pos, _ = ui.risk_position(0, "flagged", aggregator=True)
    assert zone == 2 and pos == 60                                                       # aggregators sit at 60
    html = ui.risk_meter(0, "flagged", aggregator=True)
    assert "Scam risk 60 of 100" in html and '<span class="rl">60</span>' in html
    assert '<span class="rl">93</span>' in ui.risk_meter(93, "held")
