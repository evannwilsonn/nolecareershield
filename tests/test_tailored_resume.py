"""The new resume: build_resume (tailored to a job or optimized in general), its HTML / text / Word / PDF
output, the /job/{id}/tailor, /standout and note pages, the studio's step 3, and the demo port.
Run: python -m pytest -q tests/test_tailored_resume.py"""
import io, json, re, shutil, subprocess, sys, zipfile
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import RESUME, add_job, employer, net, student, ucsrf  # noqa: E402,F401

EVAN = (ROOT / "tests" / "fixtures" / "resume_evan.txt").read_text()
DESC = "Summer data internship. Use SQL, Python and Tableau to build dashboards for city clients. Requires Power BI experience. Paid $18/hour."
JOB = {"id": 7, "title": "Data Analyst Intern", "company": "Acme Analytics", "category": "Data & Analytics", "description": DESC, "requirements": "[]",
       "work_type": "remote", "location": "Tallahassee, FL"}
PROF = {"display_name": "Jordan R.", "major": "Statistics", "grad_term": "Spring 2027", "skills": ["Python", "SQL", "Excel", "Power BI"],
        "links": {"linkedin": "linkedin.com/in/jordanrivera", "website": "github.com/jrivera"},
        "items": [{"kind": "project", "title": "Bus Tracker", "org": "", "start": "2025", "end": "", "current": True,
                   "description": "Built a bus arrival predictor in Python for 3 routes"}]}
TODAY = (2026, 9)


def nums(s):
    return set(re.findall(r"\d[\d,.]*\d|\d", s))


# ---------- engine ----------

def test_tailored_resume_is_complete_and_only_uses_the_students_facts():
    import resume_engine as re_, matching
    d = re_.build_resume(PROF, RESUME, JOB, today=TODAY)
    keys = [s["key"] for s in d["sections"]]
    assert keys == ["summary", "education", "experience", "projects", "skills"]
    assert d["name"] == "Jordan Rivera" and "github.com/jrivera" in d["contact"] and "jordan.rivera@fsu.edu" in d["contact"]
    kinds = [c["kind"] for c in d["changes"]]
    assert {"summary", "order", "rewrite", "skills", "profile"} <= set(kinds)
    assert [c["id"] for c in d["changes"]] == [f"c{i}" for i in range(1, len(kinds) + 1)] and all(c["on"] for c in d["changes"])
    exp = next(s for s in d["sections"] if s["key"] == "experience")
    assert exp["entries"][0]["head"] == "Data Intern, Leon County Health Department" and exp["entries"][0]["date"] == "Summer 2025"
    assert exp["entries"][0]["bullets"][0]["text"].startswith("Built SQL queries")              # most relevant bullet leads
    # nothing invented: every number and skill is the student's own (resume or profile)
    facts = RESUME + " " + json.dumps(PROF)
    assert nums(d["text"]) <= nums(facts)
    assert set(matching.extract_skills(d["text"])) <= set(matching.extract_skills(facts)) | set(PROF["skills"])
    assert "[add a number" not in d["text"] and "Responsible for" not in d["text"]
    assert "Power BI" in d["text"]                                   # on the profile and asked for by the job
    # match goes up only from what the student has, and missing qualifications become advice, not content
    assert d["match"]["after"] >= d["match"]["before"]
    assert all("Only add" in g["advice"] or g["text"].startswith(("Major", "GPA", "Class")) or "can't tell" in g["advice"] for g in d["gaps"])
    no_bi = dict(PROF, skills=["Python"])
    d2 = re_.build_resume(no_bi, RESUME, JOB, today=TODAY)
    assert "Power BI" not in d2["text"] and any(g["text"].startswith("Power BI") for g in d2["gaps"])
    assert re_.parse(d["text"])["sections"].keys() >= {"summary", "education", "experience", "skills"}   # the text reads back as a resume


def test_undo_and_accepted_choose_what_is_applied():
    import resume_engine as re_
    full = re_.build_resume(PROF, RESUME, JOB, today=TODAY)
    summ = next(c["id"] for c in full["changes"] if c["kind"] == "summary")
    rw = next(c for c in full["changes"] if c["kind"] == "rewrite")
    d = re_.build_resume(PROF, RESUME, JOB, undo=[summ, rw["id"]], today=TODAY)
    assert [c["id"] for c in d["changes"]] == [c["id"] for c in full["changes"]]            # ids are stable
    assert "SUMMARY" not in d["text"] and rw["before"] in d["text"] and rw["after"] not in d["text"]
    assert not next(c for c in d["changes"] if c["id"] == summ)["on"]
    none = re_.build_resume(PROF, RESUME, JOB, accepted=set(), today=TODAY)
    assert "SUMMARY" not in none["text"] and "Responsible for cleaning survey data in Excel" in none["text"] and "Bus Tracker" not in none["text"]


def test_general_optimize_and_resumes_without_bullets():
    import resume_engine as re_
    g = re_.build_resume({"major": "Business Administration", "grad_term": "May 2027"}, EVAN)
    assert g["match"] is None and g["gaps"] == [] and g["changes"][0]["kind"] == "summary"
    assert "Python, SQL and JavaScript" in g["changes"][0]["after"] and "Data-Video Generalist — Micro1." in g["changes"][0]["after"]
    ed = next(s for s in g["sections"] if s["key"] == "education")
    assert len(ed["entries"]) == 2 and ed["entries"][1]["date"] == "Aug 2023 – May 2025"      # second school, date pulled out of the middle
    assert next(s for s in g["sections"] if s["key"] == "leadership")["title"] == "Activities"
    plain = "Sam Lee\nsam@fsu.edu\n\nEXPERIENCE\nFront Desk Assistant, Rec Center, 2024 - Present\nI was responsible for the front desk and the phones every weekend\n"
    d = re_.build_resume({}, plain)
    b = d["sections"][-1]["entries"][0]["bullets"]
    assert d["sections"][-1]["entries"][0]["date"] == "2024 - Present" and b and not b[0]["text"].startswith("I was")


def test_fact_safe_rejects_anything_new():
    import resume_engine as re_
    o = "Built SQL queries to pull clinic visit counts for 12 clinics"
    assert re_.fact_safe("Wrote SQL queries that pulled visit counts for 12 clinics", o)
    assert not re_.fact_safe("Wrote SQL queries for 15 clinics", o)                          # new number
    assert not re_.fact_safe("Wrote SQL and Python queries for 12 clinics", o)               # new skill
    assert re_.fact_safe("Wrote SQL and Python queries for 12 clinics", o, ["Python"])       # unless it's on the profile
    assert not re_.fact_safe("Wrote SQL queries for 12 clinics at Google", o)                # new name
    assert not re_.fact_safe("Wrote SQL queries for [number] clinics", o) and not re_.fact_safe("", o)


def test_pdf_is_real_and_readable():
    import resume_engine as re_
    from pypdf import PdfReader
    d = re_.build_resume(PROF, RESUME, JOB, today=TODAY)
    pdf = re_.to_pdf(d)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    r = PdfReader(io.BytesIO(pdf))
    assert len(r.pages) == 1 and float(r.pages[0].mediabox.width) == 612
    t = r.pages[0].extract_text()
    for s in ("Jordan Rivera", "SUMMARY", "EXPERIENCE", "Built SQL queries", "Summer 2025", "Power BI"):
        assert s in t
    assert r.metadata.title == "Jordan Rivera resume"
    # long resumes flow onto more pages; symbols and accents survive; parentheses are escaped
    long = RESUME.replace("SKILLS", "\n".join(f"• Organized study session number {i} (weekly) for 20 students – café réunion" for i in range(70)) + "\nSKILLS")
    r2 = PdfReader(io.BytesIO(re_.to_pdf(re_.build_resume({}, long))))
    assert len(r2.pages) >= 2
    t2 = "".join(p.extract_text() for p in r2.pages)
    assert "(weekly)" in t2 and "café réunion" in t2 and "–" in t2 and "number 69" in t2


def test_docx_has_the_structure():
    import resume_engine as re_
    d = re_.build_resume(PROF, RESUME, JOB, today=TODAY)
    data = re_.to_docx(d)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert "<w:caps/>" in xml and '<w:tab w:val="right"' in xml and "Summer 2025" in xml
    back = re_.extract_text("r.docx", data)
    assert "Jordan Rivera" in back and "• Built SQL queries" in back
    assert re_.to_docx("Sam\nEDUCATION\nFSU").startswith(b"PK")                                # plain text still works


def test_stand_out_and_cover_note_come_from_the_profile():
    import resume_engine as re_
    tips = re_.stand_out_job(PROF, RESUME, JOB, TODAY)
    assert 3 <= len(tips) <= 6 and tips[0]["title"].startswith("Lead with Data Intern")
    assert any("Bus Tracker" in t["title"] for t in tips)
    note = re_.cover_note(PROF, RESUME, JOB, "Pat")
    assert note.startswith("Hi Pat,") and "Data Analyst Intern role at Acme Analytics" in note and "For example, I built SQL queries" in note
    assert len(note.split()) < 130 and nums(note) <= nums(RESUME + json.dumps(PROF))


# ---------- pages ----------

def _setup(net, **kw):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid, desc=DESC)
    with net.app.store.db() as conn:
        conn.execute("UPDATE student_profiles SET skills = ? WHERE user_id = ?", (json.dumps(["Python", "SQL", "Power BI"]), sid))
    return s, sid, emp, eid, job


def test_tailor_page_preview_changes_and_downloads(net):
    from pypdf import PdfReader
    s, sid, emp, eid, job = _setup(net)
    r = s.get(f"/resume?tab=tailor&job={job}")
    assert r.status_code == 303 and r.headers["location"] == f"/job/{job}/tailor"               # the listing's "Tailor my resume" lands here
    page = s.get(f"/job/{job}/tailor").text
    assert "Your resume for Data Analyst Intern" in page and 'class="rs-doc"' in page and "Match with this job" in page
    assert "Tailor my resume" in page and "Help me stand out" in page and "Message the poster" in page
    assert f'href="/job/{job}/tailor.pdf"' in page and f'href="/job/{job}/tailor.docx"' in page and ">Undo<" in page
    assert "Not on your resume yet" in page and "<script" not in page.split("</head>", 1)[1].split("<script src", 1)[0]
    main_before = s.get("/resume?tab=edit").text
    undo = re.search(rf'href="/job/{job}/tailor\?undo=(c\d+)#ch-c\d+"', page).group(1)
    page2 = s.get(f"/job/{job}/tailor?undo={undo}").text
    assert ">Keep<" in page2 and "Undone" in page2 and f"tailor.pdf?undo={undo}" in page2
    pdf = s.get(f"/job/{job}/tailor.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"] and ".pdf" in pdf.headers["content-disposition"]
    assert "SUMMARY" in PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    t_all, t_undo = s.get(f"/job/{job}/tailor.txt").text, s.get(f"/job/{job}/tailor.txt?undo=c1").text
    assert "SUMMARY" in t_all and "SUMMARY" not in t_undo                                    # downloads respect Undo
    assert s.get(f"/job/{job}/tailor.docx").content.startswith(b"PK")
    assert s.get("/resume?tab=edit").text == main_before                                     # nothing changed the main resume
    # save as version, and open in editor
    r = s.post(f"/job/{job}/tailor/save", data={"csrf": ucsrf(s), "undo": "c1"})
    assert r.status_code == 303 and "saved=1" in r.headers["location"]
    assert "Saved as" in s.get(r.headers["location"]).text
    vpage = s.get("/resume?tab=versions").text
    assert "For Data Analyst Intern at Acme Analytics" in vpage
    vid = int(re.search(r"/resume/versions/(\d+)\.docx", vpage).group(1))
    with net.app.store.db() as conn:
        body = conn.execute("SELECT body FROM resume_versions WHERE id = ?", (vid,)).fetchone()[0]
    assert "SUMMARY" not in body and "• Built SQL queries" in body
    ed = s.get(f"/resume?tab=edit&from=job{job}&undo=c1").text
    assert "Edit your new resume" in ed and 'action="/resume/versions"' in ed and "Built SQL queries" in ed
    assert s.post(f"/job/{job}/tailor/save", data={"csrf": "bad"}).status_code == 303


def test_tailor_access_rules(net):
    s, sid, emp, eid, job = _setup(net)
    assert emp.get(f"/job/{job}/tailor").status_code == 403
    assert emp.get(f"/job/{job}/tailor.pdf").status_code == 403
    assert net.client().get(f"/job/{job}/tailor").status_code == 303
    assert s.get("/job/99999/tailor").status_code == 404 and s.get("/job/99999/standout").status_code == 404
    pending = net.app.add_job({"title": "Pending", "company": "Acme Analytics", "category": "Data & Analytics", "work_type": "remote",
                               "location": "Tallahassee, FL", "description": DESC, "apply_url": "https://acme.example/careers", "contact": ""}, employer_id=eid)
    assert s.get(f"/job/{pending['id']}/tailor").status_code == 404                           # only approved listings
    assert s.get(f"/job/{job}/tailor.exe").status_code == 303
    s2, _ = student(net, "n@fsu.edu", "Nia N.", resume=None)
    page = s2.get(f"/job/{job}/tailor").text
    assert "Add your resume first" in page and 'action="/resume/upload"' in page


def test_standout_and_note_to_the_poster(net):
    s, sid, emp, eid, job = _setup(net)
    with net.app.store.db() as conn:
        conn.execute("UPDATE jobs SET poster_name = 'Dr. Priya Shah', poster_title = 'Data Lead' WHERE id = ?", (job,))
    page = s.get(f"/job/{job}/standout").text
    assert "Help me stand out" in page and page.count('class="rs-tipc"') >= 3 and "A short cover note" in page and "Hi Dr. Shah," in page
    note = s.get(f"/job/{job}/tailor?mode=note").text
    assert "A short note to the poster" in note and "once you apply" in note and 'action="/messages/new"' not in note
    s.get(f"/job/{job}/apply")                                                                # opening the employer's link counts as applying
    note = s.get(f"/job/{job}/tailor?mode=note").text
    assert 'action="/messages/new"' in note and 'name="body"' in note and "Continue in Messages" in note
    body = re.search(r'<textarea id="n-note" name="body"[^>]*>([^<]*)</textarea>', note).group(1)
    r = s.get("/messages/new", params={"to": eid, "job": job, "body": "Hi Dr. Shah, I'm <Jordan>."})   # the prefilled draft, escaped
    assert r.status_code == 200 and "data-count>Hi Dr. Shah, I'm &lt;Jordan&gt;.</textarea>" in r.text
    assert "Data Analyst Intern" in body


def test_optimized_resume_is_step_three(net):
    s, sid = student(net)
    page = s.get("/resume/optimize?src=main").text
    assert 'class="rs-steps"' in page and "See your optimized resume" in page and 'class="rs-ln' in page
    assert re.search(r'class="rs-ln lb hl" id="rs-l\d+"><div class="rs-txt">• Responsible for cleaning survey data in Excel</div><div class="rs-margin">.*?action="/resume/accept"', page)
    opt = s.get("/resume/optimized?src=main").text
    assert "Your optimized resume" in opt and 'class="rs-doc"' in opt and "ATS readiness" in opt and "/resume/optimized.pdf?src=main" in opt
    assert 'aria-current=step' in opt and ">Undo<" in opt
    pdf = s.get("/resume/optimized.pdf?src=main")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    r = s.post("/resume/optimized/save", data={"csrf": ucsrf(s), "src": "main"})
    assert r.status_code == 303 and "Optimized: " in s.get("/resume?tab=versions").text
    assert s.get("/resume/optimized?src=v999").status_code == 303
    other, _ = student(net, "o@fsu.edu", "Omar O.", resume=None)
    assert "Add your resume first" in other.get("/resume/optimized").text


def test_ai_wording_is_checked_before_it_reaches_the_resume(net, monkeypatch):
    s, sid, emp, eid, job = _setup(net)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    good, bad = "Pulled clinic visit counts for 12 clinics with SQL, cutting report time from 3 days to 4 hours", "Cleaned survey data in Excel for 40 clinics"

    def handler(request):
        out = {"summary": "Statistics student at Florida State University who led a 500-person team.",
               "bullets": [{"original": "Built SQL queries to pull clinic visit counts for 12 clinics, cutting report time from 3 days to 4 hours", "improved": good, "why": "Results first."},
                           {"original": "Responsible for cleaning survey data in Excel", "improved": bad, "why": "Adds scale."}]}
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "resume_wording", "input": out}]})
    net.ai._transport = httpx.MockTransport(handler)
    page = s.get(f"/job/{job}/tailor").text
    assert "Improve wording with AI" in page
    r = s.post(f"/job/{job}/tailor/ai", data={"csrf": ucsrf(s)})
    assert r.status_code == 303 and r.headers["location"] == f"/job/{job}/tailor?ai=1"
    page = s.get(r.headers["location"]).text
    assert good in page and "40 clinics" not in page and "500-person" not in page             # invented facts never land
    assert good in s.get(f"/job/{job}/tailor.txt?ai=1").text


# ---------- demo port ----------

NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_demo_build_resume_matches_python():
    import resume_engine as re_
    job2 = dict(JOB, id=9, title="Marketing Intern", category="Marketing", description="Run social media campaigns and write copy. Canva and Excel a plus. Juniors preferred.",
                requirements=json.dumps([{"kind": "skill", "label": "Canva", "must": False}]))
    cases = [(PROF, RESUME, JOB, []), (PROF, RESUME, JOB, ["c1", "c3"]), ({"major": "Business Administration", "grad_term": "May 2027"}, EVAN, None, []),
             ({"skills": ["Excel", "Canva"], "display_name": "Evan W."}, EVAN, job2, ["c2"]), ({}, "Sam Lee\nsam@fsu.edu\n\nEXPERIENCE\nFront Desk Assistant, Rec Center, 2024 - Present\n"
             "I was responsible for the front desk and the phones every weekend\n", None, [])]
    js = r"""
const fs = require("fs");
globalThis.NCS_RULEPACK = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const NCS = require(process.argv[3]);
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inp.map(([p, t, j, u]) => { const d = NCS.buildResume(p, t, j, null, u, [2026, 9]);
  return {doc: d, pdf: Buffer.from(NCS.toPdf(d)).toString("latin1"), html: NCS.docHtml(d),
          tips: j ? NCS.standOutJob(p, t, j, [2026, 9]) : null, note: j ? NCS.coverNote(p, t, j, "Pat") : null}; })));
"""
    script = ROOT / "demo" / "_parity_tr.js"
    script.write_text(js)
    try:
        res = subprocess.run([NODE, str(script), str(ROOT / "scam_detector" / "rulepack" / "core.json"), str(ROOT / "demo" / "engine.js")],
                             input=json.dumps(cases), capture_output=True, text=True, timeout=120)
    finally:
        script.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr[-2000:]
    for (p, t, j, u), g in zip(cases, json.loads(res.stdout)):
        want = json.loads(json.dumps(re_.build_resume(p, t, j, undo=u, today=TODAY)))
        assert g["doc"] == want
        assert g["pdf"] == re_.to_pdf(want).decode("latin-1")
        assert g["html"] == re_.doc_html(want)
        if j:
            assert g["tips"] == re_.stand_out_job(p, t, j, TODAY)
            assert g["note"] == re_.cover_note(p, t, j, "Pat")
