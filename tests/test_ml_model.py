"""The learned layer (scam_detector/ml.py): same maths as scikit-learn, only ever escalates, can be switched off,
and the trainer's shipping gate refuses a model that adds false alarms."""
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from test_app import client  # noqa: E402,F401

from scam_detector import ml  # noqa: E402

# A tiny hand-made model: the made-up word "lighthouse" is all it knows. Keeps the tests independent of training data.
TOY = {"format": 1, "version": "toy", "threshold": 0.5, "rule_scale": 3.0, "rule_ids": ["weekly_stipend"],
       "rule_coef": [0.0, 0.0], "intercept": -3.0, "vocab": {"lighthouse": [1.0, 10.0], "keeper": [1.0, 0.0]},
       "trained_on": {"rows": 12}}
QUIET = {"title": "Lighthouse keeper assistant", "company": "Harbor Trust",
         "description": "Help maintain the lighthouse museum. $18/hour, 15 hours a week, on site in St. Marks. Apply on our careers page."}
SCAM = {"title": "Remote Admin Assistant", "company": "QuickCash Staffing",
        "description": "Part-time remote lighthouse assistant, $500 weekly, no experience needed. We will send you a check to buy "
                       "office equipment from our vendor. Deposit it and send the rest by Zelle."}


@pytest.fixture
def toy(tmp_path, monkeypatch):
    p = tmp_path / "scam_model.json"
    p.write_text(json.dumps(TOY))
    monkeypatch.setattr(ml, "MODEL_PATH", p)
    monkeypatch.delenv("SCAM_MODEL", raising=False)
    return p


def test_no_model_file_means_rules_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODEL_PATH", tmp_path / "missing.json")
    assert ml.load() is None and ml.second_look(QUIET["title"], QUIET["description"]) is None


def test_second_look_explains_itself(toy):
    f = ml.second_look(QUIET["title"], QUIET["description"], QUIET["company"])
    assert f["rule_id"] == "model_second_look" and f["weight"] == 0 and '"lighthouse"' in f["matched"]
    assert "never rejects" in f["why"] and "12 labeled listings" in f["why"]


def test_switch_off(toy, monkeypatch):
    monkeypatch.setenv("SCAM_MODEL", "off")
    assert ml.second_look(QUIET["title"], QUIET["description"]) is None


def test_listing_check_raises_quiet_to_careful_and_never_touches_a_scam(toy):
    import msgcheck
    r = msgcheck.check_listing(QUIET["title"], QUIET["description"], QUIET["company"])
    assert r["level"] == 1 and any(f["rule_id"] == "model_second_look" for f in r["findings"])
    s = msgcheck.check_listing(SCAM["title"], SCAM["description"], SCAM["company"])
    assert s["level"] == 3 and not any(f["rule_id"] == "model_second_look" for f in s["findings"])


def test_messages_are_not_scored_by_the_model_yet(toy):
    # every legit training example is a listing; the model has never seen a real recruiter email
    import msgcheck
    r = msgcheck.check("Hi, the lighthouse museum needs a weekend guide. $15/hour. Apply at the front desk.")
    assert r["level"] == 0 and not any(f["rule_id"] == "model_second_look" for f in r["findings"])


def test_collection_leftovers_are_not_features():
    t = ml.tokens("From: a@b.com\nSubject: Job\nDear [NAME REDACTED], see https://x.example (EMAIL REDACTED) [...]")
    assert not {"from", "subject", "redacted", "name", "https", "email"} & set(t) and "job" in t and "dear" in t


def test_submission_goes_to_reviewer_with_the_note(toy, client):
    out = client.appmod.add_job({**QUIET, "work_type": "onsite", "category": "Other", "apply_url": ""})
    assert out["scam_status"] == "flagged" and out["band"] == "clear"
    assert any(f["rule_id"] == "model_second_look" for f in out["findings"])


def test_gate_refuses_new_false_alarms_and_needs_a_real_gain():
    from scam_detector.tools.train_model import gate
    rules_h = {"scam": 11, "legit_flagged": []}
    rules_s = {"scam": 0, "legit_flagged": []}
    assert gate(rules_h, {"scam": 13, "legit_flagged": []}, rules_s, {"scam": 0, "legit_flagged": []}) == []
    assert "new false alarm" in " ".join(gate(rules_h, {"scam": 13, "legit_flagged": []}, rules_s, {"scam": 0, "legit_flagged": ["Camp Counselor"]}))
    assert gate(rules_h, {"scam": 10, "legit_flagged": []}, rules_s, rules_s)
    assert gate(rules_h, {"scam": 11, "legit_flagged": []}, rules_s, rules_s) == ["adds nothing over the rules on the holdout"]


def test_plain_python_inference_matches_scikit_learn(tmp_path):
    pytest.importorskip("sklearn")
    from scam_detector.tools import train_model as T
    rows = [r for f in T.TRAIN_FILES for r in T.load(T.DATA / f)]
    rule_ids = sorted({f["rule_id"] for r in rows for f in T.rules_for(r)["findings"]})
    trained = T.Trained(rows, rule_ids)
    model = ml.Model(trained.export(0.5, {}))
    test = [r for f in T.HOLDOUTS for r in T.load(T.DATA / f)]
    want = trained.proba(test)
    for r, p in zip(test, want):
        rr = T.rules_for(r)
        got = model.predict(r.get("title", ""), r.get("description", ""), r.get("company", ""), r.get("url") or "",
                            rr["findings"], rr["score"])["probability"]
        assert abs(got - p) < 1e-3, (r.get("title"), got, p)


def test_shipped_model_if_any_is_readable():
    if not ml.MODEL_PATH.exists():
        pytest.skip("no model has passed the gate yet")
    m = ml.load()
    assert m and 0.5 <= m.threshold < 1 and m.trained_on.get("rows")
