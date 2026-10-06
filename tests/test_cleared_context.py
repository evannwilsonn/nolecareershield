"""Green "ruled out by context" marks: wording that looks like a scam tactic but is ruled out ("we will never ask for a fee",
"SSN for payroll upon hire") is shown to students with the reason, and never contradicts a signal that fired.
Run: python -m pytest -q tests/test_cleared_context.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from, make_verified, user_login  # noqa: E402,F401

LEGIT = ("Hi Jordan, thanks for applying to the Front Desk Assistant role at Tally Civic Labs. We'd like to set up a 20-minute video "
         "interview with our office manager this week. The role is 12 hours a week at $14/hour. We will never ask you to pay a training "
         "fee or buy equipment. Your Social Security number is only collected for payroll upon hire.")
SCAM = ("Dear Applicant, you have been selected for the position. Pay is $35/hr, no experience needed. We will send you a check to buy "
        "your work laptop and equipment from our approved vendor.")


def test_guards_report_the_words_that_cleared_a_match():
    from scam_detector.rules import cleared_matches
    from scam_detector.asks import cleared_asks, extract_asks
    found = cleared_matches(LEGIT) + cleared_asks(LEGIT)
    clauses = {c["clause"] for c in found}
    assert "We will never ask you to pay a training fee or buy equipment" in clauses
    assert "Your Social Security number is only collected for payroll upon hire" in clauses
    assert {c["guard"] for c in found} >= {"negation", "post_hire"} and all(c["why"] for c in found)
    assert extract_asks(LEGIT) == []                               # still not counted as an ask
    assert cleared_matches(SCAM) == [] and cleared_asks(SCAM) == []


def _student_check(client, text, sender=""):
    make_verified(client, "student", "jordan@fsu.edu")
    assert user_login(client, "student", "jordan@fsu.edu").status_code == 303
    page = client.get("/check?kind=message").text
    return client.post("/check", data={"csrf": csrf_from(page), "text": text, "sender": sender}).text


def test_students_see_the_text_marked_up_with_reasons(client):
    page = _student_check(client, LEGIT)
    assert "How we read it" in page and 'class="mk-grn"' in page and "Ruled out by context" in page
    import html
    text = html.unescape(page)
    assert "Not counted:" in text and "only comes up after you're hired" in text and "doesn't mean the message is safe" in text
    scam = _student_check(client, SCAM)
    assert 'class="mk-red"' in scam and 'class="mk-grn"' not in scam and "Ruled out by context" not in scam


def test_marked_text_escapes_the_paste(client):
    evil = LEGIT + ' <img src=x onerror=alert(1)> <script>alert(2)</script>'
    page = _student_check(client, evil)
    assert "<img src=x" not in page and "<script>alert(2)" not in page and "&lt;script&gt;" in page


def test_visitors_do_not_get_the_marked_text(client):
    page = client.get("/check?kind=message").text
    r = client.post("/check", data={"csrf": csrf_from(page), "text": LEGIT, "sender": ""})
    assert r.status_code == 200 and "How we read it" not in r.text
