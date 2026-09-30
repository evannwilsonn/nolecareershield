"""Evidence-triggered retraining, the expanded release gate, shadow scoring, staged rollout and automatic rollback."""
import copy, json, sqlite3, sys, time
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client, csrf_from  # noqa: E402,F401

SCAM = ("Hello, the Career Center has a remote assistant job for you: $500 weekly for 5 hours. We will mail you a check "
        "to buy office equipment from our vendor. Reply from your personal email to get started.")
LEGIT = "Campus library needs a student assistant, $13/hour, 10 hours a week, apply through the FSU jobs site. Ref {i}."


def _spec(version, threshold=None):
    from scam_detector import ml
    s = json.loads(ml.MODEL_PATH.read_text())
    s["version"] = version
    if threshold is not None:
        s["threshold"] = threshold
    return s


def _write(path, spec):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec))


def _check(conn, body, label, kind="listing", split=None, at=None, campaign=None):
    cur = conn.execute("""INSERT INTO submitted_checks (body, sender, band, user_label, created_at, kind, title, company, url, source,
                          review_label, reviewed_at, learn_split, campaign) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (body, "", "clear", "", time.time(), kind, "Assistant", "", "", "student", label, at or time.time(), split, campaign))
    return cur.lastrowid


def _decisions(conn, n, cand_flag, active_flag, cand="cand", active=None):
    from scam_detector import ml
    active = active or ml.load(ml.active_path()).version
    for i in range(n):
        conn.execute("INSERT INTO model_decisions (at, key, served, flag, p, other, other_flag, other_p) VALUES (?,?,?,?,?,?,?,?)",
                     (time.time(), f"{i:064x}", active, active_flag, 0.1, cand, cand_flag, 0.1))


def _stage(conn, stage, version="cand", days_ago=10, pct=0):
    t = time.time() - days_ago * 86400
    conn.execute("UPDATE model_release SET stage = ?, candidate_version = ?, pct = ?, created_at = ?, stage_started = ?, run_id = NULL WHERE id = 1",
                 (stage, version, pct, t, t))


def test_wave_cap_keeps_a_few_rows_per_wave():
    import learning
    rows = [{"id": f"r{i}", "campaign": 7} for i in range(10)] + [{"id": "solo", "campaign": None}]
    kept = learning.cap_waves(rows, 3)
    assert [r["id"] for r in kept if r["campaign"] == 7] == ["r0", "r4", "r9"] and any(r["id"] == "solo" for r in kept)


def test_retrain_triggers(client, monkeypatch):
    import learning, release, store, cases
    monkeypatch.setattr(learning, "EVIDENCE_MIN_NEW", 3)
    with store.db() as conn:
        conn.execute("INSERT INTO model_runs (started_at, status) VALUES (?, 'refused')", (time.time() - 5 * 86400,))
        for i in range(6):                                   # one wave labeled six times counts once
            _check(conn, SCAM + f" copy {i}", "scam", campaign=99)
        ok, why, trig = learning.due_detail(conn)
        assert not ok and "1 so far" in why
        for i in range(2):
            _check(conn, LEGIT.format(i=i), "legit")
        ok, why, trig = learning.due_detail(conn)
        assert ok and trig == "evidence" and "3 new distinct labels" in why
        monkeypatch.setattr(learning, "EVIDENCE_MIN_NEW", 50)
        assert not learning.due_detail(conn)[0]
        conn.execute("INSERT INTO cases (key, kind, title, status, created_at, updated_at, summary, decided_at) VALUES "
                     "('k', 'missed', 't', 'confirmed', 0, 0, ?, ?)", (json.dumps({"distinct": 4}), time.time()))
        ok, why, trig = learning.due_detail(conn)
        assert ok and trig == "new_campaign" and "case #" in why
        conn.execute("INSERT INTO model_runs (started_at, status) VALUES (?, 'refused')", (time.time() - 86400,))
        assert "next scheduled retrain" in learning.due_detail(conn)[1]          # never more often than every 3 days
        _stage(conn, "rollout")
        ok, why, _ = learning.due_detail(conn)
        assert not ok and "release is in progress" in why


def test_gate_refuses_a_flag_happy_candidate_and_passes_a_sound_one(client):
    import release, store
    from scam_detector import ml
    with store.db() as conn:
        for i in range(3):
            _check(conn, SCAM.replace("$500", f"${500 + i * 50}") + f" ref {i}", "scam", split="holdout", campaign=100 + i)
        for i in range(3):
            _check(conn, LEGIT.format(i=i), "legit", split="holdout")
        good = ml.Model(_spec("cand"))
        ok, checks = release.gate(good, ml.load(ml.MODEL_PATH), conn)
        names = {c["name"]: c for c in checks}
        assert set(names) == {"Recent confirmed scams", "False alarms on legitimate items", "Older scam techniques (frozen holdouts)",
                              "Legitimate but unusual employers", "Scam campaigns held out of training", "Red-team regression variants"}
        assert ok, checks
        bad = ml.Model(_spec("bad", threshold=0.0))
        ok, checks = release.gate(bad, ml.load(ml.MODEL_PATH), conn)
        assert not ok and not next(c for c in checks if c["name"] == "False alarms on legitimate items")["passed"]
        blind = ml.Model(_spec("blind", threshold=2.0))
        ok, checks = release.gate(blind, ml.load(ml.MODEL_PATH), conn)
        assert not next(c for c in checks if c["name"] == "Older scam techniques (frozen holdouts)")["passed"]




def test_full_release_then_watch_rollback(client, monkeypatch):
    import learning, release, store
    from scam_detector import ml
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    with store.db() as conn:
        _stage(conn, "shadow")
        _decisions(conn, 40, 0, 0, active="active0")
        for i in range(3):
            _check(conn, SCAM + f" fresh {i}", "scam")
            _check(conn, LEGIT.format(i=i), "legit")
    assert release.tick() == "rollout started"
    for expect in ("rollout 50%", "promoted"):
        with store.db() as conn:
            conn.execute("UPDATE model_release SET stage_started = ? WHERE id = 1", (time.time() - 4 * 86400,))
        assert release.tick() == expect
    assert json.loads(learning.model_path().read_text())["version"] == "cand" and release.previous_path().exists()
    assert not release.candidate_path().exists()
    # the new model turns out to flag real jobs: the previous one comes back by itself
    _write(learning.model_path(), _spec("cand", threshold=0.0))
    with store.db() as conn:
        conn.execute("UPDATE model_release SET stage_started = ? WHERE id = 1", (time.time() - 60,))
        for i in range(3, 6):
            _check(conn, LEGIT.format(i=i), "legit")
    assert release.tick() == "rolled back"
    assert json.loads(learning.model_path().read_text())["version"] == "active0"
    with store.db() as conn:
        assert release.state(conn)["stage"] == "none"
        events = [r[0] for r in conn.execute("SELECT event FROM release_log ORDER BY id")]
    assert events[:4] == ["rollout", "rollout", "promoted", "rolled_back"]


def test_rollout_stops_when_the_candidate_does_worse_on_fresh_labels(client):
    import learning, release, store
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand", threshold=0.0))
    with store.db() as conn:
        _stage(conn, "rollout", pct=10, days_ago=1)
        _check(conn, LEGIT.format(i=1), "legit")
    out = release.tick()
    assert out.startswith("stopped") and "confirmed-real" in out
    with store.db() as conn:
        assert release.state(conn)["stage"] == "none"
    assert not release.candidate_path().exists() and json.loads(learning.model_path().read_text())["version"] == "active0"


def test_traffic_spike_stops_a_shadow_candidate(client):
    import learning, release, store
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    with store.db() as conn:
        _stage(conn, "shadow", days_ago=1)
        _decisions(conn, 20, 1, 0, active="active0")
        _decisions(conn, 20, 0, 0, active="active0")
    assert "flags 50%" in release.tick()


def test_waits_for_evidence_and_respects_manual_mode(client, monkeypatch):
    import learning, release, store
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    with store.db() as conn:
        _stage(conn, "shadow")
        _decisions(conn, 40, 0, 0, active="active0")
    assert release.tick() == "waiting: evidence"
    with store.db() as conn:
        for i in range(5):
            _check(conn, LEGIT.format(i=i), "legit")
    monkeypatch.setenv("MODEL_AUTO_RELEASE", "0")
    assert release.tick() == "ready"
    with store.db() as conn:
        assert release.state(conn)["stage"] == "shadow"


def test_routing_serves_a_stable_slice_and_records_both_opinions(client):
    import learning, release, store
    from scam_detector import ml
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    active = ml.load(learning.model_path())
    with store.db() as conn:
        _stage(conn, "rollout", pct=50, days_ago=0)
    release._cache["at"] = 0
    served = [release.route(f"{i:08x}" + "0" * 56, active)[0].version for i in (0, 0x7fffffff, 0xffffffff)]
    assert served.count("cand") >= 1 and served.count("active0") >= 1
    assert release.route("00000000" + "0" * 56, active)[0].version == release.route("00000000" + "0" * 56, active)[0].version
    release.configure()
    ml.second_look("Assistant", SCAM, "", "", [], 0)
    with store.db() as conn:
        row = store.row(conn, "SELECT * FROM model_decisions ORDER BY id DESC LIMIT 1")
    assert row and {row["served"], row["other"]} == {"cand", "active0"}


def test_model_page_shows_the_release_and_buttons_work(client):
    import learning, release, store
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    with store.db() as conn:
        _stage(conn, "shadow", days_ago=0)
    client.post("/admin/login", data={"password": "correct-horse-battery", "csrf": csrf_from(client.get("/admin").text)})
    page = client.get("/admin/model").text
    assert "Scoring alongside the active model" in page and "Start serving 10%" in page and "Rollback is always automatic" in page
    client.post("/admin/model/release", data={"csrf": csrf_from(page), "action": "next"})
    with store.db() as conn:
        assert release.state(conn)["stage"] == "rollout" and release.state(conn)["pct"] == 10
    page = client.get("/admin/model").text
    client.post("/admin/model/release", data={"csrf": csrf_from(page), "action": "stop"})
    with store.db() as conn:
        assert release.state(conn)["stage"] == "none"
    assert not release.candidate_path().exists()
