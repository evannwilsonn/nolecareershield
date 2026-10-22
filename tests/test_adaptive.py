"""The adaptive layer: model format 2 (pieces of words + the shape of the text), template memory, drift monitor and the
training-time rule proposals. Each piece may only escalate, and each can be switched off or is absent without breaking a check."""
import json, sys, time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client  # noqa: E402,F401

from scam_detector import memory, ml  # noqa: E402

SCAM = ("Hello student, our department needs a remote personal assistant. $450 weekly, flexible hours, no experience needed. "
        "You will receive a check to buy office equipment from our vendor and keep the rest. Kindly reply with your personal email "
        "and phone number so we can proceed immediately.")
SCAM_RENAMED = SCAM.replace("$450", "$500").replace("personal assistant", "administrative assistant").replace("Kindly", "Please")
LEGIT = ("Student Assistant, Dirac Science Library. 10-15 hours a week at $13/hour. Duties: shelving, front-desk coverage, "
         "basic data entry. Requirements: enrolled FSU student, Federal Work-Study preferred. Apply through the FSU Careers site; "
         "interviews on campus. Equal opportunity employer, background check required.")


# ---------- model format 2 ----------

def test_shape_features_are_bounded_and_named():
    for text in (SCAM, LEGIT, "", "x"):
        f = ml.shape_features(text)
        assert len(f) == len(ml.SHAPE) and all(0.0 <= x <= 1.0 for x in f)
    s, l = ml.shape_features(SCAM), ml.shape_features(LEGIT)
    i = {n: k for k, n in enumerate(ml.SHAPE)}
    assert s[i["talks_to_you"]] > l[i["talks_to_you"]]
    assert l[i["requirements"]] > s[i["requirements"]] and l[i["benefits_eeo"]] > s[i["benefits_eeo"]]
    assert s[i["no_experience"]] == 1.0 and l[i["no_experience"]] == 0.0


def test_char_pieces_survive_spelling_tricks():
    a, b = set(ml.char_analyzer("send the cheque")), set(ml.char_analyzer("send the ch3que"))
    assert len(a & b) >= 6                                   # the pieces around the swapped letter still match


def test_format_1_models_still_load(tmp_path):
    spec = {"format": 1, "version": "old", "threshold": 0.5, "rule_scale": 3.0, "rule_ids": [], "rule_coef": [0.0], "intercept": -1.0,
            "vocab": {"lighthouse": [1.0, 5.0]}}
    m = ml.Model(spec)
    assert m.predict("Lighthouse keeper", "lighthouse")["flag"] and not m.predict("Clerk", "filing")["flag"]


def test_format_2_explains_with_traits_and_pieces():
    spec = {"format": 2, "version": "t2", "threshold": 0.5, "rule_scale": 3.0, "shape_scale": 1.0, "rule_ids": [], "rule_coef": [0.0],
            "intercept": -2.0, "vocab": {}, "cvocab": {" che": [1.0, 2.0], "que ": [1.0, 2.0]},
            "shape_coef": [0.0] * len(ml.SHAPE), "trained_on": {"rows": 5}}
    spec["shape_coef"][ml.SHAPE.index("talks_to_you")] = 6.0
    m = ml.Model(spec)
    p = m.predict("Assistant", "You will receive a cheque. You deposit it and you keep part for yourself.")
    assert p["flag"] and {b["kind"] for b in p["because"]} >= {"trait", "piece"}
    f = ml.second_look("Assistant", "You will receive a cheque. You deposit it and you keep part for yourself.", model=m)
    assert f["rule_id"] == "model_second_look" and "written at 'you'" in f["matched"] and "spelling of the words" in f["matched"]


def test_novelty_is_the_share_of_unseen_words():
    m = ml.Model({"format": 2, "version": "n", "threshold": 0.5, "rule_scale": 3.0, "rule_ids": [], "rule_coef": [0.0], "intercept": 0.0,
                  "vocab": {"remote": [1, 0], "assistant": [1, 0], "remote assistant": [1, 0]}, "cvocab": {}, "shape_coef": []})
    assert m.novelty("", "remote assistant") == 0.0
    assert m.novelty("", "quantum basket weaving") == 1.0
    assert m.novelty("", "") == 1.0


def test_shipped_model_is_format_2_with_a_drift_reference():
    m = ml.load(ml.MODEL_PATH)
    assert m and m.format == 2 and m.cvocab and len(m.shape_coef) == len(ml.SHAPE)
    ref = m.spec["drift_ref"]
    assert len(ref["score_hist"]) == 10 and abs(sum(ref["score_hist"]) - 1) < 0.01 and 0 < ref["novelty_mean"] < 1


# ---------- template memory ----------

@pytest.fixture
def mem(tmp_path, monkeypatch):
    p = tmp_path / "templates.jsonl"
    monkeypatch.setenv("SCAM_MEMORY_PATH", str(p))
    memory._cache.clear()
    return p


def test_memory_recognizes_a_renamed_copy_and_forgets_on_legit(mem):
    assert memory.finding(SCAM) is None                      # nothing remembered yet
    key = memory.remember(SCAM, title="Remote personal assistant", source="check #1")
    assert key
    f = memory.finding(SCAM_RENAMED)
    assert f and f["rule_id"] in ("confirmed_scam_copy", "confirmed_scam_template") and f["weight"] > 0
    assert "Remote personal assistant" in f["why"] and memory.finding(LEGIT) is None
    memory.forget(SCAM)
    assert memory.finding(SCAM_RENAMED) is None


def test_memory_ignores_short_texts_and_missing_store(tmp_path, monkeypatch):
    monkeypatch.delenv("SCAM_MEMORY_PATH", raising=False)
    memory._cache.clear()
    assert memory.remember(SCAM) is None and memory.finding(SCAM) is None
    monkeypatch.setenv("SCAM_MEMORY_PATH", str(tmp_path / "t.jsonl"))
    assert memory.remember("too short to matter") is None


def test_reviewer_label_feeds_memory_and_the_next_check_is_flagged(mem, client):
    import defense, learning, store
    with store.db() as conn:
        cid = learning.add_submission(conn, body=SCAM, band="clear", kind="listing", title="Remote personal assistant")
        conn.execute("UPDATE submitted_checks SET review_label = 'scam' WHERE id = ?", (cid,))
        defense.log_label(conn, "check", cid, "scam", "tester", "money mule")
    found = defense.extra_findings(SCAM_RENAMED, title="Admin assistant")
    assert any(f["rule_id"] in ("confirmed_scam_copy", "confirmed_scam_template") for f in found)
    with store.db() as conn:
        defense.log_label(conn, "check", cid, "legit", "tester", "undo")
    assert not any(f["rule_id"].startswith("confirmed_scam") for f in defense.extra_findings(SCAM_RENAMED, title="Admin assistant"))


# ---------- drift ----------

def test_psi_is_zero_for_identical_and_large_for_shifted_histograms():
    import drift
    a = [0.6, 0.1, 0.05, 0.05, 0.0, 0.0, 0.0, 0.0, 0.05, 0.15]
    assert drift.psi(a, a) == 0.0
    b = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    assert drift.psi(b, a) > 0.25


def test_drift_status_needs_traffic_then_measures(client, monkeypatch):
    import drift, store
    monkeypatch.setattr(drift, "MIN_CHECKS", 20)
    m = ml.load(ml.MODEL_PATH)
    with store.db() as conn:
        drift.ensure_schema(conn)
        conn.execute("DELETE FROM model_traffic")
        s = drift.status(conn, m)
        assert not s["measured"] and s["checks"] == 0
    for i in range(30):                                      # everything new to the model and scored mid-range: a shift
        drift.record(f"k{i}", {"probability": 0.5, "flag": False, "version": m.version}, 0.95)
    with store.db() as conn:
        s = drift.status(conn, m)
        assert s["measured"] and s["level"] == "drift" and s["psi_novelty"] > 0.25
        assert drift.alert(conn)["kind"] == "drift"
        conn.execute("DELETE FROM model_traffic")


def test_listing_check_records_traffic_through_the_hook(client, monkeypatch):
    import drift, msgcheck, store
    drift.configure()
    try:
        with store.db() as conn:
            drift.ensure_schema(conn)
            before = conn.execute("SELECT COUNT(*) FROM model_traffic").fetchone()[0]
        msgcheck.check_listing("Student Assistant", LEGIT, "FSU Libraries")
        with store.db() as conn:
            after = conn.execute("SELECT COUNT(*) FROM model_traffic").fetchone()[0]
        assert after == before + 1
    finally:
        ml.MONITOR = None


# ---------- training-time proposals ----------

def test_proposal_fragment_is_inert_and_in_rulepack_shape():
    from scam_detector.tools.train_model import proposal_fragment
    frag = proposal_fragment([{"term": "receive a", "weight": 0.3, "scam_rows": 5, "legit_rows": 0},
                              {"term": "hello", "weight": 0.3, "scam_rows": 9, "legit_rows": 0}], 300)
    assert len(frag["rules"]) == 1                            # single words are not proposed as rules
    r = frag["rules"][0]
    assert r["status"] == "proposed" and r["reviewed"] is False and r["phrases"] == ["receive a"] and r["guards"] == ["negation"]


def test_adversarial_copies_only_rewrite_scams():
    from scam_detector.tools.train_model import adversarial_copies
    rows = [{"label": "scam", "title": "A", "description": "Deposit the check and send the rest by Zelle weekly.", "_w": 1.0},
            {"label": "legit", "title": "B", "description": "Shelve books.", "_w": 1.0}]
    out = adversarial_copies(rows, weight=0.3)
    assert out and all(r["label"] == "scam" and r["_w"] == 0.3 for r in out)
    # a trick that has nothing to change (no dollar amount to drop here) leaves the text alone; most of them rewrite it
    assert sum(r["description"] != rows[0]["description"] for r in out) >= len(out) - 1
