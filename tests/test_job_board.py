"""The job board: filter rail and result cards, the listing page, filters, saved jobs, the match card and the qualifications block."""
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401

QUALS = [{"kind": "skill", "label": "SQL", "must": True}, {"kind": "skill", "label": "Tableau", "must": False},
         {"kind": "major", "label": "Statistics", "must": True}, {"kind": "gpa", "label": "3.0", "must": False}]


def job(n, eid, title="Data Analyst Intern", **kw):
    data = {"title": title, "company": "Acme Analytics", "category": "Data & Analytics", "work_type": "remote", "location": "Tallahassee, FL",
            "description": "Summer data internship. Use SQL and Tableau to build dashboards for city clients. Paid $18/hour. Apply on our careers page.",
            "apply_url": "https://acme.example/careers", "contact": ""}
    data.update(kw)
    j = n.app.add_job(data, employer_id=eid)
    n.app.set_review(j["id"], "approved", "legit")
    return j["id"]


def rows(n, sql, *a):
    with closing(sqlite3.connect(n.app.DB_PATH)) as db:
        return db.execute(sql, a).fetchall()


def test_layout_rail_segmented_tabs_and_one_column_of_cards(net):
    emp, eid = employer(net)
    a = job(net, eid)
    b = job(net, eid, "Front Desk Assistant", category="Admin & Office", work_type="on-site", location="Miami, FL",
            description="Greet visitors, answer phones and keep the front desk tidy. Part-time, weekday afternoons. Paid $15/hour.")
    s, sid = student(net)
    page = s.get("/jobs").text
    for label in (">Jobs</a>", ">Resume optimizer</a>", "Describe a job you want", "Full-time", "Internship", "Part-time", "Date posted", "Quick apply",
                  "From companies I follow", "Filters", "Location", "Work setting", "Category", "Sort by Most relevant"):
        assert label in page, label
    # tabs are a segmented control beside the search; filters are a rail of <details> sections plus one fold for phones
    top = page.split('class="jb-top"')[1].split('class="jb-grid')[0]
    assert 'class="jb-search"' in top and 'class="jb-seg"' in top and 'href="/resume"' in top and 'href="/jobs?tab=saved"' in top
    rail = page.split('class="jb-rail"')[1].split("</aside>")[0]
    assert rail.count('<details class="jb-sec"') == 6 and 'class="jb-mf"' in page and ".jb-rail" in page and ".jb-mf" in page
    assert 'class="jb-chips"' not in page                                                                # no chip row any more
    assert "Easy apply" not in page
    # one column of cards, no detail pane: each card links to the listing page and keeps the scam pill
    assert 'class="jb-pane"' not in page and "Job match is" not in page and "At a glance" not in page
    assert f'href="/job/{a}"' in page and f'href="/job/{b}"' in page and "/jobs?job=" not in page
    assert page.count("Scam risk") >= 2 and page.count('<article class="jc v-clear z0"') == 2
    # the old pane address sends people to the listing page
    r = s.get(f"/jobs?job={b}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"/job/{b}"
    assert s.get("/jobs?job=abc&when=zz&kind=x&sort=q").status_code == 200                             # bogus params fall back


def test_card_edge_follows_the_verdict(net):
    emp, eid = employer(net)
    a = job(net, eid)
    s, sid = student(net)
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE jobs SET scam_status = 'flagged', score = 40 WHERE id = ?", (a,))
        db.commit()
    page = s.get("/jobs").text
    assert '<article class="jc v-flagged z1"' in page
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE jobs SET score = 90 WHERE id = ?", (a,))
        db.commit()
    assert '<article class="jc v-flagged z3"' in s.get("/jobs").text
    assert 'class="jd v-flagged z3"' in s.get(f"/job/{a}").text


def test_listing_page_two_columns(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=QUALS)
    s, sid = student(net)
    page = s.get(f"/job/{a}").text
    art = page.split('<article class="jd')[1]
    top, rest = art.split('<aside class="jd-side"')
    side, body = rest.split('<div class="jd-body">')
    assert "<h1" in top and "Data Analyst Intern" in top and "Apply →" in top and "Save" in top and "About the job" not in top
    for part in ('class="js"', "Scam check", 'class="jm"', "What they’re looking for"):
        assert part in side, part
    assert side.index("Scam check") < side.index("Job match is") < side.index("What they’re looking for")
    assert "About the job" in body and "At a glance" in body and body.index("About the job") < body.index("At a glance")
    assert "Tailor your resume to this job" in body                                                      # the tailoring kit stays on the page
    assert ".jd-side" in page and "position:sticky" in page


def test_ai_action_row_links(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=QUALS)
    s, sid = student(net)
    row = s.get(f"/job/{a}").text.split('class="jm-ai"')[1].split("</section>")[0]
    assert "<details" in row and "Show match details" in row
    assert f'href="/job/{a}/tailor"' in row and "Tailor my resume" in row
    assert f'href="/job/{a}/standout"' in row and "Help me stand out" in row
    assert f'href="/job/{a}/tailor?mode=note"' in row and "Draft a note to the poster" in row


def test_filters_and_natural_language_search(net):
    emp, eid = employer(net)
    job(net, eid)
    job(net, eid, "Front Desk Assistant", category="Admin & Office", work_type="on-site", location="Miami, FL",
        description="Greet visitors, answer phones and keep the front desk tidy. Part-time, weekday afternoons. Paid $15/hour.")
    job(net, eid, "Marketing Intern", category="Marketing", work_type="hybrid", location="Tallahassee, FL", easy_apply=1,
        description="Help our marketing team with campaigns and social posts. Internship. Paid $17/hour.", apply_url="")
    s, sid = student(net)

    def titles(qs):
        return re.findall(r'class="jc-link" href="/job/\d+">([^<]+)</a>', s.get("/jobs" + qs).text)
    assert sorted(titles("")) == ["Data Analyst Intern", "Front Desk Assistant", "Marketing Intern"]
    assert titles("?kind=part-time") == ["Front Desk Assistant"]
    assert sorted(titles("?kind=internship")) == ["Data Analyst Intern", "Marketing Intern"]
    assert titles("?quick=1") == ["Marketing Intern"]
    assert titles("?loc=Miami%2C+FL") == ["Front Desk Assistant"]
    assert titles("?work_type=remote") == ["Data Analyst Intern"]
    assert titles("?category=Marketing") == ["Marketing Intern"]
    assert titles("?when=1").__len__() == 3 and titles("?when=7").__len__() == 3
    assert titles("?search=part-time+front+desk+job") == ["Front Desk Assistant"]                 # matching.parse_query reads the sentence
    assert titles("?search=acme") and len(titles("?search=acme")) == 3                            # company names still work
    assert titles("?search=zzzzqq") == []
    assert "No listings match" in s.get("/jobs?search=zzzzqq").text
    # most recent puts the newest first
    assert titles("?sort=recent")[0] == "Marketing Intern"
    # an old listing drops out of "past 24 hours"
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE jobs SET created_at = '2020-01-01T00:00:00' WHERE title = 'Front Desk Assistant'")
        db.commit()
    assert "Front Desk Assistant" not in titles("?when=7")
    # companies I follow
    assert titles("?following=1") == []
    t = ucsrf(s)
    s.post("/network/follow", data={"csrf": t, "employer": eid, "next": "/jobs"})
    assert len(titles("?following=1")) == 3 or len(titles("?following=1")) == 2


def test_save_unsave_and_saved_tab(net):
    emp, eid = employer(net)
    a = job(net, eid)
    b = job(net, eid, "Marketing Intern", category="Marketing")
    s, sid = student(net)
    assert "No saved jobs yet" in s.get("/jobs?tab=saved").text
    t = ucsrf(s)
    r = s.post(f"/job/{a}/save", data={"csrf": t, "next": "/jobs?kind=internship"})
    assert r.status_code == 303 and r.headers["location"] == "/jobs?kind=internship"
    assert rows(net, "SELECT job_id FROM saved_jobs WHERE user_id = ?", sid) == [(a,)]
    s.post(f"/job/{a}/save", data={"csrf": t})                                                       # twice is still one
    assert len(rows(net, "SELECT * FROM saved_jobs")) == 1
    page = s.get("/jobs").text
    assert "Remove from saved jobs" in page and "Save job" in page and "Saved (1)" in page
    saved = s.get("/jobs?tab=saved").text
    assert "Data Analyst Intern" in saved.split('class="jb-list"')[1] and "Marketing Intern" not in saved.split('class="jb-list"')[1]
    assert 'class="jb-rail"' not in saved and 'class="jb-grid solo"' in saved
    assert "1 saved job" in saved
    # open redirect and forged posts go nowhere
    r = s.post(f"/job/{a}/unsave", data={"csrf": t, "next": "https://evil.example/"})
    assert r.headers["location"] == f"/job/{a}" and rows(net, "SELECT * FROM saved_jobs") == []
    s.post(f"/job/{b}/save", data={"csrf": "forged", "next": "/jobs"})
    assert rows(net, "SELECT * FROM saved_jobs") == []
    # unapproved or missing listings can't be saved
    assert s.post("/job/9999/save", data={"csrf": t}).status_code == 303 and rows(net, "SELECT * FROM saved_jobs") == []
    # employers and visitors can't save
    assert emp.post(f"/job/{a}/save", data={"csrf": ucsrf(emp)}).status_code in (303, 403) and rows(net, "SELECT * FROM saved_jobs") == []
    assert "Save job" not in emp.get("/jobs").text and "Saved (" not in emp.get("/jobs").text
    assert net.client().post(f"/job/{a}/save", data={"csrf": "x"}).status_code in (303, 401, 403)
    # exported with the account and gone when it is deleted
    s.post(f"/job/{a}/save", data={"csrf": t})
    assert json.loads(s.get("/profile/export").text)["saved_jobs"][0]["job_id"] == a
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        import store
        store.delete_account(db, sid)
        assert db.execute("SELECT COUNT(*) FROM saved_jobs").fetchone()[0] == 0


def test_saved_rows_go_with_their_listing(net):
    emp, eid = employer(net)
    a = job(net, eid)
    s, sid = student(net)
    s.post(f"/job/{a}/save", data={"csrf": ucsrf(s)})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("DELETE FROM jobs WHERE id = ?", (a,))
        import store
        store.purge(db)
        assert db.execute("SELECT COUNT(*) FROM saved_jobs").fetchone()[0] == 0


def test_match_panel_and_qualifications_for_students(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=QUALS)
    s, sid = student(net)                                                                            # Statistics major, Python SQL Excel Tableau R
    page = s.get(f"/job/{a}").text
    assert "Job match is" in page and re.search(r"Job match is <span class=\"jm-lvl (high|medium|low)\">(High|Medium|Low)</span>", page)
    pct = int(re.search(r'class="jm-pct">(\d+)%<', page).group(1))
    assert 0 <= pct <= 100 and "top applicant" not in page.lower()
    assert "Show match details" in page and "<details" in page and 'class="jm-meter' in page
    assert f'href="/job/{a}/tailor"' in page and "Tailor my resume" in page and "Help me stand out" in page
    q = page.split('class="jq"')[1].split("</section>")[0]
    assert "What they’re looking for" in q and re.search(r"You match \d+ of \d+ qualifications", q) and "Update profile" in q
    assert "Matching is based on your profile" in q
    assert 'class="met"' in q and 'class="rq required">Required' in q and 'class="rq preferred">Preferred' in q
    assert "⊘" in q or "✓" in q
    # the card shows the same percentage
    assert f"{pct}% match" in s.get("/jobs").text
    # scam information stays on the card and the detail
    assert "Scam risk" in page and 'class="risk' in page and "passed the scam check" in page


def test_missing_and_unknown_marks(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=[{"kind": "skill", "label": "Photoshop", "must": True}, {"kind": "gpa", "label": "3.9", "must": False},
                                    {"kind": "cert", "label": "Notary", "must": False}])
    s, sid = student(net)
    q = s.get(f"/job/{a}").text.split('class="jq"')[1].split("</section>")[0]
    assert 'class="missing"' in q and "⊘" in q and "Photoshop" in q and "Notary" in q


def test_employer_sees_qualifications_without_a_personal_match(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=QUALS)
    for path in (f"/job/{a}",):
        page = emp.get(path).text
        assert "What they’re looking for" in page and "SQL" in page and "Required" in page and "Preferred" in page
        assert "You match" not in page and "Job match is" not in page and "Update profile" not in page
        assert "This is your listing" in page
    assert "Tailor my resume" not in emp.get(f"/job/{a}").text and 'class="jb-seg"' not in emp.get("/jobs").text


def test_profile_thin_student_gets_a_prompt(net):
    emp, eid = employer(net)
    a = job(net, eid)
    s, sid = student(net, resume="")
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE student_profiles SET skills = '[]', resume_text = '' WHERE user_id = ?", (sid,))
        db.execute("DELETE FROM profile_items WHERE user_id = ?", (sid,))
        db.commit()
    page = s.get(f"/job/{a}").text
    assert "Build my profile" in page and "% match" not in s.get("/jobs").text


def test_quick_apply_name_everywhere(net):
    emp, eid = employer(net)
    a = job(net, eid, easy_apply=1, apply_url="", questions=[{"q": "Why this role?", "kind": "long", "required": True}])
    s, sid = student(net)
    for path in ("/jobs", f"/job/{a}", "/about", "/privacy", f"/job/{a}/easy", "/applications"):
        text = s.get(path).text
        assert "Easy apply" not in text and "easy apply" not in text, path
    page = s.get(f"/job/{a}").text
    assert "Quick apply →" in page and "Quick apply" in s.get("/jobs").text
    assert "Quick apply" in emp.get("/post").text and "Easy apply" not in emp.get("/post").text


def test_visitors_are_sent_to_log_in(net):
    c = net.client()
    assert c.get("/jobs").headers["location"] == "/login?next=/jobs"
    assert c.get("/job/1").status_code == 303


def test_pages_stay_csp_clean(net):
    emp, eid = employer(net)
    a = job(net, eid, requirements=QUALS)
    s, _ = student(net)
    for path in ("/jobs", f"/job/{a}", "/jobs?tab=saved"):
        html = s.get(path).text
        assert "<script" not in html.replace('<script src="/static/fx.js', "").replace('<script src="/static/app.js', "") and " onclick=" not in html and "javascript:" not in html
