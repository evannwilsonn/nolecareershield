"""The learning loop (learning.py): sent-in checks become a reviewer-confirmed label queue grouped into scam waves,
confirmed labels feed the monthly retrain, every label gets a permanent train/holdout place, and a retrain ships only
through the gate."""
import json, re, sqlite3, sys, time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from  # noqa: E402,F401

SCAM = ("Hello, the Career Center has a remote assistant job for you: $500 weekly for 5 hours. We will mail you a check "
        "to buy office equipment from our vendor. Reply from your personal email to get started.")
SCAM2 = SCAM.replace("$500", "$550").replace("Hello,", "Hi there,")
LISTING = {"title": "Data Entry Clerk", "company": "Garnet Analytics", "url": "https://garnet.example/jobs/7", "contact": "",
           "description": "Part-time data entry for our Tallahassee office, $16/hour, 15 hours a week. Apply on our careers page. "
                          "Contact recruiting@garnet.example with questions."}


def _admin(c):
    tok = csrf_from(c.get("/admin").text)
    c.post("/admin/login", data={"password": "correct-horse-battery", "csrf": tok})
    return c


def _send_message(c, text, label="scam", source="student"):
    tok = csrf_from(c.get("/check?kind=message").text)
    return c.post("/check/submit", data={"csrf": tok, "text": text, "sender": "hr@gmail.com", "band": "review",
                                         "label": label, "kind": "message", "source": source})


def _db(c):
    return closing(sqlite3.connect(c.appmod.DB_PATH))


def test_listing_check_sends_structured_fields(client):
    page = client.get("/check").text
    r = client.post("/check/listing", data={"csrf": csrf_from(page), **LISTING})
    form = r.text[r.text.index('action="/check/submit"'):]
    assert 'name="kind" value="listing"' in form and 'name="title" value="Data Entry Clerk"' in form
    tok = re.search(r'name="csrf" value="([^"]+)"', form).group(1)
    fields = {k: re.search(rf'name="{k}" value="([^"]*)"', form).group(1) for k in ("text", "sender", "band", "kind", "title", "company", "url")}
    client.post("/check/submit", data={"csrf": tok, "label": "legit", **{k: v.replace("&amp;", "&") for k, v in fields.items()}})
    with _db(client) as db:
        row = db.execute("SELECT kind, title, company, url, body, user_label, review_label FROM submitted_checks").fetchone()
    assert row[:4] == ("listing", "Data Entry Clerk", "Garnet Analytics", "https://garnet.example/jobs/7")
    assert row[4].startswith("Part-time data entry") and row[5] == "legit" and row[6] is None      # a visitor's word isn't a label


def test_near_copies_form_a_wave_and_one_decision_labels_it(client):
    _send_message(client, SCAM)
    _send_message(client, SCAM2, label="unsure")
    _send_message(client, "Our campus library needs a student assistant, $13/hour, apply through the FSU jobs site this week.", label="legit")
    with _db(client) as db:
        rows = db.execute("SELECT id, campaign FROM submitted_checks ORDER BY id").fetchall()
    assert rows[1][1] == rows[0][0] and rows[0][1] == rows[0][0] and rows[2][1] is None
    a = _admin(client)
    page = a.get("/admin/checks").text
    assert "Wave: 2 near-copies" in page and "Scam all 2" in page and "Label queue" in page
    tok = csrf_from(page)
    a.post("/admin/checks/label", data={"csrf": tok, "group": str(rows[0][0]), "label": "scam"})
    with _db(client) as db:
        labels = [r[0] for r in db.execute("SELECT review_label FROM submitted_checks ORDER BY id")]
    assert labels == ["scam", "scam", None]
    a.post("/admin/checks/undo", data={"csrf": tok, "cid": rows[1][0]})
    with _db(client) as db:
        assert db.execute("SELECT review_label FROM submitted_checks WHERE id = ?", (rows[1][0],)).fetchone()[0] is None
    # a new copy of a labeled wave shows the earlier decision
    _send_message(client, SCAM.replace("5 hours", "six hours"))
    assert "earlier labeled scam" in a.get("/admin/checks").text


def test_label_queue_needs_a_reviewer(client):
    assert client.get("/admin/checks").status_code == 303
    assert client.post("/admin/checks/label", data={"csrf": "x", "group": "1", "label": "scam"}).status_code == 303


def test_ai_flagged_new_pattern_is_tagged_and_prompted(client, monkeypatch):
    import msgcheck
    r = {"band": "clear", "ai": {"verdict": "scam", "confidence": 0.9}}
    assert msgcheck.is_novel(r) and not msgcheck.is_novel({**r, "band": "review"}) and not msgcheck.is_novel({**r, "ai": {"verdict": "scam", "confidence": 0.5}})
    _send_message(client, SCAM, source="ai_novel")
    _send_message(client, "Totally unrelated: need a dog walker near campus on weekends, $15 per walk, text me.", source="bogus")
    with _db(client) as db:
        assert [x[0] for x in db.execute("SELECT source FROM submitted_checks ORDER BY id")] == ["ai_novel", "student"]
    assert "AI flagged a pattern the rules missed" in _admin(client).get("/admin/checks").text


def test_export_includes_confirmed_checks_masked(client, tmp_path):
    _send_message(client, SCAM + " Call 850-555-0142 or write jane.doe@gmail.com")
    with _db(client) as db:
        db.execute("UPDATE submitted_checks SET review_label = 'scam', reviewed_at = ?", (time.time(),))
        db.commit()
    import export_labeled
    out = tmp_path / "labels.jsonl"
    counts = export_labeled.export(Path(client.appmod.DB_PATH), out)
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert counts["from_checks"] == 1 and rows[0]["label"] == "scam" and rows[0]["kind"] == "message"
    assert "850-555-0142" not in rows[0]["description"] and "jane.doe" not in rows[0]["description"] and "[email]@gmail.com" in rows[0]["description"]


def test_every_label_gets_a_permanent_place_and_waves_stay_together(client):
    import learning, store
    for i in range(30):
        words = " ".join(f"w{i}x{j}" for j in range(12))
        _send_message(client, f"Posting {i}: {words} apply today.")
    _send_message(client, SCAM)
    _send_message(client, SCAM2)
    with _db(client) as db:
        db.execute("UPDATE submitted_checks SET review_label = 'scam', reviewed_at = ?", (time.time(),))
        db.commit()
    with store.db() as conn:
        learning._assign_splits(conn)
    with _db(client) as db:
        splits = dict(db.execute("SELECT id, learn_split FROM submitted_checks").fetchall())
        waves = db.execute("SELECT COALESCE(campaign, id), COUNT(DISTINCT learn_split) FROM submitted_checks GROUP BY COALESCE(campaign, id)").fetchall()
    assert set(splits.values()) == {"train", "holdout"} and all(n == 1 for _, n in waves)
    assert any(c for c, _ in waves if c)
    with store.db() as conn:
        conn.execute("UPDATE submitted_checks SET learn_split = learn_split")          # nothing moves on a second pass
        learning._assign_splits(conn)
    with _db(client) as db:
        assert dict(db.execute("SELECT id, learn_split FROM submitted_checks").fetchall()) == splits


def test_retrain_waits_for_enough_labels_and_a_month(client, monkeypatch):
    import learning, store
    with store.db() as conn:
        ok, why = learning.due(conn)
    assert not ok and "waiting for labels: 0 new" in why
    assert learning.run_retrain()["status"] == "skipped"
    with store.db() as conn:
        conn.execute("INSERT INTO model_runs (started_at, status) VALUES (?, 'refused')", (time.time() - 3 * 86400,))
        ok, why = learning.due(conn)
    assert not ok and "next scheduled retrain in about 27 days" in why


def test_retrain_runs_the_gate_and_records_the_run(client, monkeypatch):
    pytest.importorskip("sklearn")
    import learning, store
    from scam_detector import ml
    from scam_detector.tools import train_model
    monkeypatch.setattr(train_model, "TRAIN_FILES", ["labeled_seed.jsonl", "real_corpus_clean.jsonl", "field_2026_09_tune.jsonl"])
    monkeypatch.setattr(train_model, "HALF_WEIGHT", [])
    for i in range(6):
        _send_message(client, f"{SCAM} Reference code {i * 1117}.")
    with _db(client) as db:
        db.execute("UPDATE submitted_checks SET review_label = 'scam', reviewed_at = ?", (time.time(),))
        db.commit()
    before = ml.active_path()
    out = learning.run_retrain(trigger="test", force=True)
    assert out["status"] in ("candidate", "refused"), out
    with store.db() as conn:
        run = store.row(conn, "SELECT * FROM model_runs ORDER BY id DESC LIMIT 1")
    assert run["trigger"] == "test" and run["status"] == out["status"] and "Holdout, rules alone" in run["report"] and run["finished_at"]
    assert (learning.learn_dir() / "live_train.jsonl").exists()
    import release
    assert not learning.model_path().exists() and ml.active_path() == before         # the active model never changes at training time
    with store.db() as conn:
        stage = release.state(conn)["stage"]
    if out["status"] == "candidate":
        assert release.candidate_path().exists() and stage == "shadow" and "Release gate" in run["report"]
    else:
        assert not release.candidate_path().exists() and stage == "none"
    page = _admin(client).get("/admin/model").text
    assert "Training runs" in page and out["status"] in page and "Retrain now" in page


def test_retrain_button_and_schedule_run_in_the_background(client, monkeypatch):
    import learning, store
    calls = []
    monkeypatch.setattr(learning, "run_retrain", lambda **kw: calls.append(kw))
    a = _admin(client)
    r = a.post("/admin/model/retrain", data={"csrf": csrf_from(a.get("/admin/model").text)})
    assert r.status_code == 303 and "started=1" in r.headers["location"]
    monkeypatch.setattr(learning, "due_detail", lambda conn: (True, "test", "schedule"))
    learning.maybe_retrain()
    for _ in range(50):
        if len(calls) == 2:
            break
        time.sleep(0.02)
    assert calls == [{"trigger": "reviewer", "force": True}, {"trigger": "schedule"}]
    assert "Retraining started" in a.get("/admin/model?started=1").text


def test_a_live_model_takes_over_from_the_repo_model(client, tmp_path, monkeypatch):
    import learning
    from scam_detector import ml
    assert ml.active_path() == ml.MODEL_PATH                           # nothing retrained yet
    learning.model_path().parent.mkdir(parents=True, exist_ok=True)
    learning.model_path().write_text(ml.MODEL_PATH.read_text())
    assert ml.active_path() == learning.model_path() and ml.load().version
