"""Drift alerts become investigation cases with evidence, a proposal and its legitimate collateral."""
import json, sqlite3, sys, time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from  # noqa: E402,F401

NEW = ("Hello student, earn by rating hotel reviews online from your phone. Complete the daily review set to unlock "
       "the golden tier bonus, then withdraw your commission. Contact coordinator {n} via reviewhub{n}@gmail.com")


def _admin(c):
    c.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(c.get("/admin").text)})
    p = c.get("/admin/checks").text
    c.post("/admin/whoami", data={"csrf": csrf_from(p), "name": "Dana", "back": "/admin/checks"})
    return c


def _send(c, text):
    tok = csrf_from(c.get("/check?kind=message").text)
    c.post("/check/submit", data={"csrf": tok, "text": text, "sender": "", "band": "clear", "label": "scam", "kind": "message"})


VARIANTS = [
    "Hello student, earn by rating hotel reviews online. Unlock the golden tier bonus after your first set. Write reviewhub1@gmail.com",
    "Flexible gig: rate hotel reviews online from your phone each evening, unlock the golden tier bonus and withdraw weekly.",
    "Our travel partner pays students to rate hotel reviews online. Reach the golden tier bonus in three days. Text 850-555-0133.",
    "Side income for Seminoles! You rate hotel reviews online, level up to the golden tier bonus, commission paid in USDT.",
]


def _setup(c, n=4):
    for t in VARIANTS[:n]:
        _send(c, t)
    with closing(sqlite3.connect(c.appmod.DB_PATH)) as db:
        db.execute("UPDATE submitted_checks SET review_label = 'scam', reviewed_at = ?, band = 'clear'", (time.time(),))
        db.commit()


def test_missed_scams_open_a_case_with_evidence_and_a_proposal(client):
    _setup(client)
    a = _admin(client)
    page = a.get("/admin/cases").text
    assert "confirmed scams got past the rules" in page and "Cases" in page
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        cid, summary = db.execute("SELECT id, summary FROM cases").fetchone()
        assert db.execute("SELECT COUNT(*) FROM case_members WHERE case_id = ?", (cid,)).fetchone()[0] == 4
    s = json.loads(summary)
    assert s["reports"] == 4 and s["missed"] >= 1 and s["examples"]
    assert any("hotel reviews" in p["phrase"] or "golden tier" in p["phrase"] for p in s["proposal"])
    detail = a.get(f"/admin/cases/{cid}").text
    assert "Representative examples" in detail and "Proposed detection change" in detail and "Would also hit" in detail
    frag = a.get(f"/admin/cases/{cid}/proposal.json").json()
    assert frag["rules"] and frag["rules"][0]["status"] == "proposed" and frag["rules"][0]["reviewed"] is False
    # syncing again doesn't duplicate the case
    a.get("/admin/cases")
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


def test_proposal_shows_legit_collateral():
    import cases
    texts = ["Please complete the onboarding paperwork today", "Kindly complete the onboarding paperwork asap"]
    props = cases.propose(texts, [("listing #9", "New hires complete the onboarding paperwork in HR.")])
    hit = [p for p in props if "onboarding paperwork" in p["phrase"]]
    assert hit and hit[0]["legit_hits"] == 1 and hit[0]["legit_examples"] == ["listing #9"]


def test_case_decisions_need_notes_and_record_the_reviewer(client):
    _setup(client)
    a = _admin(client)
    a.get("/admin/cases")
    page = a.get("/admin/cases/1").text
    r = a.post("/admin/cases/1/decide", data={"csrf": csrf_from(page), "status": "dismissed", "note": ""})
    assert "need_note" in r.headers["location"]
    a.post("/admin/cases/1/decide", data={"csrf": csrf_from(page), "status": "confirmed", "note": "task-scam variant"})
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        assert db.execute("SELECT status, reviewer, decision_note FROM cases WHERE id = 1").fetchone() == ("confirmed", "Dana", "task-scam variant")
    import cases, store
    with store.db() as conn:
        assert len(cases.confirmed_since(conn, 0)) == 1


def test_case_can_label_its_unlabeled_reports(client):
    for i in range(3):
        _send(client, NEW.format(n=i) + f" wave copy {i}")
    import cases, store
    with store.db() as conn:
        conn.execute("INSERT INTO cases (key, kind, title, created_at, updated_at) VALUES ('t', 'wave', 't', 0, 0)")
        for cid in (1, 2, 3):
            conn.execute("INSERT INTO case_members (case_id, check_id) VALUES (1, ?)", (cid,))
    a = _admin(client)
    page = a.get("/admin/cases/1").text
    assert "Label the 3 unlabeled reports scam" in page
    a.post("/admin/cases/1/label", data={"csrf": csrf_from(page), "label": "scam"})
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        assert set(db.execute("SELECT review_label, reviewer, review_reason FROM submitted_checks")) == {("scam", "Dana", "case #1")}


def test_cases_need_a_reviewer(client):
    assert client.get("/admin/cases").status_code == 303
    assert client.get("/admin/cases/1/proposal.json").status_code == 303
