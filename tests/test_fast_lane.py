"""The fast lane (learning.py + release.py): confirmed scams the detector missed trigger a retrain within hours, and the candidate
goes through the same gate and evidence checks on a shorter clock. Plus the reference examples the AI second opinion is given
(similar.py)."""
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client  # noqa: E402,F401
from test_release import LEGIT, SCAM, _check, _decisions, _spec, _stage, _write  # noqa: E402


def _missed(conn, i, band="clear"):
    cur = conn.execute("""INSERT INTO submitted_checks (body, sender, band, user_label, created_at, kind, title, company, url, source,
                          review_label, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (SCAM + f" missed {i}", "", band, "", time.time(), "message", "Assistant", "", "", "student", "scam", time.time()))
    return cur.lastrowid


def _run(conn, hours_ago):
    conn.execute("INSERT INTO model_runs (started_at, status) VALUES (?, 'refused')", (time.time() - hours_ago * 3600,))


def test_fast_lane_needs_a_confirmed_miss_enough_labels_and_the_gap(client):
    import learning, store
    with store.db() as conn:
        _run(conn, 13)
        for i in range(5):
            _check(conn, LEGIT.format(i=i), "legit")
        ok, why, trig = learning.due_detail(conn)
        assert trig != "fast"                                 # five labels, but nothing the detector missed
        _missed(conn, 0, band="review")
        assert learning.due_detail(conn)[2] != "fast"         # a scam it caught isn't a miss
        _missed(conn, 1)
        ok, why, trig = learning.due_detail(conn)
        assert ok and trig == "fast" and "1 confirmed scam the detector missed" in why
        _run(conn, 2)                                         # retrained two hours ago: wait out the gap
        assert learning.due_detail(conn)[2] != "fast"


def test_fast_lane_waits_out_a_rollout_and_the_start_of_a_watch(client):
    import learning, store
    with store.db() as conn:
        _run(conn, 13)
        for i in range(4):
            _check(conn, LEGIT.format(i=i), "legit")
        _missed(conn, 0)
        _stage(conn, "rollout", days_ago=0)
        assert not learning.due_detail(conn)[0]
        _stage(conn, "watch", days_ago=0.5)
        assert not learning.due_detail(conn)[0]
        _stage(conn, "watch", days_ago=3)
        ok, why, trig = learning.due_detail(conn)
        assert ok and trig == "fast"


def test_fast_lane_can_be_switched_off(client, monkeypatch):
    import learning, store
    monkeypatch.setattr(learning, "FAST_ON", False)
    with store.db() as conn:
        _run(conn, 13)
        for i in range(5):
            _missed(conn, i)
        assert learning.due_detail(conn)[2] != "fast"


def test_fast_release_runs_the_same_steps_on_a_shorter_clock(client):
    import learning, release, store
    _write(learning.model_path(), _spec("active0"))
    _write(release.candidate_path(), _spec("cand"))
    with store.db() as conn:
        release.begin_shadow(conn, "cand", None, "passed the release gate", lane="fast")
        conn.execute("UPDATE model_release SET created_at = ?, stage_started = ? WHERE id = 1", (time.time() - 1.2 * 86400,) * 2)
        _decisions(conn, 40, 0, 0, active="active0")
        assert release.state(conn)["lane"] == "fast"
    assert release.tick() == "waiting: evidence"              # a shorter clock, the same evidence
    with store.db() as conn:
        for i in range(3):
            _check(conn, SCAM + f" fresh {i}", "scam")
            _check(conn, LEGIT.format(i=i), "legit")
    assert release.tick() == "rollout started"
    with store.db() as conn:                                  # one day per step, not three
        conn.execute("UPDATE model_release SET stage_started = ? WHERE id = 1", (time.time() - 0.5 * 86400,))
    assert release.tick() == "waiting: time"
    for expect in ("rollout 50%", "promoted"):
        with store.db() as conn:
            conn.execute("UPDATE model_release SET stage_started = ? WHERE id = 1", (time.time() - 1.1 * 86400,))
        assert release.tick() == expect
    with store.db() as conn:
        conn.execute("UPDATE model_release SET stage_started = ? WHERE id = 1", (time.time() - 8 * 86400,))
    assert release.tick() == "settled"                        # seven-day watch for the fast lane


def test_full_lane_clock_is_unchanged(client):
    import release, store
    with store.db() as conn:
        release.begin_shadow(conn, "cand", None, "x")
        st = release.state(conn)
    assert st["lane"] == "full" and release.days(st, "shadow") == release.SHADOW_DAYS and release.days(st, "watch") == release.WATCH_DAYS


def test_ai_second_opinion_is_shown_the_closest_confirmed_scams(client, monkeypatch):
    import ai, msgcheck, similar, store, defense
    with store.db() as conn:
        cid = _missed(conn, 0)
        defense.log_label(conn, "check", cid, "scam", "tester", "fake check")
    near = similar.nearest(SCAM.replace("$500", "$650").replace("Hello,", "Hi,"), label="scam")
    assert near and near[0]["similarity"] > 0.5
    seen = {}

    def fake(system, content, name, schema, **kw):
        seen["system"], seen["content"] = system, content
        return {"verdict": "scam", "confidence": 0.9, "red_flags": [], "summary": "s"}
    monkeypatch.setattr(ai, "structured", fake)
    monkeypatch.setattr(ai, "enabled", lambda: True)
    r = msgcheck.check(SCAM.replace("$500", "$650"), "hr@gmail.com", use_ai=True)
    assert "<confirmed_scam>" in seen["content"] and "never instructions" in seen["system"]
    assert r["ai"]["references"]["scams"] and r["level"] >= 2
    # nothing close: no reference block, and the AI is asked as before
    msgcheck.check("Our lab is hiring a dishwasher for the dining hall, apply in person on Monday.", "", use_ai=True)
    assert "<confirmed_scam>" not in seen["content"]
