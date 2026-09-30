"""The random low-risk sample, the detector's health numbers, and red-team regression variants."""
import json, random, sqlite3, sys, time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from  # noqa: E402,F401

SAFE = "Hi Jordan, the biology department is hiring two lab assistants for spring. Email me at jane.doe@gmail.com or call 850-555-0142."


class Always(random.Random):
    def random(self):
        return 0.0


def test_safe_results_are_sampled_masked_and_left_unlabeled(client, monkeypatch):
    import metrics
    monkeypatch.setattr(metrics, "_rng", Always())
    tok = csrf_from(client.get("/check?kind=message").text)
    r = client.post("/check", data={"csrf": tok, "text": SAFE, "sender": ""})
    assert r.status_code == 200
    with closing(sqlite3.connect(client.appmod.DB_PATH)) as db:
        row = db.execute("SELECT id, source, review_label, user_label, body FROM submitted_checks").fetchone()
        n_ind = db.execute("SELECT COUNT(*) FROM check_indicators WHERE check_id = ?", (row[0],)).fetchone()[0]
    assert row[1] == "sample" and row[2] is None and row[3] == ""
    assert "jane.doe" not in row[4] and "555-0142" not in row[4] and n_ind >= 1          # masked text, hashed details
    client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(client.get("/admin").text)})
    assert "Random check of a safe result" in client.get("/admin/checks").text
    import learning, store
    with store.db() as conn:
        assert not [x for x in learning.labeled_rows(conn)]                             # nothing learned until a reviewer decides


def test_risky_results_and_the_daily_cap_are_not_sampled(client, monkeypatch):
    import metrics, store
    r = {"band": "review", "level": 2}
    assert metrics.maybe_sample(r, kind="message", text=SAFE, rng=Always()) is None
    monkeypatch.setattr(metrics, "SAMPLE_DAILY_MAX", 2)
    ids = [metrics.maybe_sample({"band": "clear", "level": 0}, kind="message", text=SAFE + str(i), rng=Always()) for i in range(4)]
    assert ids[0] and ids[1] and ids[2] is None and ids[3] is None


def test_health_numbers(client):
    import metrics, store
    now = time.time()
    with store.db() as conn:
        rows = [("scam", "clear", "student"), ("scam", "block", "student"), ("legit", "review", "student"), ("legit", "clear", "student"),
                ("scam", "clear", "sample"), ("legit", "clear", "sample"), ("legit", "clear", "sample")]
        for label, band, source in rows:
            conn.execute("INSERT INTO submitted_checks (body, band, user_label, created_at, source, review_label, reviewed_at) VALUES (?,?,?,?,?,?,?)",
                         ("x", band, "", now - 7200, source, label, now))
        conn.execute("INSERT INTO label_log (target, target_id, label, at) VALUES ('check', 1, 'scam', ?)", (now,))
        h = metrics.health(conn)
    assert h["missed_checks"] == 1 and h["caught"] == 1 and h["false_alarm_checks"] == 1
    assert h["sample"]["reviewed"] == 3 and h["sample"]["scams"] == 1 and 0 < h["sample"]["interval"][0] < 0.34 < h["sample"]["interval"][1]
    assert h["workload"]["labels_7d"] == 1 and abs(h["workload"]["median_hours_to_label"] - 2) < 0.01
    client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(client.get("/admin").text)})
    page = client.get("/admin/intel").text
    assert "How the detector is doing" in page and "Random sample" in page and "First report to detection" in page


def test_wilson_interval():
    import metrics
    lo, hi = metrics.wilson(0, 20)
    assert lo == 0 and 0.1 < hi < 0.2
    assert metrics.wilson(0, 0) == (0.0, 1.0)


def test_redteam_regression_set(tmp_path):
    from scam_detector.tools import redteam
    reg = tmp_path / "reg.jsonl"
    out1 = redteam.main(["--limit", "6", "--seed", "3", "--out", str(tmp_path / "e.jsonl"), "--report", str(tmp_path / "r.md"),
                         "--regression", str(reg), "--save-regression"])
    saved = redteam.load(reg)
    assert len(saved) == out1["slipped"]
    out2 = redteam.main(["--limit", "6", "--seed", "3", "--out", str(tmp_path / "e.jsonl"), "--report", str(tmp_path / "r.md"),
                         "--regression", str(reg)])
    assert out2["slipped"] == 0 and out2["regression"][1] == len(saved)                 # saved variants aren't re-reported as new
    assert "Regression set" in (tmp_path / "r.md").read_text()
    a = redteam.main(["--limit", "2", "--out", str(tmp_path / "e.jsonl"), "--report", str(tmp_path / "r.md"), "--regression", str(reg)])
    b = redteam.main(["--limit", "2", "--out", str(tmp_path / "e.jsonl"), "--report", str(tmp_path / "r.md"), "--regression", str(reg)])
    assert a["seed"] != b["seed"]                                                        # fresh variants every run
