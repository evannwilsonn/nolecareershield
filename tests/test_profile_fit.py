"""Profile sections, resume import, the whole-profile fit score, job-page tailoring, and PDF/Word uploads."""
import io, re, sqlite3, sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import RESUME, add_job, employer, net, student, ucsrf  # noqa: E402,F401

EVAN = (ROOT / "tests" / "fixtures" / "resume_evan.txt").read_text()


def make_pdf(lines):
    """A minimal real PDF with one text line per entry (Helvetica), for upload tests."""
    plain = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2019": "'", "\u2022": "-", "\u00b7": "-"})
    lines = [l.translate(plain).encode("latin-1", "replace").decode("latin-1") for l in lines]
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 10 Tf 12 TL 50 760 Td " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# ---------- resume -> profile ----------

def test_resume_parse_finds_every_section():
    import resume_parse
    r = resume_parse.to_profile(EVAN)
    kinds = [i["kind"] for i in r["items"]]
    assert kinds.count("education") == 2 and kinds.count("project") == 2 and kinds.count("experience") == 2
    fsu = next(i for i in r["items"] if i["org"] == "Florida State University")
    assert fsu["extra"]["major"] == "Business Administration" and "Business Analytics" in fsu["extra"]["coursework"] and fsu["end"] == "May 2027"
    tsc = next(i for i in r["items"] if i["org"] == "Tallahassee State College")
    assert tsc["extra"]["gpa"] == "3.4" and tsc["start"] == "Aug 2023" and tsc["end"] == "May 2025"
    tdn = next(i for i in r["items"] if "Dental" in i["org"])
    assert tdn["title"] == "IT & Financial Data Analyst Intern" and tdn["location"] == "Tampa, FL" and "Jarvis PMS" in tdn["description"]
    micro = next(i for i in r["items"] if i["org"] == "Micro1")
    assert micro["current"] and micro["location"] == "Remote"
    org = next(i for i in r["items"] if i["kind"] == "organization")
    assert org["org"] == "The Finance Society" and org["title"] == "Member"
    assert any(i["kind"] == "certification" and "Excel Expert" in i["title"] for i in r["items"])
    assert {"Python", "SQL", "Tableau"} <= set(r["skills"])
    j = resume_parse.to_profile(RESUME)
    edu = next(i for i in j["items"] if i["kind"] == "education")
    assert edu["extra"] == {"major": "Statistics", "minor": "Computer Science", "gpa": "3.6"}


def test_profile_sections_edit_and_privacy(net):
    s, sid = student(net)                                     # uploads RESUME during setup
    page = s.get("/profile").text
    assert "Leon County Health Department" in page and 'id="experience"' in page and "Looking for" in page
    t = ucsrf(s, "/profile")
    r = s.post("/profile/items", data={"csrf": t, "kind": "project", "title": "Budget dashboard", "org": "ISM 3011", "url": "github.com/jr/budget",
                                       "x_skills": "Python, SQL", "start": "Aug 2026", "current": "1", "description": "Built a <b>dashboard</b>"})
    assert r.status_code == 303
    page = s.get("/profile").text
    assert "Budget dashboard" in page and "&lt;b&gt;dashboard" in page and "https://github.com/jr/budget" in page
    iid = max(int(x) for x in re.findall(r"/profile/items/(\d+)\"", page))
    # Validation: dates and GPA must look right; nothing oversized.
    bad = s.post("/profile/items", data={"csrf": t, "kind": "education", "org": "FSU", "x_gpa": "9.9"})
    assert bad.status_code == 400 and "GPA should look like" in bad.text
    bad = s.post("/profile/items", data={"csrf": t, "kind": "experience", "title": "X", "start": "last summer"})
    assert bad.status_code == 400 and "month and year" in bad.text
    bad = s.post("/profile/items", data={"csrf": t, "kind": "experience", "title": "x" * 500})
    assert bad.status_code == 400
    # Edit, then delete.
    s.post("/profile/items", data={"csrf": t, "kind": "project", "id": iid, "title": "Budget dashboard v2"})
    assert "Budget dashboard v2" in s.get("/profile").text
    # Someone else can't edit or delete it.
    other, oid = student(net, "x@fsu.edu", "Xander X.")
    ot = ucsrf(other, "/profile")
    other.post("/profile/items", data={"csrf": ot, "kind": "project", "id": iid, "title": "Hacked"})
    other.post(f"/profile/items/{iid}/delete", data={"csrf": ot})
    assert "Budget dashboard v2" in s.get("/profile").text and "Hacked" not in s.get("/profile").text
    assert other.get(f"/profile/items/{iid}").status_code == 303
    # Other students see basics, never the sections; approved employers see the sections.
    seen = other.get(f"/u/{sid}").text
    assert "Jordan R." in seen and "Leon County Health" not in seen and "Budget dashboard" not in seen and "shared with approved employers only" in seen
    emp, eid = employer(net)
    seen = emp.get(f"/u/{sid}").text
    assert "Leon County Health" in seen and "Budget dashboard v2" in seen and ">Edit</a>" not in seen
    s.post(f"/profile/items/{iid}/delete", data={"csrf": t})
    assert "Budget dashboard v2" not in s.get("/profile").text
    # Import from resume adds nothing new the second time.
    r = s.post("/profile/import", data={"csrf": t})
    assert r.headers["location"] == "/profile?imported=0"


# ---------- fit score ----------

def _evan():
    import resume_parse
    pp = resume_parse.to_profile(EVAN)
    return {"major": "Business Administration", "grad_term": "Spring 2027", "skills": ["Excel", "SQL", "Python", "Tableau"], "resume_text": EVAN,
            "items": pp["items"], "work_types": ["remote", "hybrid"], "job_kinds": ["internship", "part-time"], "pref_locations": ["Tallahassee, FL"]}


def test_fit_uses_the_whole_profile():
    import fit
    job = {"title": "Data Analyst Intern", "work_type": "hybrid", "location": "Tallahassee, FL", "category": "Data & Analytics",
           "description": "Summer internship for juniors and seniors majoring in Statistics, Business, Economics or a related field. "
                          "Minimum 3.0 GPA. Required: SQL and Excel. Build dashboards in Tableau. Python is a plus. Paid $18/hour."}
    r = fit.fit_score(job, _evan(), today=(2026, 9))
    assert 65 <= r["score"] <= 95 and r["label"] in ("Good fit", "Strong fit") and r["confidence"] == "high"
    req = r["requirements"]
    assert req["gpa"] == 3.0 and req["standing"] == ["junior", "senior"] and "business" in req["majors"] and "Python" in req["preferred"]
    status = {c["text"]: c["status"] for c in r["checklist"]}
    assert status["GPA 3.0 or higher"] == "met"                           # from the TSC education entry
    assert status["Class standing: Juniors, Seniors"] == "met"            # graduating 2027, today Sep 2026 -> senior
    assert status["Python (preferred)"] == "met"
    where = {m["skill"]: m["where"] for m in r["matched"]}
    assert any("project" in w for w in where["Python"])                   # found in a project, not just the skills list
    assert any("Today's Dental Network" in w for w in where["Data analysis"])  # found in an experience entry
    # A thinner profile scores lower and says so.
    thin = fit.fit_score(job, {"skills": ["Excel"]}, today=(2026, 9))
    assert thin["score"] < r["score"] and thin["confidence"] == "low"
    # Low GPA is caught.
    low = _evan()
    for it in low["items"]:
        if it["kind"] == "education":
            it["extra"]["gpa"] = "2.6"
    assert {c["text"]: c["status"] for c in fit.fit_score(job, low, today=(2026, 9))["checklist"]}["GPA 3.0 or higher"] == "missing"


def test_fit_certifications_and_parts_not_asked_are_left_out():
    import fit
    nurse = {"title": "Patient Care Assistant", "work_type": "on-site", "location": "Miami, FL", "category": "Healthcare",
             "description": "Must hold CNA and CPR certification. Nursing students preferred. Patient care, vital signs, charting in Epic."}
    r = fit.fit_score(nurse, _evan(), today=(2026, 9))
    assert r["label"] == "Stretch" and any(p["key"] == "certifications" and p["score"] == 0 for p in r["parts"])
    cna = _evan()
    cna["items"] = cna["items"] + [{"kind": "certification", "title": "Certified Nursing Assistant (CNA)", "org": "Florida Board of Nursing", "extra": {}},
                                   {"kind": "certification", "title": "CPR and First Aid", "org": "American Red Cross", "extra": {}}]
    r2 = fit.fit_score(nurse, cna, today=(2026, 9))
    assert next(p for p in r2["parts"] if p["key"] == "certifications")["score"] == 100 and r2["score"] > r["score"]
    plain = fit.fit_score({"title": "Research Assistant", "work_type": "remote", "description": "Help code survey responses in a shared spreadsheet."}, _evan())
    assert "certifications" not in [p["key"] for p in plain["parts"]]


def test_job_page_shows_fit_and_tailoring(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    page = s.get(f"/job/{job}").text
    assert "Job match is" in page and "Where your profile backs it up" in page and "Tailor your resume to this job" in page
    assert "Suggested summary for this job" in page and f'href="/resume?tab=tailor&amp;job={job}"' in page
    body = re.search(r'<textarea class="resume" name="body"[^>]*>(.*?)</textarea>', page, re.S).group(1)
    r = s.post("/resume/versions", data={"csrf": ucsrf(s), "name": "For Data Analyst Intern", "body": body.replace("&amp;", "&"), "job_id": job})
    assert r.status_code == 303 and "For Data Analyst Intern" in s.get("/resume?tab=versions").text
    # The list pages show the same fit number.
    home = s.get("/").text
    assert re.search(r">Fit \d+<", home)
    # Visitors and employers don't get the panels.
    assert "Job match is" not in net.client().get(f"/job/{job}").text
    assert "Job match is" not in emp.get(f"/job/{job}").text


# ---------- uploads ----------

def test_pdf_and_docx_uploads_fill_the_resume(net):
    import resume_engine
    pdf = make_pdf(EVAN.splitlines())
    text = resume_engine.extract_text("evan.pdf", pdf)
    # pypdf 6 reads this PDF's apostrophe as a curly one (StandardEncoding 0x27 is quoteright), so compare loosely.
    straight = lambda s: s.replace("\u2019", "'").replace("&#x27;", "'")
    assert "Today's Dental Network" in straight(text) and "NoleCareerShield" in text
    s, sid = student(net, resume=None)
    t = ucsrf(s)
    r = s.post("/resume/upload", data={"csrf": t}, files={"resume": ("Evan Wilson Resume.pdf", pdf, "application/pdf")})
    assert r.status_code == 303
    assert "Resume score" in s.get("/resume?tab=review").text
    prof = s.get("/profile").text
    assert "Today's Dental Network" in straight(prof)      # filled from the PDF
    docx = resume_engine.to_docx(RESUME)
    r = s.post("/resume/upload", data={"csrf": t}, files={"resume": ("jr.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 303 and "Leon County Health Department" in s.get("/resume?tab=edit").text
