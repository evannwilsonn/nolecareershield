import pytest

import fit
import quals


def test_clean_rejects_protected_terms_and_bad_values():
    for bad in ({"kind": "skill", "label": "US citizenship"}, {"kind": "skill", "label": "under 25 years old"},
                {"kind": "standing", "label": "wizard"}, {"kind": "gpa", "label": "5"}, {"kind": "gradyear", "label": "soon"},
                {"kind": "nope", "label": "x"}):
        with pytest.raises(quals.QualError):
            quals.clean([bad])
    out = quals.clean([{"kind": "skill", "label": "Excel", "must": "1"}, {"kind": "skill", "label": "excel"}, {"kind": "standing", "label": "Juniors"}])
    assert out == [{"kind": "skill", "label": "Excel", "must": True}, {"kind": "standing", "label": "junior", "must": False}]


def test_chosen_qualifications_drive_match_and_checklist():
    job = {"title": "Assistant", "description": "Help around the office.", "requirements": [
        {"kind": "skill", "label": "Excel", "must": True}, {"kind": "skill", "label": "Tableau", "must": False},
        {"kind": "major", "label": "Marketing", "must": True}]}
    p = {"skills": ["Excel"], "major": "Marketing", "items": []}
    f = fit.fit_score(job, p)
    status = {c["text"]: (c["status"], c["must"]) for c in f["checklist"]}
    assert status["Excel"] == ("met", True)
    assert status["Tableau (preferred)"][0] == "missing"
    assert any(t.startswith("Major") and s[0] == "met" for t, s in status.items())
    assert f["percent"] == f["score"] and f["level"] in ("high", "medium", "low")
    assert f["met"] == 2 and f["total"] == 3
    assert fit.fit_score({**job, "requirements": []}, p)["total"] == 0
