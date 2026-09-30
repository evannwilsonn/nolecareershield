"""Evidence can be corrected: who confirmed what and why, expiry, disputes, revocation, and re-scoring the listings a
correction affects. Plus: being an aggregator is a label, not a scam-risk number."""
import sqlite3, sys, time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from  # noqa: E402,F401

SCAM = ("Hi, this is Linda from the hiring team. You were selected for a remote assistant role, $450 weekly. Text me on "
        "850-555-0199 or write lindahr.careers@gmail.com. We will send a check for your equipment.")
LISTING = {"title": "Office Assistant", "company": "Acme", "work_type": "part-time", "apply_url": "", "contact": "",
           "description": "Help our office with filing and phones, 10 hours a week. Contact lindahr.careers@gmail.com to apply."}


def _admin(c, name="Dana"):
    c.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(c.get("/admin").text)})
    page = c.get("/admin/checks").text
    c.post("/admin/whoami", data={"csrf": csrf_from(page), "name": name, "back": "/admin/checks"})
    return c


def _send(c, text, label="scam"):
    tok = csrf_from(c.get("/check?kind=message").text)
    c.post("/check/submit", data={"csrf": tok, "text": text, "sender": "", "band": "clear", "label": label, "kind": "message"})


def _db(c):
    return closing(sqlite3.connect(c.appmod.DB_PATH))


def _label_all(c, label="scam", reason="asks to deposit a check"):
    a = _admin(c)
    page = a.get("/admin/checks").text
    with _db(c) as db:
        groups = {r[0] if r[0] else f"i{r[1]}" for r in db.execute("SELECT campaign, id FROM submitted_checks WHERE review_label IS NULL")}
    for g in groups:
        a.post("/admin/checks/label", data={"csrf": csrf_from(page), "group": str(g), "label": label, "reason": reason})
    return a


def test_labels_record_who_and_why(client):
    _send(client, SCAM)
    _label_all(client)
    with _db(client) as db:
        assert db.execute("SELECT reviewer, review_reason FROM submitted_checks").fetchone() == ("Dana", "asks to deposit a check")
        assert db.execute("SELECT target, label, reviewer, reason FROM label_log").fetchall() == [("check", "scam", "Dana", "asks to deposit a check")]
    assert "by Dana" in client.get("/admin/checks").text


def test_revoking_a_detail_rescores_the_listing(client):
    _send(client, SCAM)
    a = _label_all(client)
    out = client.appmod.add_job(dict(LISTING))
    assert out["scam_status"] == "held"
    page = a.get("/admin/intel").text
    assert "Contact details used as scam evidence" in page and "active until" in page
    import defense, store
    with store.db() as conn:
        h = next(h for h, d in defense.evidence(conn).items() if d["kind"] == "email")
    r = a.post("/admin/intel/indicator/revoke", data={"csrf": csrf_from(page), "h": h, "reason": "address now belongs to a real recruiter"})
    assert "changed=1" in r.headers["location"]
    job = client.appmod.get_job(out["id"])
    assert job["scam_status"] != "held" and "known_scam_identifier" not in job["findings_json"]
    page = a.get("/admin/intel").text
    assert "revoked" in page and "address now belongs to a real recruiter" in page and "by Dana" in page
    a.post("/admin/intel/indicator/restore", data={"csrf": csrf_from(page), "h": h})
    assert client.appmod.get_job(out["id"])["scam_status"] == "held"                 # restoring puts it back


def test_undoing_a_label_rescores_listings_that_leaned_on_it(client):
    _send(client, SCAM)
    a = _label_all(client)
    out = client.appmod.add_job(dict(LISTING))
    assert out["scam_status"] == "held"
    with _db(client) as db:
        cid = db.execute("SELECT id FROM submitted_checks").fetchone()[0]
    a.post("/admin/checks/undo", data={"csrf": csrf_from(a.get("/admin/checks").text), "cid": cid})
    assert client.appmod.get_job(out["id"])["scam_status"] != "held"
    with _db(client) as db:
        assert db.execute("SELECT label, reason FROM label_log ORDER BY id DESC LIMIT 1").fetchone() == (None, "undo")


def test_evidence_expires_and_disputes_cancel_it(client):
    import defense, store
    _send(client, SCAM)
    _label_all(client)
    items = defense.hashes(defense.extract("text 850-555-0199"))
    with store.db() as conn:
        assert defense.known_bad(conn, items)
        conn.execute("UPDATE submitted_checks SET reviewed_at = ?", (time.time() - 200 * 86400,))
        assert not defense.known_bad(conn, items)                                      # phones expire after 180 days
        assert defense.evidence(conn, [items[0]["hash"]])[items[0]["hash"]]["status"] == "expired"
        conn.execute("UPDATE submitted_checks SET reviewed_at = ?", (time.time(),))
    _send(client, "Library desk job, $13/hour. Questions? Call 850-555-0199.", label="legit")
    _label_all(client, "legit", "real campus job")
    with store.db() as conn:
        assert not defense.known_bad(conn, items)
        assert defense.evidence(conn, [items[0]["hash"]])[items[0]["hash"]]["status"] == "disputed"


def test_revoked_details_leave_the_partner_feed(client, monkeypatch):
    import defense, store
    monkeypatch.setenv("SHARE_HMAC_KEY", "k" * 32)
    _send(client, SCAM)
    _label_all(client)
    with store.db() as conn:
        n = len(defense.share_feed(conn)["indicators"])
        h = next(iter(defense._confirmed(conn)))
        defense.revoke(conn, h, "mistake")
        assert len(defense.share_feed(conn)["indicators"]) == n - 1


def test_aggregators_are_labeled_not_scored(client):
    import ui
    assert ui.shown_score(0, True) == 4
    assert "Aggregator" in ui.risk_meter(0, "flagged", aggregator=True) and "Aggregator" not in ui.risk_meter(0, "flagged")
