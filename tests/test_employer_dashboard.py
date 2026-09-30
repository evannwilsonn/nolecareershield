"""Employer experience: nav cleanup, the hiring dashboard, company Page stats, and the "Hiring at a glance" fix."""
import os
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401


def _db(n):
    return closing(sqlite3.connect(n.app.DB_PATH))


def _side(html):
    return html[html.index('<aside class="side">'):html.index("</aside>")]


def test_employer_nav_and_jobs_redirect(net):
    emp, eid = employer(net)
    s, _ = student(net)
    side = _side(emp.get("/hiring").text)
    assert 'href="/jobs"' not in side and 'href="/check"' not in side and "Stay safe" not in side and "Your listings" in side
    assert 'href="/check">Scam check</a>' in emp.get("/hiring").text.split("<footer>")[1]      # still reachable from the footer
    r = emp.get("/jobs?search=x")
    assert r.status_code == 303 and r.headers["location"] == "/hiring"
    sside = _side(s.get("/jobs").text)
    assert 'href="/jobs"' in sside and "Stay safe" in sside and 'href="/check"' in sside         # students keep theirs


def test_dashboard_queue_pipeline_and_listing_rows(net):
    emp, eid = employer(net)
    job = add_job(net, eid)
    other = add_job(net, eid, title="Research Assistant")
    s1, sid1 = student(net)
    s2, sid2 = student(net, "b@fsu.edu", "Blair B.")
    for c in (s1, s2):
        c.get(f"/job/{job}")
    t1 = ucsrf(s1)
    s1.post("/messages/new", data={"csrf": t1, "to": eid, "job": job, "body": "Hi! Is the Data Analyst Intern role still open?"})
    home = emp.get("/").text
    assert 'class="ed-hello"' in home and "Acme Analytics" in home
    assert "<b>1 new applicant</b> to review" in home and f'href="/hiring/{job}?tab=candidates"' in home
    assert "<b>1 student message</b> waiting for a reply" in home
    assert 'href="/post"' in home and 'href="/talent"' in home and 'href="/messages"' in home     # quick actions
    assert "Candidate pipeline" in home and '<span class="n">1</span><span class="l">New</span>' in home
    row = home[home.index(">Data Analyst Intern</a>"):]
    row = row[:row.index('<div class="ed-row">') if '<div class="ed-row">' in row else len(row)]
    assert "<b>2</b><span>viewed</span>" in row and "<b>1</b><span>applicants</span>" in row and re.search(r"<b>\d+%</b><span>avg match</span>", row)
    assert f'href="/job/{job}">Preview as students see it' in row
    assert f'href="/job/{other}">Preview as students see it' in home
    # Replying clears the message item; moving the candidate on clears the applicant item.
    cid = int(re.search(r"/messages/(\d+)", emp.get("/messages").text).group(1))
    t = ucsrf(emp)
    emp.post(f"/messages/{cid}/send", data={"csrf": t, "body": "Yes it is. Apply on our careers page."})
    emp.post(f"/hiring/{job}/stage", data={"csrf": t, "student": sid1, "stage": "reviewing", "note": ""})
    home = emp.get("/").text
    assert "waiting for a reply" not in home and "new applicant" not in home
    assert '<span class="n">1</span><span class="l">Reviewing</span>' in home
    # The hiring page's listing header links the student view too.
    assert f'href="/job/{job}">Preview as students see it' in emp.get(f"/hiring/{job}").text


def test_dashboard_profile_gap_expiry_and_events_guards(net):
    emp, eid = employer(net)
    job = add_job(net, eid)
    home = emp.get("/").text
    assert "Your company profile is missing" in home and "a tagline" in home          # from the trust card's tips
    assert "expires" not in home and "Upcoming events" not in home                     # no expires_at column / events table yet (guards)
    with _db(net) as db:
        if "expires_at" not in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}:
            db.execute("ALTER TABLE jobs ADD COLUMN expires_at REAL")
        db.execute("UPDATE jobs SET expires_at = ? WHERE id = ?", (time.time() + 3 * 86400 + 60, job))
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, employer_id INTEGER, title TEXT, starts_at REAL)")
        db.execute("INSERT INTO events (employer_id, title, starts_at) VALUES (?,?,?)", (eid, "Summer internship info session", time.time() + 86400))
        db.commit()
    home = emp.get("/").text
    assert "<b>Data Analyst Intern</b> expires in 3 days" in home
    assert "Upcoming events" in home and "Summer internship info session" in home
    pend, _ = employer(net, "hr@beta.example", approve=False, company="Beta Co")
    assert "waiting for a reviewer" in pend.get("/").text


def test_company_page_stats_views_followers_majors(net):
    emp, eid = employer(net)
    job = add_job(net, eid)
    other, _ = employer(net, "hr@beta.example", company="Beta Co")
    studs = [student(net, f"s{i}@fsu.edu", f"Student {n}") for i, n in enumerate("ABC")]
    s0, sid0 = studs[0]
    for _ in range(3):
        s0.get(f"/company/{eid}")                                        # once per student per day
    other.get(f"/company/{eid}")                                         # employers aren't counted
    emp.get(f"/company/{eid}")                                           # nor the owner
    s0.get(f"/job/{job}")
    studs[1][0].get(f"/job/{job}")
    s0.post("/network/follow", data={"csrf": ucsrf(s0), "employer": eid})
    own = emp.get("/profile").text
    ps = own[own.index('id="page-stats"'):]
    ps = ps[:ps.index("</section>")]
    assert "<b>1</b><span>company page views</span>" in ps and "<b>1</b><span>followers</span>" in ps and "+1 in the last 30 days" in ps
    assert "<b>2</b><span>listing views</span>" in ps
    assert "Majors show once at least 3 students" in ps and "Statistics" not in ps          # 2 students: under the privacy floor
    studs[2][0].get(f"/job/{job}")
    ps = emp.get("/profile").text
    ps = ps[ps.index('id="page-stats"'):]
    ps = ps[:ps.index("</section>")]
    assert "Statistics" in ps and "under 5" in ps and "Student A" not in ps and "s0@fsu.edu" not in ps
    assert 'id="page-stats"' not in s0.get(f"/company/{eid}").text                           # owner only
    # Deleting a student keeps the employer's total but drops who; deleting the employer drops the rows.
    import store
    with _db(net) as db:
        store.delete_account(db, sid0)
        assert db.execute("SELECT COUNT(*), COUNT(viewer_id) FROM company_views WHERE employer_id = ?", (eid,)).fetchone() == (1, 0)
        store.delete_account(db, eid)
        assert db.execute("SELECT COUNT(*) FROM company_views").fetchone()[0] == 0
        db.execute("INSERT INTO company_views (employer_id, viewer_id, day) VALUES (?,?,?)", (999, 1, "2020-01-01"))
        db.commit()
        store.purge(db)
        assert db.execute("SELECT COUNT(*) FROM company_views").fetchone()[0] == 0


def test_fold_majors_privacy():
    import employer_dash as ed
    assert ed.fold_majors([("Statistics", 2)], 2) is None
    out = ed.fold_majors([("Statistics", 12), ("Marketing", 3), ("Geology", 1)], 16)
    assert out[0] == ("Statistics", "about 10", 75) and out[1][0] == "Marketing" and out[-1][0] == "Other majors"
    assert all(m != "Geology" for m, _, _ in out)                       # a single student's major is folded away
    assert ed.round_count(3) == "under 5" and ed.round_count(13) == "about 15"


# ---------- regression: "Hiring at a glance" showed 0 open / 0 reviewed with 2 live listings ----------

def test_hiring_at_a_glance_counts_live_listings(net):
    emp, eid = employer(net)
    add_job(net, eid)
    add_job(net, eid, title="Research Assistant")
    s, _ = student(net)
    for page in (emp.get("/profile").text, s.get(f"/company/{eid}").text):
        g = page[page.index("Hiring at a glance"):]
        assert '<div class="n">2</div><div class="l">open listings</div>' in g and '<div class="n">2</div><div class="l">listings reviewed</div>' in g
        assert '<div class="pgrid co">' in page                           # the tall side column scrolls with the page
    # The cause was the count-up: fx.js zeroed every number up front and only restored it once it scrolled into view,
    # which a number low in the (sticky) side column never did. Now only numbers already on screen start at 0.
    fx = (ROOT / "static" / "fx.js").read_text()
    arm = fx[fx.index("function arm()"):]
    arm = arm[:arm.index("\n  }\n")]
    assert 'el.__count = +t; el.textContent = "0"' not in arm and "r.top < vh" in arm


def _browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path("/opt/pw-browsers").exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    return sync_playwright


def test_glance_numbers_in_a_real_browser(tmp_path):
    """Site markup + the real fx.js in Chromium: numbers below the fold must read true without scrolling."""
    sp = _browser()
    fx = (ROOT / "static" / "fx.js").read_text()
    page_html = ('<!doctype html><html><body><div class="kpi"><span class="n" id="top">7</span></div>'
                 '<div style="height:3000px"></div><div class="stat"><div class="n" id="low">2</div></div>'
                 f"<script>{fx}</script></body></html>")
    f = tmp_path / "p.html"
    f.write_text(page_html)
    with sp() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                                          # no browser in this environment
            pytest.skip(f"chromium unavailable: {e}")
        pg = b.new_page(viewport={"width": 390, "height": 800})
        pg.goto(f.as_uri())
        pg.wait_for_timeout(1500)
        assert pg.inner_text("#low") == "2" and pg.inner_text("#top") == "7"
        b.close()


def test_demo_employer_pages_in_a_real_browser():
    """The demo twin: dashboard, Page stats and the glance card, and no horizontal scroll at 390px."""
    sp = _browser()
    sys.path.insert(0, str(ROOT / "demo"))
    import build
    _, full = build.build()
    with sp() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        for w in (1440, 390):
            pg = b.new_page(viewport={"width": w, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(full.as_uri())
            pg.click('[data-do="as-employer"]')
            pg.wait_for_timeout(300)
            home = pg.inner_text("#app")
            assert "Needs your attention" in home and "Candidate pipeline" in home and "Preview as students see it" in home
            side = pg.inner_text("aside.side")
            assert "Jobs" not in side.split() and "Scam check" not in side and "Stay safe" not in side
            assert pg.evaluate("document.documentElement.scrollWidth") <= w
            pg.evaluate("() => { const a = document.createElement('a'); a.href = '#'; a.dataset.go = 'profile'; document.querySelector('#app').appendChild(a); a.click(); }")
            pg.wait_for_timeout(1200)
            nums = pg.evaluate("() => [...document.querySelectorAll('.stats.two .stat .n')].slice(0, 2).map(e => e.textContent)")
            assert nums == ["2", "2"], nums
            assert "Page stats" in pg.inner_text("#app") and pg.evaluate("document.documentElement.scrollWidth") <= w
            assert not errs, errs
            pg.close()
        b.close()
