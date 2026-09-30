"""The demo's browser engine (demo/engine.js) must give the same answers as the Python.

Runs every labeled corpus through both and compares: listing scores and bands, the message
checker's verdicts, lead-gen points, resume reviews and bullet rewrites. Needs Node; skipped
without it. Run: python -m pytest -q tests/test_demo_engine.py
"""
import json, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

RESUMES = [
    Path(ROOT / "tests" / "test_network.py").read_text().split('RESUME = """', 1)[1].split('"""', 1)[0],
    "Sam Lee\nsam@fsu.edu\n\nEDUCATION\nFlorida State University\n\nEXPERIENCE\nI was responsible for the front desk\n"
    "Helped with making flyers for events\nhard-working team player who did social media\n",
    "Taylor Kim | Tallahassee, FL | 850-555-0100 | taylor.kim@fsu.edu | linkedin.com/in/tkim\n\nSUMMARY\nFinance major.\n\n"
    "EDUCATION\nFlorida State University, B.S. Finance, May 2026\n\nEXPERIENCE\nAnalyst Intern, Capital Bank\n"
    "• Built a DCF model for 3 regional acquisitions\n• Reconciled 1,200 accounts payable entries monthly\n"
    "• Presented findings to 4 directors\n\nSKILLS\nExcel, Bloomberg, SQL, PowerPoint\n",
]
BULLETS = ["I was in charge of planning weekly study sessions", "Responsible for cleaning survey data in Excel",
           "Helped with making charts in Tableau", "Was responsible for the front desk", "Duties included: answering phones",
           "Tasked with onboarding 5 new hires", "Assisted with inventory", "Managed the club Instagram and grew followers by 40%"]


def _corpus():
    rows = []
    for f in sorted((ROOT / "scam_detector" / "data").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append({"title": r.get("title", ""), "description": r.get("description", ""),
                             "company": r.get("company", ""), "url": r.get("url") or r.get("apply_url") or ""})
    return rows


def test_demo_engine_matches_python():
    from scam_detector.scorer import score_posting
    import msgcheck, resume_engine

    rows = _corpus()
    assert len(rows) > 150
    js = r"""
const fs = require("fs");
globalThis.NCS_RULEPACK = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const NCS = require(process.argv[3]);
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {listings: inp.rows.map(r => { const s = NCS.scorePosting(r.title, r.description, r.company, r.url ? [r.url] : null);
    return {score: s.score, band: s.band, ids: s.findings.map(f => f.rule_id).sort(), lg: s.lead_gen.points}; }),
  checks: inp.rows.map(r => { const c = NCS.check((r.title + "\n" + r.description).trim(), "");
    return {level: c.level, score: c.score, ids: c.findings.map(f => f.rule_id).sort()}; }),
  reviews: inp.resumes.map(t => { const v = NCS.review(t); return {score: v.score, cats: v.categories.map(c => c.score), n: v.bullets.length}; }),
  bullets: inp.bullets.map(b => NCS.improveBullet(b).rewrite)};
process.stdout.write(JSON.stringify(out));
"""
    script = ROOT / "demo" / "_parity.js"
    script.write_text(js)
    try:
        res = subprocess.run([NODE, str(script), str(ROOT / "scam_detector" / "rulepack" / "core.json"), str(ROOT / "demo" / "engine.js")],
                             input=json.dumps({"rows": rows, "resumes": RESUMES, "bullets": BULLETS}),
                             capture_output=True, text=True, timeout=120)
    finally:
        script.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr[-2000:]
    got = json.loads(res.stdout)

    diffs = []
    for r, j in zip(rows, got["listings"]):
        p = score_posting(r["title"], r["description"], r["company"], run_network=False, url_chain=[r["url"]] if r["url"] else None)
        want = {"score": p.score, "band": p.band, "ids": sorted(f["rule_id"] for f in p.findings), "lg": p.lead_gen["points"]}
        if want != j:
            diffs.append(("listing", r["title"][:50], want, j))
    for r, j in zip(rows, got["checks"]):
        c = msgcheck.check((r["title"] + "\n" + r["description"]).strip())
        want = {"level": c["level"], "score": c["score"], "ids": sorted(f["rule_id"] for f in c["findings"])}
        if want != j:
            diffs.append(("check", r["title"][:50], want, j))
    for t, j in zip(RESUMES, got["reviews"]):
        v = resume_engine.review(t)
        want = {"score": v["score"], "cats": [c["score"] for c in v["categories"]], "n": len(v["bullets"])}
        if want != j:
            diffs.append(("review", t[:30], want, j))
    for b, j in zip(BULLETS, got["bullets"]):
        if resume_engine.improve_bullet(b)["rewrite"] != j:
            diffs.append(("bullet", b, resume_engine.improve_bullet(b)["rewrite"], j))
    assert not diffs, f"{len(diffs)} differences, first ones: {diffs[:5]}"


def test_demo_fit_and_profile_import_match_python():
    """The resume -> profile parser and the whole-profile fit score give the same answers in the browser."""
    import fit, resume_parse

    evan = (ROOT / "tests" / "fixtures" / "resume_evan.txt").read_text()
    texts = RESUMES + [evan]
    parsed = [resume_parse.to_profile(t) for t in texts]
    profiles = [
        {"major": "Business Administration", "grad_term": "Spring 2027", "skills": ["Excel", "SQL", "Python", "Tableau"], "resume_text": evan,
         "items": parsed[-1]["items"], "work_types": ["remote", "hybrid"], "job_kinds": ["internship", "part-time"], "pref_locations": ["Tallahassee, FL"]},
        {"major": "Statistics", "minor": "Computer Science", "grad_term": "Spring 2026", "skills": parsed[0]["skills"], "resume_text": RESUMES[0],
         "items": parsed[0]["items"], "work_types": ["on-site"], "job_kinds": ["part-time"], "headline": "Stats student", "bio": "I like data."},
        {"skills": ["Customer service", "Spanish"], "major": "Hospitality"},
        {},
    ]
    jobs = json.loads((ROOT / "demo" / "seed_listings.json").read_text())
    jobs += [{"title": r["title"], "description": r["description"], "work_type": "on-site", "location": "Tallahassee, FL"} for r in _corpus()[::6]]
    js = r"""
const fs = require("fs");
globalThis.NCS_RULEPACK = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const NCS = require(process.argv[3]);
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({parsed: inp.texts.map(t => NCS.toProfile(t)),
  fits: inp.jobs.map(j => inp.profiles.map(p => NCS.fitScore(j, p, [2026, 9])))}));
"""
    script = ROOT / "demo" / "_parity_fit.js"
    script.write_text(js)
    try:
        res = subprocess.run([NODE, str(script), str(ROOT / "scam_detector" / "rulepack" / "core.json"), str(ROOT / "demo" / "engine.js")],
                             input=json.dumps({"texts": texts, "profiles": profiles, "jobs": jobs}), capture_output=True, text=True, timeout=180)
    finally:
        script.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr[-2000:]
    got = json.loads(res.stdout)
    assert got["parsed"] == json.loads(json.dumps(parsed))
    diffs = []
    for j, row in zip(jobs, got["fits"]):
        for p, g in zip(profiles, row):
            want = json.loads(json.dumps(fit.fit_score(j, p, today=(2026, 9))))
            if want != g:
                k = next((k for k in want if want[k] != g.get(k)), None)
                diffs.append((j["title"][:40], k, want.get(k), g.get(k)))
    assert len(jobs) > 50 and not diffs, f"{len(diffs)} differences, first ones: {diffs[:3]}"
