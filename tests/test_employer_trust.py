"""Employer trust score (0-100, higher is safer) and the detailed company page."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401


def _sig(**kw):
    base = {"status": "approved", "domain": "match", "days_approved": 200, "listings": 4, "approved": 4, "clear": 4, "scam_rejections": 0,
            "leadgen_rejections": 0, "sent": 12, "held": 0, "flagged": 0, "cautioned": 0, "reports": 0, "blocks": 0, "threads": 6, "replied": 6,
            "reply_hours": [2, 5, 8, 20, 30, 40], "profile": {k: "x" * 50 for k in ("website", "about", "industry", "size", "location", "contact_name",
                                                                                      "fsu_connection", "tagline", "linkedin", "founded")} | {"hires_for": ["Data"], "perks": ["Paid"]}}
    base.update(kw)
    return base


def test_trust_score_rewards_good_record_and_punishes_bad_signs():
    import employer_page as ep
    good = ep.trust_from_signals(_sig())
    assert good["score"] >= 90 and good["label"] == "Highly trusted" and good["tone"] == "ok"
    new = ep.trust_from_signals(_sig(days_approved=2, listings=0, approved=0, clear=0, sent=0, threads=0, replied=0, reply_hours=[]))
    assert 60 <= new["score"] < 85 and new["new"]                                       # neutral start, not "use caution"
    pending = ep.trust_from_signals(_sig(status="pending", days_approved=0))
    assert pending["score"] <= 49 and pending["label"] == "Use caution"                  # nobody reads as trusted before review
    free = ep.trust_from_signals(_sig(domain="free"))
    assert free["score"] < good["score"] and any("company's domain" in t for t in free["tips"])
    scam = ep.trust_from_signals(_sig(scam_rejections=1))
    assert scam["score"] <= 30
    rude = ep.trust_from_signals(_sig(held=1, reports=2, blocks=2))
    conduct = next(p for p in rude["parts"] if p["key"] == "conduct")
    assert conduct["score"] == 0 and "held by the scam scanner" in conduct["detail"] and rude["score"] < good["score"] - 15
    assert ep.trust_from_signals(_sig(held=1))["score"] <= 49 and ep.trust_from_signals(_sig(flagged=1))["score"] <= 69
    reported = ep.trust_from_signals(_sig(reports=1))
    assert reported["score"] <= 69 and reported["label"] == "Building trust"
    warned = ep.trust_from_signals(_sig(cautioned=1))
    assert "1 with warning signs" in next(p for p in warned["parts"] if p["key"] == "conduct")["detail"] and warned["score"] < good["score"]
    slow = ep.trust_from_signals(_sig(replied=2, reply_hours=[200, 300]))
    assert next(p for p in slow["parts"] if p["key"] == "responsiveness")["score"] < 40 and slow["score"] < good["score"]
    assert ep.reply_time(0.5) == "an hour" and ep.reply_time(5) == "6 hours" and ep.reply_time(50) == "3 days"


def test_company_page_details_and_trust(net):
    emp, eid = employer(net)
    t = ucsrf(emp)
    r = emp.post("/profile/setup/1", data={"csrf": t, "company": "Acme Analytics", "website": "acme.example", "industry": "Technology", "size": "11-50",
                                           "location": "Tallahassee, FL", "tagline": "Dashboards for city governments", "founded": "2015",
                                           "linkedin": "linkedin.com/company/acme",
                                           "about": "We build analytics dashboards for Florida city governments and hire FSU interns every summer."})
    assert r.status_code == 303
    emp.post("/profile/setup/2", data={"csrf": t, "contact_name": "Pat Lee", "contact_title": "Campus Recruiter",
                                       "fsu_connection": "We hire 3 FSU interns each summer.", "hires_for": ["Data & Analytics", "Bogus"],
                                       "perks": ["Paid", "Mentorship", "Free pizza"]})
    bad = emp.post("/profile/setup/1", data={"csrf": t, "company": "Acme Analytics", "website": "acme.example", "founded": "3015",
                                             "about": "We build analytics dashboards for Florida city governments and hire FSU interns."})
    assert bad.status_code == 400 and "Founded should be a year" in bad.text
    bad = emp.post("/profile/setup/1", data={"csrf": t, "company": "Acme Analytics", "website": "acme.example", "linkedin": "evil.example/acme",
                                             "about": "We build analytics dashboards for Florida city governments and hire FSU interns."})
    assert bad.status_code == 400
    own = emp.get("/profile").text
    assert "Trust score" in own and "Raise your score" in own and "Post a listing" in own and "Hiring at a glance" in own and "Dashboards for city governments" in own
    job = add_job(net, eid)
    assert "Raise your score" not in emp.get("/profile").text             # complete profile + an approved listing: nothing left to suggest
    s, sid = student(net)
    page = s.get(f"/company/{eid}").text
    assert "Founded 2015" in page and "linkedin.com/company/acme" in page and "Data &amp; Analytics" in page and "Bogus" not in page
    assert "✓ Paid" in page and "Free pizza" not in page and "Data Analyst Intern" in page
    m = re.search(r"Trust (\d+) · ([A-Za-z ]+)</span>", page)
    assert m and 50 <= int(m.group(1)) <= 100 and "Raise your score" not in page and f"/messages/new?to={eid}" in page
    # A student message answered quickly raises responsiveness.
    st = ucsrf(s)
    s.post("/messages/new", data={"csrf": st, "to": eid, "job": job, "body": "Hi! Is the Data Analyst Intern role still open?"})
    cid = int(re.search(r"/messages/(\d+)", s.get("/messages").text).group(1))
    emp.post(f"/messages/{cid}/send", data={"csrf": t, "body": "Yes it is. Apply on our careers page and we'll set up a call."})
    page = s.get(f"/company/{eid}").text
    assert "Answered 1 of 1 student messages" in page and ">100%<" in page
    # The listing shows the trust pill, linking to the company page.
    assert f'href="/company/{eid}#trust"' in s.get(f"/job/{job}").text


def test_unapproved_employers_are_capped_and_hidden(net):
    pend, pid = employer(net, "hr@gamma.example", approve=False, company="Gamma Co")
    s, sid = student(net)
    assert s.get(f"/company/{pid}").status_code == 404
    own = pend.get("/profile").text
    m = re.search(r"Trust (\d+) · ", own)
    assert m and int(m.group(1)) <= 49
