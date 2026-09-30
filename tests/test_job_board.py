"""The two-pane job board: list and detail, filters, saved jobs, the match panel and the qualifications block."""
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


def test_layout_tabs_search_chips_and_two_panes(net):
    emp, eid = employer(net)
    a = job(net, eid)
    b = job(net, eid, "Front Desk Assistant", category="Admin & Office", work_type="on-site", location="Miami, FL",
            description="Greet visitors, answer phones and keep the front desk tidy. Part-time, weekday afternoons. Paid $15/hour.")
    s, sid = student(net)
    page = s.get("/jobs").text
    for label in (">Jobs</a>", ">Resume optimizer</a>", "Describe a job you want", "Full-time", "Internship", "Part-time", "Date posted", "Quick apply",
                  "From companies I follow", "Filters", "Location", "Sort by Most relevant"):
        assert label in page, label
    assert 'class="jb-grid"' in page and 'class="jb-pane"' in page and ".jb-grid" in page                    # two panes, css in the shared sheet
    assert 'href="/resume"' in page and 'href="/jobs?tab=saved"' in page
    assert "Easy apply" not in page
    # the first result is open in the detail pane and every card keeps the scam pill
    assert page.count("Scam risk") >= 3 and "Job match is" in page and "What they’re looking for" in page and "At a glance" in page
    # the list links: desktop to the same board, phones to the full page
    assert f'href="/jobs?job={b}"' in page and f'href="/job/{b}"' in page
    other = s.get(f"/jobs?job={b}").text
    pane = other.split('class="jb-pane"')[1]
    assert "Front Desk Assistant" in pane and "Greet visitors" in pane
    assert "Greet visitors" not in page.split('class="jb-pane"')[1] or a > b                            # default pane is the top-ranked one
    assert 'class="jc sel"' in other and other.count('class="jc sel"') == 1
    # a bogus job param falls back instead of failing
    assert s.get("/jobs?job=99999&when=zz&kind=x&sort=q").status_code == 200


def test_filters_and_natural_language_search(net):
    emp, eid = employer(net)
    job(net, eid)
    job(net, eid, "Front Desk Assistant", category="Admin & Office", work_type="on-site", location="Miami, FL",
        description="Greet visitors, answer phones and keep the front desk tidy. Part-time, weekday afternoons. Paid $15/hour.")
    job(net, eid, "Marketing Intern", category="Marketing", work_type="hybrid", location="Tallahassee, FL", easy_apply=1,
        description="Help our marketing team with campaigns and social posts. Internship. Paid $17/hour.", apply_url="")
    s, sid = student(net)

    def titles(qs):
        return re.findall(r'class="jc-link jc-m" href="/job/\d+">([^<]+)</a>', s.get("/jobs" + qs).text)
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
    assert "Data Analyst Intern" in saved.split('class="jb-list"')[1].split('class="jb-pane"')[0] and "Marketing Intern" not in saved.split('class="jb-pane"')[0].split('class="jb-list"')[1]
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
    assert f'href="/resume?tab=tailor&amp;job={a}"' in page and "Tailor my resume" in page and "Help me stand out" in page
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
    for path in (f"/job/{a}", f"/jobs?job={a}"):
        page = emp.get(path).text
        assert "What they’re looking for" in page and "SQL" in page and "Required" in page and "Preferred" in page
        assert "You match" not in page and "Job match is" not in page and "Update profile" not in page
        assert "This is your listing" in page
    assert "Tailor my resume" not in emp.get(f"/jobs?job={a}").text


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
    for path in ("/jobs", f"/job/{a}", f"/jobs?job={a}", "/about", "/privacy", f"/job/{a}/easy", "/applications"):
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
    for path in ("/jobs", f"/jobs?job={a}", "/jobs?tab=saved"):
        html = s.get(path).text
        assert "<script" not in html.replace('<script src="/static/fx.js', "") and " onclick=" not in html and "javascript:" not in html
