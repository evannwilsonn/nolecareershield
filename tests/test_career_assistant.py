"""The Career assistant: saved chats, job cards from real listings only, qualifications block, feedback, delete, privacy."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_network import add_job, employer, net, student, ucsrf  # noqa: E402,F401


def ask(s, q, cid=None):
    """Post a question, follow the Thinking step, and return (chat url, final page html)."""
    data = {"csrf": ucsrf(s), "q": q}
    if cid:
        data["cid"] = cid
    r = s.post("/assistant", data=data)
    assert r.status_code == 303
    url = r.headers["location"]
    page = s.get(url)
    assert "Thinking" in page.text and f"{url}/reply" in page.text        # the waiting state is server-rendered
    assert s.get(url + "/reply").status_code == 303
    return url, s.get(url).text


def test_home_greeting_and_starters(net):
    s, sid = student(net)
    html = s.get("/assistant").text
    assert re.search(r"Good (morning|afternoon|evening), Jordan", html)
    assert "What can I help you with today?" in html and "Ask anything" in html
    for chip in ("Find jobs matching my skills", "Draft my resume", "Help me prepare for an interview"):
        assert chip in html
    assert "New chat" in html and "Chat history" in html and "AI-generated content may contain mistakes." in html
    assert "<script>" not in html.split("</header>")[1]                    # no inline script on the page
    assert net.client().get("/assistant").status_code in (302, 303)


def test_greeting_by_time_of_day(net):
    import assistant
    from datetime import datetime
    assert assistant.greeting("Ava", datetime(2026, 9, 30, 8)) == "Good morning, Ava"
    assert assistant.greeting("Ava", datetime(2026, 9, 30, 13)) == "Good afternoon, Ava"
    assert assistant.greeting("", datetime(2026, 9, 30, 21)) == "Good evening"


def test_cards_only_real_approved_listings_with_match_and_quals(net):
    s, sid = student(net)
    emp, eid = employer(net)
    good = add_job(net, eid)
    net.app.add_job({"title": "Secret SQL Analyst", "company": "Nope", "category": "Data & Analytics", "work_type": "remote",
                     "location": "", "description": "SQL analyst role, unreviewed.", "apply_url": "", "contact": ""})
    easy = net.app.add_job({"title": "Data Reporting Intern", "company": "Acme Analytics", "category": "Data & Analytics", "work_type": "remote",
                            "location": "", "description": "Data internship. Use SQL and Excel to build reports. Paid $17/hour.", "apply_url": "",
                            "contact": "", "easy_apply": 1, "questions": []}, employer_id=eid)["id"]
    net.app.set_review(easy, "approved", "legit")
    url, html = ask(s, "Find jobs matching my skills")
    assert f'href="/job/{good}"' in html and "Data Analyst Intern" in html and "Secret SQL" not in html
    assert re.search(r"\d+% match", html)
    assert "Quick apply" in html and ">New<" in html
    assert "Scam check passed" in html                                     # the same verified/warning status the board uses
    assert "What they’re looking for" in html and "Update profile" in html and "/profile/setup" in html
    assert "You match" in html or "You don't match" in html
    assert "AI-generated content may contain mistakes." in html
    assert "Show only remote jobs" in html                                 # follow-up chips


def test_show_more_reveals_extra_cards(net):
    s, sid = student(net)
    emp, eid = employer(net)
    for i in range(6):
        add_job(net, eid, title=f"Data Analyst Intern {i}")
    url, html = ask(s, "data internships")
    assert 'class="cs-more"' in html and "Show more" in html
    assert html.count('class="cs-job"') == 6


def test_handoffs_and_interview_tips(net):
    s, sid = student(net)
    url, html = ask(s, "Draft my resume")
    assert 'href="/resume"' in html and "Open Resume studio" in html
    url, html = ask(s, "Help me prepare for an interview", cid=url.rsplit("/", 1)[1])
    assert "Tell me about yourself" in html and "never require you to pay" in html


def test_chats_persist_list_delete_and_are_private(net):
    s, sid = student(net)
    other, _ = student(net, "other@fsu.edu", "Xan X.")
    url, html = ask(s, "remote marketing internships")
    cid = url.rsplit("/", 1)[1]
    assert "remote marketing internships" in s.get("/assistant").text     # chat history
    assert "Recent:" in s.get("/assistant").text
    url2, _ = ask(s, "part-time jobs", cid=cid)                            # same chat continues
    assert url2 == url
    assert other.get(url).status_code == 303 and "remote marketing" not in other.get("/assistant").text
    other.post(f"{url}/delete", data={"csrf": ucsrf(other)})               # not theirs: nothing happens
    assert "remote marketing" in s.get("/assistant").text
    assert s.post(f"{url}/delete", data={"csrf": "bad"}).status_code == 303
    assert "remote marketing" in s.get("/assistant").text
    assert s.post(f"{url}/delete", data={"csrf": ucsrf(s)}).status_code == 303
    assert "remote marketing" not in s.get("/assistant").text


def test_feedback_toggle_and_copy_fallback(net):
    s, sid = student(net)
    url, html = ask(s, "hello")
    mid = int(re.search(r'name="m" value="(\d+)"', html).group(1))
    assert "<textarea readonly" in html and 'aria-label="Good answer"' in html
    db = sqlite3.connect(net.app.DB_PATH)

    def fb():
        db.commit()
        return db.execute("SELECT feedback FROM assistant_msgs WHERE id = ?", (mid,)).fetchone()[0]
    s.post(f"{url}/feedback", data={"csrf": ucsrf(s), "m": mid, "v": "up"})
    assert fb() == 1
    s.post(f"{url}/feedback", data={"csrf": ucsrf(s), "m": mid, "v": "down"})
    assert fb() == -1
    s.post(f"{url}/feedback", data={"csrf": ucsrf(s), "m": mid, "v": "down"})           # tap again to undo
    assert fb() == 0
    s.post(f"{url}/feedback", data={"csrf": "bad", "m": mid, "v": "up"})
    assert fb() == 0


def test_removed_listing_disappears_from_old_chat(net):
    s, sid = student(net)
    emp, eid = employer(net)
    good = add_job(net, eid)
    url, html = ask(s, "data internships")
    assert "Data Analyst Intern" in html
    net.app.set_review(good, "removed", "gone")
    assert "Data Analyst Intern" not in s.get(url).text


def test_only_students_and_csrf(net):
    assert net.client().get("/assistant").status_code in (302, 303)
    emp, eid = employer(net)
    assert emp.get("/assistant").status_code in (302, 303, 403)
    s, sid = student(net)
    assert s.post("/assistant", data={"csrf": "bad", "q": "hi"}).headers["location"] == "/assistant"
    assert "<script>alert" not in ask(s, "<script>alert(1)</script>")[1]


def test_purge_delete_account_and_export(net):
    s, sid = student(net)
    ask(s, "remote jobs")
    exp = json.loads(s.get("/profile/export").text)
    assert exp["assistant_chats"] and exp["assistant_chats"][0]["messages"][0]["text"] == "remote jobs"
    db = sqlite3.connect(net.app.DB_PATH)
    db.execute("UPDATE assistant_chats SET updated_at = 1")
    net.app.store.purge(db)
    assert db.execute("SELECT COUNT(*) FROM assistant_chats").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM assistant_msgs").fetchone()[0] == 0
    ask(s, "remote jobs")
    net.app.store.delete_account(db, sid)
    assert db.execute("SELECT COUNT(*) FROM assistant_chats").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM assistant_msgs").fetchone()[0] == 0
