"""Resume studio redesign: optimizer landing, ATS readiness report, accept/dismiss suggestion cards,
tailor-to-a-job coverage, and the demo engine's port of the same functions. Run: python -m pytest -q tests/test_resume_studio.py"""
import json, re, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import RESUME, add_job, employer, net, student, ucsrf  # noqa: E402,F401

EVAN = (ROOT / "tests" / "fixtures" / "resume_evan.txt").read_text()
OLD = "Responsible for cleaning survey data in Excel"


def hidden(html, name, near):
    return re.search(r'name="' + name + r'" value="([^"]*)"', html[html.index(near):]).group(1)


# ---------- engine ----------

def test_report_scores_four_sections_and_lists_suggestions():
    import resume_engine as re_
    r = re_.report(RESUME, ["Figma"])
    assert 0 <= r["percent"] <= 100 and r["label"] in ("ATS-ready", "Almost ready", "Needs work")
    assert [s["name"] for s in r["sections"]] == ["Formatting", "Keywords", "Impact & bullets", "Contact & structure"]
    assert all(0 <= s["percent"] <= 100 for s in r["sections"])
    kinds = {s["kind"] for s in r["suggestions"]}
    assert {"rewrite", "skills"} <= kinds
    assert [s["id"] for s in r["suggestions"]] == [f"s{i}" for i in range(len(r["suggestions"]))]
    rw = next(s for s in r["suggestions"] if s["kind"] == "rewrite" and s["old"] == OLD)
    assert rw["section"] == "impact" and rw["new"] and rw["new"] != OLD
    # a stronger resume scores higher than a bare one
    bare = re_.report("Sam Lee\nI like jobs\n")
    assert bare["percent"] < r["percent"] and re_.report(EVAN)["percent"] >= 80


def test_add_skills_and_set_summary():
    import resume_engine as re_
    out = re_.add_skills(RESUME, ["Figma", "Python", "figma"])
    assert "Tableau, R, Public speaking, Spanish, Figma" in out and out.count("Python") == RESUME.count("Python")
    assert re_.add_skills(RESUME, ["Python"]) == RESUME                      # already there: nothing changes
    no_sec = "Sam Lee\nsam@fsu.edu\n\nEDUCATION\nFSU\n"
    assert re_.add_skills(no_sec, ["Excel"]).rstrip().endswith("SKILLS\nExcel")
    s1 = re_.set_summary(RESUME, "Statistics student who likes data.")
    assert "SUMMARY\nStatistics student who likes data." in s1 and s1.index("SUMMARY") < s1.index("EDUCATION")
    s2 = re_.set_summary(s1, "A new summary.")
    assert s2.count("SUMMARY") == 1 and "A new summary." in s2 and "likes data" not in s2


def test_stand_out_tips_use_the_resume():
    import resume_engine as re_
    tips = re_.stand_out(EVAN)
    assert 1 <= len(tips) <= 4 and any("strongest" in t["title"] for t in tips)


# ---------- pages ----------

def test_landing_has_hero_add_card_and_trust_line(net):
    s, _ = student(net, resume=None)
    page = s.get("/resume").text
    assert "Land more interviews with an ATS-ready resume" in page and "Add your resume" in page
    assert "You approve every change" in page and "Optimize my resume" in page
    s2, _ = student(net, "b@fsu.edu", "Blair B.")
    page = s2.get("/resume").text
    assert 'action="/resume/optimize"' in page and 'name="src"' in page and "Upload resume" in page and "Optimize my resume" in page
    assert "<script" not in page.split("</head>", 1)[1].split("<script src", 1)[0]     # no inline script in the body
    assert 'class="rs-steps"' in page and "rs-steps" in net.app.ui.CSS              # three steps; styles come from css_resume via ui.CSS


def test_report_shows_score_sections_and_cards_and_changes_nothing(net):
    s, sid = student(net)
    before = s.get("/resume?tab=edit").text
    page = s.get("/resume/optimize?src=main").text
    assert "ATS readiness" in page and "You approve every change" in page
    for name in ("Formatting", "Keywords", "Impact &amp; bullets", "Contact &amp; structure", "Help me stand out"):
        assert name in page
    assert OLD in page and 'action="/resume/accept"' in page and ">Dismiss<" in page
    assert s.get("/resume?tab=edit").text == before                        # viewing changes nothing


def test_accept_applies_only_that_suggestion(net):
    s, sid = student(net)
    page = s.get("/resume/optimize?src=main").text
    new = hidden(page, "new", f'name="old" value="{OLD}"').replace("&amp;", "&")
    t = ucsrf(s)
    # no CSRF: nothing happens
    r = s.post("/resume/accept", data={"ctx": "main", "kind": "rewrite", "old": OLD, "new": new, "csrf": "bad"})
    assert r.status_code == 303 and OLD in s.get("/resume?tab=edit").text
    r = s.post("/resume/accept", data={"ctx": "main", "kind": "rewrite", "old": OLD, "new": new, "csrf": t})
    assert r.status_code == 303 and r.headers["location"] == "/resume/optimize?src=main&ok=1"
    edit = s.get("/resume?tab=edit").text
    assert OLD not in edit and "Managed the club Instagram" in edit         # the other bullets are untouched
    assert "Applied." in s.get(r.headers["location"]).text
    # an 'old' line that isn't in the resume never applies
    r = s.post("/resume/accept", data={"ctx": "main", "kind": "rewrite", "old": "Not a real line", "new": "Invented experience", "csrf": t})
    assert "Invented experience" not in s.get("/resume?tab=edit").text and "ok=1" not in r.headers["location"]


def test_dismiss_hides_a_card_and_can_be_undone(net):
    s, _ = student(net)
    page = s.get("/resume/optimize?src=main").text
    href = re.search(r'href="(/resume/optimize\?src=main&amp;x=s\d+#rs-\w+)"', page).group(1).replace("&amp;", "&")
    gone = s.get(href.split("#")[0]).text
    assert gone.count('class="rs-card') == page.count('class="rs-card') - 1 and "dismissed. " in gone and "Show all again" in gone
    assert s.get("/resume/optimize?src=main").text.count('class="rs-card') == page.count('class="rs-card')


def test_profile_skills_missing_from_resume_can_be_added(net):
    s, sid = student(net)
    t = ucsrf(s)
    with net.app.store.db() as conn:
        conn.execute("UPDATE student_profiles SET skills = ? WHERE user_id = ?", (json.dumps(["Python", "Figma"]), sid))
    page = s.get("/resume/optimize?src=main").text
    assert "Add skills you already list on your profile" in page and "Figma" in page
    s.post("/resume/accept", data={"ctx": "main", "kind": "skills", "old": "", "new": "Malware, Figma", "csrf": t})
    text = s.get("/resume?tab=edit").text
    assert "Spanish, Figma" in text and "Malware" not in text                # the server uses the profile's skills, not the form's text


def test_saved_versions_can_be_optimized_and_stay_private(net):
    s, sid = student(net)
    t = ucsrf(s)
    s.post("/resume/versions", data={"csrf": t, "name": "Copy A", "body": RESUME.replace("Data Intern", "Analyst Intern")})
    vid = int(re.search(r"/resume/versions/(\d+)\.docx", s.get("/resume?tab=versions").text).group(1))
    assert f'<option value="v{vid}">Copy A' in s.get("/resume").text
    page = s.get(f"/resume/optimize?src=v{vid}").text
    assert "Copy A" in page and "ATS readiness" in page
    s.post("/resume/accept", data={"ctx": f"v{vid}", "kind": "rewrite", "old": OLD, "new": "Cleaned survey data in Excel for [number] clinics", "csrf": t})
    assert "Cleaned survey data in Excel for [number] clinics" in s.get(f"/resume/optimize?src=v{vid}").text
    assert OLD in s.get("/resume?tab=edit").text                            # the main resume is unchanged
    other, _ = student(net, "x@fsu.edu", "Xander X.")
    assert "Copy A" not in other.get("/resume").text
    r = other.get(f"/resume/optimize?src=v{vid}")
    assert r.status_code == 404 and "Copy A" not in r.text and "isn&#x27;t available" in r.text.replace("'", "&#x27;")
    other.post("/resume/accept", data={"ctx": f"v{vid}", "kind": "rewrite", "old": OLD, "new": "hijacked", "csrf": ucsrf(other)})
    assert "hijacked" not in s.get(f"/resume/optimize?src=v{vid}").text


def test_upload_goes_straight_to_the_report(net):
    s, _ = student(net, resume=None)
    r = s.post("/resume/upload", data={"csrf": ucsrf(s)}, files={"resume": ("r.txt", RESUME.encode(), "text/plain")})
    assert r.status_code == 303 and r.headers["location"] == "/resume/optimize?src=main"
    assert "ATS readiness" in s.get(r.headers["location"]).text
    r = s.post("/resume/upload", data={"csrf": ucsrf(s)}, files={"resume": ("x.exe", b"MZ" + b"0" * 100, "application/octet-stream")})
    assert r.status_code == 400 and "Add your resume" in r.text


def test_tailor_shows_coverage_and_accepts_into_a_copy(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid, desc="Summer data internship. Use SQL, Python and Tableau to build dashboards. Requires Power BI experience. Paid $18/hour.")
    t = ucsrf(s)
    with net.app.store.db() as conn:
        conn.execute("UPDATE student_profiles SET skills = ? WHERE user_id = ?", (json.dumps(["Python", "SQL", "Power BI"]), sid))
    assert s.get(f"/resume?tab=tailor&job={job}").headers["location"] == f"/job/{job}/tailor"     # the new resume page (test_tailored_resume)
    tab = s.get("/resume?tab=tailor").text
    assert 'action="/resume/tailor-go"' in tab and f'<option value="{job}"' in tab
    assert s.get(f"/resume/tailor-go?job={job}").headers["location"] == f"/job/{job}/tailor"
    # the coverage view with accept/dismiss cards is still there for a listing (and for pasted descriptions)
    page = s.post("/resume/tailor", data={"csrf": t, "job_id": str(job), "mode": "builtin"}).text
    assert f'<option value="{job}" selected>' in page and "Match details" in page
    assert "listed qualifications" in page and "Covered by your resume" in page and "Not shown yet" in page and "Tableau" in page
    assert "Add skills this job lists that you already have on your profile" in page and "Add a summary written for this role" in page
    assert "You approve every change" in page
    main_before = s.get("/resume?tab=edit").text
    s.post("/resume/accept", data={"ctx": f"job{job}", "kind": "skills", "old": "", "new": "", "csrf": t})
    s.post("/resume/accept", data={"ctx": f"job{job}", "kind": "summary", "old": "", "new": "Statistics student aiming at data roles.", "csrf": t})
    assert s.get("/resume?tab=edit").text == main_before                                     # main resume untouched
    vpage = s.get("/resume?tab=versions").text
    assert "For Data Analyst Intern at Acme Analytics" in vpage
    vid = int(re.search(r"/resume/versions/(\d+)\.docx", vpage).group(1))
    docx = s.get(f"/resume/versions/{vid}.docx")
    assert docx.status_code == 200
    again = s.post("/resume/tailor", data={"csrf": t, "job_id": str(job), "mode": "builtin"}).text
    assert "tailored copy" in again
    assert "Add skills this job lists" not in again                                          # already accepted
    # pasted descriptions show the coverage but offer no Accept button
    r = s.post("/resume/tailor", data={"csrf": t, "job_id": "", "title": "Data Intern", "description": "Use SQL and Tableau to build dashboards for city clients every week.", "mode": "builtin"})
    assert r.status_code == 200 and "Covered by your resume" in r.text and 'action="/resume/accept"' not in r.text


def test_tailor_dismiss_and_access_rules(net):
    s, sid = student(net)
    emp, eid = employer(net)
    job = add_job(net, eid)
    page = s.post("/resume/tailor", data={"csrf": ucsrf(s), "job_id": str(job), "mode": "builtin"}).text
    assert re.search(r'href="/resume\?tab=tailor&amp;job=\d+&amp;x=s\d+"', page)
    assert emp.get("/resume/optimize").status_code == 403
    assert net.client().get("/resume/optimize").status_code == 303
    assert s.post("/resume/accept", data={"ctx": "job999", "kind": "summary", "new": "x", "csrf": ucsrf(s)}).status_code == 303
    assert s.get("/resume?tab=tailor&job=99999").headers["location"] == "/job/99999/tailor"
    assert s.get("/job/99999/tailor").status_code == 404


# ---------- demo engine parity ----------

NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_demo_engine_matches_python_for_the_optimizer():
    import resume_engine as re_
    texts = [RESUME, EVAN, "Sam Lee\nsam@fsu.edu\n\nEDUCATION\nFlorida State University\n\nEXPERIENCE\nI was responsible for the front desk\nHelped with making flyers for events\n"]
    skills = [["Figma", "Python", "Excel"], [], ["SQL"]]
    js = r"""
const fs = require("fs");
globalThis.NCS_RULEPACK = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const NCS = require(process.argv[3]);
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inp.texts.map((t, i) => ({report: NCS.report(t, inp.skills[i]), stand: NCS.standOut(t),
  add: NCS.addSkills(t, ["Figma", "Excel", "Tableau"]), sum: NCS.setSummary(t, "A short summary."), miss: NCS.missingProfileSkills(t, inp.skills[i])}))));
"""
    script = ROOT / "demo" / "_parity_rs.js"
    script.write_text(js)
    try:
        res = subprocess.run([NODE, str(script), str(ROOT / "scam_detector" / "rulepack" / "core.json"), str(ROOT / "demo" / "engine.js")],
                             input=json.dumps({"texts": texts, "skills": skills}), capture_output=True, text=True, timeout=120)
    finally:
        script.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr[-2000:]
    got = json.loads(res.stdout)
    for t, sk, g in zip(texts, skills, got):
        want = json.loads(json.dumps(re_.report(t, sk)))
        want["stats"].pop("sections", None)
        g["report"]["stats"].pop("sections", None)
        assert g["report"] == want
        assert g["stand"] == re_.stand_out(t)
        assert g["add"] == re_.add_skills(t, ["Figma", "Excel", "Tableau"])
        assert g["sum"] == re_.set_summary(t, "A short summary.")
        assert g["miss"] == re_.missing_profile_skills(t, sk)
