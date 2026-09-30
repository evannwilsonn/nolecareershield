"""demo/ml.js must give the same answers as scam_detector/ml.py on the shipped model. Needs Node; skipped without it."""
import json, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


def test_browser_model_matches_python():
    from scam_detector import ml
    from scam_detector.scorer import score_posting
    model = ml.load()
    if model is None:
        pytest.skip("no model has passed the gate yet")
    rows = []
    for f in sorted((ROOT / "scam_detector" / "data").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                s = score_posting(r.get("title", ""), r.get("description", ""), r.get("company", ""), run_network=False)
                rows.append({"title": r.get("title", ""), "description": r.get("description", ""), "company": r.get("company", ""),
                             "url": r.get("url") or "", "findings": s.findings, "score": s.score})
    js = r"""
const fs = require("fs");
globalThis.NCS_RULEPACK = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const NCS = require(process.argv[3]);
const M = require(process.argv[4]).create(JSON.parse(fs.readFileSync(process.argv[5], "utf8")), NCS.normalize);
const rows = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(rows.map(r => M.predict(r.title, r.description, r.company, r.url, r.findings, r.score))));
"""
    script = ROOT / "tests" / "_ml_parity.js"
    script.write_text(js)
    try:
        res = subprocess.run([NODE, str(script), str(ROOT / "scam_detector" / "rulepack" / "core.json"), str(ROOT / "demo" / "engine.js"),
                              str(ROOT / "demo" / "ml.js"), str(ml.MODEL_PATH)],
                             input=json.dumps(rows), capture_output=True, text=True, timeout=120)
    finally:
        script.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr[-2000:]
    out = res.stdout
    got = json.loads(out)
    assert len(got) == len(rows) > 300
    for r, g in zip(rows, got):
        want = model.predict(r["title"], r["description"], r["company"], r["url"], r["findings"], r["score"])
        assert abs(want["probability"] - g["probability"]) < 1e-4 and want["flag"] == g["flag"], (r["title"], want, g)
