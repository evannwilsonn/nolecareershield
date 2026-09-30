"""The applicant table (/hiring/applicants): every candidate across an employer's listings, filters, sorting,
bulk stage moves and archive, private rating and note, privacy rules and pagination."""
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401
from test_easy_network import apply_form, easy_job  # noqa: E402


def _rows(html):
    return re.findall(r'<tr id="a(\d+)-(\d+)">', html)


def _setup(net):
    emp, eid = employer(net)
    job1 = add_job(net, eid)                                                  # Data Analyst Intern
    job2 = easy_job(net, eid, requirements=[{"kind": "skill", "label": "Excel", "must": True},
                                            {"kind": "skill", "label": "Photoshop", "must": True}])
    s1, sid1 = student(net)                                                   # Jordan: SQL/Python/Excel, visible
    s2, sid2 = student(net, "b@fsu.edu", "Blair B.", resume=None)             # visible, thin profile
    s3, sid3 = student(net, "c@fsu.edu", "Casey C.", visible=False)           # hidden, applies instead
    t = ucsrf(emp)
    emp.post(f"/hiring/{job1}/save", data={"csrf": t, "student": sid1})
    emp.post(f"/hiring/{job1}/save", data={"csrf": t, "student": sid2})
    assert s3.post(f"/job/{job2}/easy", data=apply_form(job2, ucsrf(s3))).status_code == 303
    return emp, eid, (job1, job2), (sid1, sid2, sid3), t


def test_table_lists_every_candidate_across_listings(net):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    over = emp.get("/hiring").text
    assert 'href="/hiring/applicants"' in over and "All applicants (3)" in over
    page = emp.get("/hiring/applicants")
    assert page.status_code == 200
    html = page.text
    rows = _rows(html)
    assert len(rows) == 3 and {(int(j), int(s)) for j, s in rows} == {(job1, sid1), (job1, sid2), (job2, sid3)}
    # columns: student with major and class, listing, source, stage, match %, N/M requirements, date, rating, note
    assert "Jordan R." in html and "Statistics · Class of 2027" in html
    assert "Data Analyst Intern" in html and "Marketing Intern" in html
    assert ">Applied<" in html and "Saved from matches" in html
    assert re.search(r'class="at-pct \w+">\d+%<', html)
    assert re.search(r"<b>\d+/\d+</b>", html) and "Photoshop" in html and "Required" in html     # expandable ✓/⊘/? list
    assert 'name="rating"' in html and 'name="note"' in html and "★★★★★" in html
    # the default sort is best match first
    order = [int(s) for _, s in rows]
    pcts = [int(p) for p in re.findall(r'class="at-pct \w+">(\d+)%<', html)]
    assert pcts == sorted(pcts, reverse=True) and len(order) == 3
    # a hidden student who applied is visible (they chose to apply), but the resume never appears in the table
    assert "Casey C." in html and "Data Intern, Leon County" not in html
    # every row control and bulk checkbox belongs to a form; forms carry the CSRF token
    assert html.count('form="bulk"') == 3 and 'action="/hiring/applicants/bulk"' in html and html.count('action="/hiring/applicants/row"') == 3


def test_filters_and_sorts(net):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    only = _rows(emp.get(f"/hiring/applicants?job={job2}").text)
    assert only == [(str(job2), str(sid3))]
    assert _rows(emp.get("/hiring/applicants?source=saved").text) and all(j == str(job1) for j, _ in _rows(emp.get("/hiring/applicants?source=saved").text))
    assert _rows(emp.get("/hiring/applicants?source=applied").text) == [(str(job2), str(sid3))]
    assert _rows(emp.get("/hiring/applicants?stage=offer").text) == []
    assert "No applicants match those filters" in emp.get("/hiring/applicants?stage=offer").text
    names = re.findall(r'<div class="nm"><a [^>]*>([^<]+)</a>', emp.get("/hiring/applicants?sort=name").text)
    assert names == sorted(names, key=str.lower)
    # min match and "meets all required" filter the rows by the fit engine's numbers
    all_rows = emp.get("/hiring/applicants").text
    pcts = [int(p) for p in re.findall(r'class="at-pct \w+">(\d+)%<', all_rows)]
    hi = max(pcts)
    kept = emp.get(f"/hiring/applicants?min={50 if hi >= 50 else 25}").text
    assert all(int(p) >= (50 if hi >= 50 else 25) for p in re.findall(r'class="at-pct \w+">(\d+)%<', kept))
    req = emp.get("/hiring/applicants?req=1").text
    assert (str(job2), str(sid3)) not in _rows(req)                           # Casey doesn't list Photoshop
    # junk parameters are ignored, not errors
    assert emp.get("/hiring/applicants?job=abc&min=999&sort=evil&stage=<x>&page=-4").status_code == 200


def test_bulk_move_archive_restore_and_row_edit(net):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    r = emp.post("/hiring/applicants/bulk", data={"csrf": t, "sel": [f"{job1}:{sid1}", f"{job1}:{sid2}"], "do": "stage", "stage": "interviewing",
                                                  "back": "/hiring/applicants?sort=name"})
    assert r.status_code == 303 and r.headers["location"].startswith("/hiring/applicants?sort=name&done=moved&n=2")
    assert "Moved 2 to Interviewing" in emp.get(r.headers["location"]).text
    assert len(_rows(emp.get("/hiring/applicants?stage=interviewing").text)) == 2
    # nothing selected: a hint, no change
    r = emp.post("/hiring/applicants/bulk", data={"csrf": t, "do": "archive", "back": "/hiring/applicants"})
    assert "done=none" in r.headers["location"]
    # bad CSRF and off-site "back" are refused
    r = emp.post("/hiring/applicants/bulk", data={"csrf": "nope", "sel": [f"{job1}:{sid1}"], "do": "archive", "back": "https://evil.example/"})
    assert r.headers["location"] == "/hiring/applicants"
    assert len(_rows(emp.get("/hiring/applicants").text)) == 3
    # archive hides them from the table and the listing's tracker; restore brings them back
    emp.post("/hiring/applicants/bulk", data={"csrf": t, "sel": [f"{job1}:{sid2}"], "do": "archive", "back": "/hiring/applicants"})
    assert (str(job1), str(sid2)) not in _rows(emp.get("/hiring/applicants").text)
    assert _rows(emp.get("/hiring/applicants?show=archived").text) == [(str(job1), str(sid2))]
    assert "Blair B." not in emp.get(f"/hiring/{job1}?tab=candidates").text
    emp.post("/hiring/applicants/bulk", data={"csrf": t, "sel": [f"{job1}:{sid2}"], "do": "restore", "back": "/hiring/applicants?show=archived"})
    assert len(_rows(emp.get("/hiring/applicants").text)) == 3
    # quick per-row edit: stage, 1-5 rating and a private note (escaped, never shown to the student)
    r = emp.post("/hiring/applicants/row", data={"csrf": t, "job": job2, "student": sid3, "stage": "offer", "rating": "4",
                                                 "note": "<b>strong</b> writer", "back": "/hiring/applicants"})
    assert r.status_code == 303 and r.headers["location"].endswith(f"#a{job2}-{sid3}")
    html = emp.get("/hiring/applicants?sort=rating").text
    assert _rows(html)[0] == (str(job2), str(sid3))                         # rated first
    assert "&lt;b&gt;strong&lt;/b&gt; writer" in html and re.search(r'<option value="4" selected>★★★★☆</option>', html)
    assert 'value="offer" selected' in html
    student_c = net.clients[-1]
    assert "strong" not in student_c.get("/applications").text
    # ratings outside 1-5 are ignored
    emp.post("/hiring/applicants/row", data={"csrf": t, "job": job2, "student": sid3, "stage": "offer", "rating": "9", "note": "x", "back": ""})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT rating, note FROM candidates WHERE job_id = ? AND student_id = ?", (job2, sid3)).fetchone() == (4, "<b>strong</b> writer")


def test_privacy_other_employers_and_hidden_students(net):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    other, oid = employer(net, "hr@beta.example", company="Beta Co")
    ot = ucsrf(other)
    assert _rows(other.get("/hiring/applicants").text) == []
    # another employer can't move or rate someone else's candidates
    other.post("/hiring/applicants/bulk", data={"csrf": ot, "sel": [f"{job1}:{sid1}"], "do": "stage", "stage": "hired", "back": ""})
    other.post("/hiring/applicants/row", data={"csrf": ot, "job": job1, "student": sid1, "stage": "hired", "rating": "1", "note": "x", "back": ""})
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        assert db.execute("SELECT stage, rating FROM candidates WHERE job_id = ? AND student_id = ?", (job1, sid1)).fetchone() == ("new", 0)
    # a saved student who later hides their profile (and never applied or messaged) drops out of the table
    with closing(sqlite3.connect(net.app.DB_PATH)) as db:
        db.execute("UPDATE student_profiles SET visible_to_employers = 0 WHERE user_id = ?", (sid2,))
        db.commit()
    assert (str(job1), str(sid2)) not in _rows(emp.get("/hiring/applicants").text)
    # employers not yet approved get a banner, no rows
    pend, pid = employer(net, "hr@gamma.example", approve=False, company="Gamma Co")
    assert "opens once a reviewer approves" in pend.get("/hiring/applicants").text
    # students can't open it
    s = net.clients[1]
    assert s.get("/hiring/applicants").status_code in (303, 403, 404)


def test_export_and_deletion_cover_ratings_and_notes(net):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    emp.post("/hiring/applicants/row", data={"csrf": t, "job": job1, "student": sid1, "stage": "reviewing", "rating": "5", "note": "call back", "back": ""})
    data = json.loads(emp.get("/profile/export").text)
    row = [r for r in data["candidate_tracker"] if r["student_id"] == sid1][0]
    assert row["rating"] == 5 and row["note"] == "call back"
    # the student's own export never contains the employer's private rating or note
    stu = net.clients[1]
    assert "call back" not in stu.get("/profile/export").text
    import store
    with store.db() as conn:
        store.delete_account(conn, sid1)
        assert conn.execute("SELECT COUNT(*) FROM candidates WHERE student_id = ?", (sid1,)).fetchone()[0] == 0


def test_pagination(net, monkeypatch):
    emp, eid, (job1, job2), (sid1, sid2, sid3), t = _setup(net)
    import hiring
    monkeypatch.setattr(hiring, "PAGE_SIZE", 2)
    p1 = emp.get("/hiring/applicants?sort=name").text
    assert len(_rows(p1)) == 2 and "Page 1 of 2" in p1 and 'href="/hiring/applicants?sort=name&amp;page=2"' in p1
    p2 = emp.get("/hiring/applicants?sort=name&page=2").text
    assert len(_rows(p2)) == 1 and "Page 2 of 2" in p2 and "← Previous" in p2
    assert not set(_rows(p1)) & set(_rows(p2))
    assert "Page 2 of 2" in emp.get("/hiring/applicants?sort=name&page=99").text
