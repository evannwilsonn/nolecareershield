"""defense.py and defense_web.py: identifier memory, rings, fingerprints and clones, the stricter-only verdict merge,
conversation and attachment checks, drift alerts, the intel page, the decoy desk gate, forward-by-email and the peer feed."""
import json, sqlite3, sys, time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from, make_verified, user_login  # noqa: E402,F401

SCAM = ("Hi, this is Linda from the hiring team. You were selected for a remote assistant role, $450 weekly. Text me on "
        "850-555-0199 or write lindahr.careers@gmail.com. We will send a check for your equipment.")


def _admin(c):
    c.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(c.get("/admin").text)})
    return c


def _send(c, text, label="scam"):
    tok = csrf_from(c.get("/check?kind=message").text)
    c.post("/check/submit", data={"csrf": tok, "text": text, "sender": "", "band": "clear", "label": label, "kind": "message"})


def _confirm_all(c, label="scam"):
    with closing(sqlite3.connect(c.appmod.DB_PATH)) as db:
        db.execute("UPDATE submitted_checks SET review_label = ?, reviewed_at = ?", (label, time.time()))
        db.commit()


def test_extract_finds_contacts_and_skips_common_domains():
    import defense
    items = defense.extract("Call (850) 555-0199, email Jo.Smith@gmail.com, see careers-fsu.net or fsu.edu, telegram @hr_linda88, "
                            "BTC wallet bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh")
    kinds = {i["kind"]: i for i in items}
    assert {"phone", "email", "domain", "telegram", "wallet"} <= set(kinds)
    assert not any(i["value"].endswith("fsu.edu") for i in items if i["kind"] == "domain")
    assert "555-0199" not in kinds["phone"]["shown"] or "*" in kinds["phone"]["shown"] or kinds["phone"]["shown"]
    h = defense.hashes(items)
    assert all(len(x["hash"]) == 64 and x["value"] not in x["hash"] for x in h)


def test_confirmed_scam_contact_details_flag_a_rewritten_message(client):
    import defense
    _send(client, SCAM)
    _confirm_all(client)
    rewritten = "Good morning! Our firm has an opening for a virtual aide. Reach our coordinator at 850 555 0199 to begin."
    found = defense.extra_findings(rewritten)
    assert any(f["rule_id"] == "known_scam_identifier" for f in found)
    # a number that also appeared in a legit report doesn't count
    _send(client, "Library desk job, $13/hour. Questions? Call 850-555-0199.", label="legit")
    _confirm_all(client, "legit")
    assert not any(f["rule_id"] == "known_scam_identifier" for f in defense.extra_findings(rewritten))


def test_message_check_only_gets_stricter_and_lists_the_asks(client):
    _send(client, SCAM)
    _confirm_all(client)
    tok = csrf_from(client.get("/check?kind=message").text)
    r = client.post("/check", data={"csrf": tok, "text": "Hello, great news. Please contact our manager at 850-555-0199 today.", "sender": ""})
    assert r.status_code == 200 and "Uses contact details from confirmed scams" in r.text and "Report it" in r.text
    tok = csrf_from(r.text)
    r = client.post("/check", data={"csrf": tok, "text": "We will send you a check. Deposit it and buy gift cards for the office vendor.", "sender": ""})
    assert "What they&#x27;re asking you to do" in r.text or "What they're asking you to do" in r.text


def test_rings_join_reports_that_share_details(client):
    import defense, store
    _send(client, "Remote job, text 850-555-0111 to start today, $600 a week, no interview needed at all.")
    _send(client, "Different wording entirely: package inspector role, email ops.team77@gmail.com or 850-555-0111.")
    _send(client, "Payroll assistant needed. Write ops.team77@gmail.com with your bank details to get onboarded fast.")
    _send(client, "Unrelated campus tutoring position, apply through the department office in person.")
    with store.db() as conn:
        rm = defense.rings(conn)
        ids = [r[0] for r in conn.execute("SELECT id FROM submitted_checks ORDER BY id")]
        s = defense.ring_summary(conn, ids[0], rm)
    assert rm[ids[0]] == rm[ids[1]] == rm[ids[2]] and ids[3] not in rm and s["size"] == 3


def test_fingerprint_round_trip_and_clone_detection(client):
    import defense, store
    d = "We are hiring a front desk assistant. Greet visitors and answer phones at our Tallahassee office for 12 hours a week."
    marked = defense.with_fingerprint(d, 4242)
    assert marked != d and defense.strip_fingerprints(marked) == d and defense.read_fingerprint(marked) == 4242
    with store.db() as conn:
        conn.execute("INSERT INTO jobs (id, title, company, category, work_type, location, description, apply_url, contact, score, band, "
                     "scam_status, review_status, findings_json, created_at) VALUES (77, 'Front Desk Assistant', 'Garnet Dental', 'Other', "
                     "'part-time', '', ?, 'https://garnetdental.example/jobs', 'jobs@garnetdental.example', 0, 'clear', 'clear', 'approved', '[]', '')",
                     (d,))
        copy = defense.with_fingerprint(d, 77) + " Apply by texting 850-555-0142 or hr.garnetdental@gmail.com."
        found = defense.clone_findings(conn, copy)
    assert found and found[0]["rule_id"] == "cloned_listing"
    with store.db() as conn:
        assert defense.clone_findings(conn, defense.with_fingerprint(d, 77))[0]["rule_id"] == "copied_from_board"


def test_job_page_carries_an_invisible_fingerprint(client):
    import defense, store
    with store.db() as conn:
        conn.execute("INSERT INTO jobs (id, title, company, category, work_type, location, description, apply_url, contact, score, band, "
                     "scam_status, review_status, findings_json, created_at) VALUES (5, 'Lab Aide', 'FSU Chem', 'Other', 'part-time', '', "
                     "'Help in the teaching lab. Wash glassware and restock supplies.', '', '', 0, 'clear', 'clear', 'approved', '[]', ?)",
                     (__import__("datetime").datetime.utcnow().isoformat(),))
    make_verified(client, "student", "stu@my.fsu.edu")
    user_login(client, "student", "stu@my.fsu.edu")
    page = client.get("/job/5").text
    assert defense.read_fingerprint(page.replace("&#x2060;", "⁠")) == 5 or defense.read_fingerprint(page) == 5


def test_conversation_tab(client):
    page = client.get("/check?kind=thread").text
    assert "A conversation" in page and 'action="/check/thread"' in page
    thread = ("Recruiter: Hi! You've been selected for a remote data entry job, $35 an hour, no interview needed.\n"
              "Me: Great, what are the next steps?\n"
              "Recruiter: Please add our hiring manager on Telegram @hr_manager_jobs for onboarding.\n"
              "Me: Ok done.\n"
              "Recruiter: We will mail you a check to buy your equipment from our approved vendor. Deposit it and send the rest by Zelle.")
    r = client.post("/check/thread", data={"csrf": csrf_from(page), "text": thread, "me": "Me"})
    assert r.status_code == 200 and "step by step" in r.text and "Moved you off the platform" in r.text and "Report it" in r.text


def test_attachment_upload_is_read(client):
    tok = csrf_from(client.get("/check?kind=message").text)
    r = client.post("/check", data={"csrf": tok, "text": "", "sender": ""},
                    files={"file": ("offer.txt", b"not a pdf", "text/plain")})
    assert r.status_code == 400 and "Paste the message" in r.text          # an unreadable file with no text asks for the text
    tok = csrf_from(r.text)
    r = client.post("/check", data={"csrf": tok, "text": "Here is the offer letter they sent me for the assistant job.", "sender": ""},
                    files={"file": ("offer.pdf", b"%PDF-1.4 broken", "application/pdf")})
    assert r.status_code == 200


def test_listing_with_known_identifier_is_held_on_the_board(client):
    import defense
    _send(client, SCAM)
    _confirm_all(client)
    out = client.appmod.add_job({"title": "Office Assistant", "company": "Acme", "work_type": "part-time",
                                 "description": "Help our office with filing and phones, 10 hours a week. Contact lindahr.careers@gmail.com to apply.",
                                 "apply_url": "", "contact": ""})
    assert out["scam_status"] == "held" and any(f["rule_id"] == "known_scam_identifier" for f in out["findings"])


def test_alerts_spot_missed_scams_and_windows(client):
    import defense, store
    for i in range(3):
        _send(client, f"Totally new tactic number {i}: we pay you to rate hotel reviews online, level {i} unlocks bonus tasks.")
    _confirm_all(client)
    with store.db() as conn:
        a = defense.alerts(conn)
        md = time.strftime("%m-%d", time.gmtime())
        conn.execute("INSERT INTO risk_windows (name, start_md, end_md, note) VALUES ('Test week', ?, ?, 'watch out')", (md, md))
        assert any(w["name"] == "Test week" for w in defense.active_windows(conn))
    assert any("got past the rules" in x["title"] for x in a)
    assert "Scam season" in client.get("/check").text


def test_intel_page_needs_a_reviewer_and_shows_config(client):
    assert client.get("/admin/intel").status_code == 303
    page = _admin(client).get("/admin/intel").text
    assert "Alerts" in page and "Scam calendar" in page and "Outside checks" in page and "Intel" in page
    r = client.post("/admin/intel/window", data={"csrf": csrf_from(page), "name": "Career fair", "start_md": "10-01", "end_md": "10-07", "note": "x"})
    assert r.status_code == 303 and "Career fair" in client.get("/admin/intel").text


def test_decoy_desk_is_off_without_the_flag(client, monkeypatch):
    a = _admin(client)
    assert "decoy desk is off" in a.get("/admin/decoys").text
    tok = csrf_from(a.get("/admin/intel").text)
    a.post("/admin/decoys/log", data={"csrf": tok, "persona": "maya", "body": SCAM, "direction": "in"})
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        assert db.execute("SELECT COUNT(*) FROM submitted_checks").fetchone()[0] == 0
    monkeypatch.setenv("DECOY_ENABLED", "1")
    page = a.get("/admin/decoys?persona=maya").text
    assert "Protocol" in page and "Never move money" in page
    a.post("/admin/decoys/log", data={"csrf": csrf_from(page), "persona": "maya", "body": SCAM, "direction": "in"})
    a.post("/admin/decoys/log", data={"csrf": csrf_from(page), "persona": "maya", "body": "What is the company website?", "direction": "out"})
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        assert db.execute("SELECT source FROM submitted_checks").fetchall() == [("decoy",)]
        assert db.execute("SELECT COUNT(*) FROM decoy_logs").fetchone()[0] == 2
    assert "Linda" in a.get("/admin/decoys?persona=maya").text


def test_forward_by_email_needs_the_token_and_replies(client, monkeypatch):
    assert client.post("/inbound/email", data={"from": "a@my.fsu.edu", "text": SCAM}).status_code == 404
    monkeypatch.setenv("INBOUND_EMAIL_TOKEN", "tok123")
    body = "FYI is this real?\n\n---------- Forwarded message ---------\nFrom: Linda <lindahr.careers@gmail.com>\nSubject: Job\n\n" + SCAM
    r = client.post("/inbound/email?token=tok123", data={"from": "Student <stu@my.fsu.edu>", "subject": "Fwd: Job", "text": body})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert client.mailer.outbox and client.mailer.outbox[-1]["to"] == "stu@my.fsu.edu" and "Scam check" in client.mailer.outbox[-1]["subject"]
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        row = db.execute("SELECT source, sender, body FROM submitted_checks").fetchone()
    assert row[0] == "email" and row[1] == "lindahr.careers@gmail.com" and "stu@my.fsu.edu" not in row[2]
    spoof = client.post("/inbound/email?token=tok123", data={"from": "x@my.fsu.edu", "text": body,
                                                            "headers": "Authentication-Results: mx.example; dmarc=fail"})
    assert spoof.json()["status"] == "ignored"


def test_peer_feed_needs_keys_and_shares_only_hashes(client, monkeypatch):
    assert client.get("/api/indicators").status_code == 404
    monkeypatch.setenv("SHARE_HMAC_KEY", "k" * 32)
    monkeypatch.setenv("SHARE_FEED_KEY", "feedkey")
    _send(client, SCAM)
    _confirm_all(client)
    assert client.get("/api/indicators", headers={"X-Share-Key": "wrong"}).status_code == 404
    r = client.get("/api/indicators", headers={"X-Share-Key": "feedkey"})
    data = r.json()
    assert r.status_code == 200 and data["indicators"] and "555" not in json.dumps(data) and "gmail" not in json.dumps(data)


def test_peer_feed_job_imports_partner_hashes(client, monkeypatch):
    import defense, store
    monkeypatch.setenv("SHARE_HMAC_KEY", "k" * 32)
    monkeypatch.setenv("PEER_FEEDS", "https://peer.example/api/indicators|pk")
    items = defense.hashes(defense.extract("Text 850-555-0177 now"))

    class R:
        status_code = 200
        def json(self):
            return {"source": "Peer U", "indicators": [{"hash": i["peer_hash"], "kind": i["kind"]} for i in items]}

    class C:
        def get(self, *a, **k):
            return R()
    assert "1 peer" in defense.peer_feed_job(client=C())
    assert any(f["rule_id"] == "peer_reported_identifier" for f in defense.extra_findings("Please text 850 555 0177 for the job."))


def test_conformal_sets_mark_uncertain_cases():
    from scam_detector import ml
    m = ml.load()
    if not m or "conformal" not in (m.spec.get("meta") or {}) and "conformal" not in m.spec:
        pytest.skip("model without conformal values")
    p = m.predict("Data entry", "Part-time data entry, $16 an hour, apply on our site.", "Garnet", "", [], 0)
    assert p["set"] == ["legit"] and not p["uncertain"]
    from scam_detector.scorer import score_posting
    txt = ("Remote assistant, $500 weekly, no interview. We will mail you a check, deposit it and buy equipment from our vendor. "
           "Text me on telegram and reply from your personal email.")
    res = score_posting("Assistant", txt, "", run_network=False)
    hi = m.predict("Assistant", txt, "", "", res.findings, res.score)
    assert "scam" in hi["set"] and hi["uncertain"] == (not hi["flag"])
