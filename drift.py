"""
Drift monitor: does the traffic the model sees this week still look like what it was trained on?

What it records (ml.MONITOR, set by configure()): for every listing check, the model's probability, whether it flagged,
and the share of the text's words the model has never seen (novelty). Only the posting's hash, never the text.

What it compares: the model file carries `drift_ref`, the distribution of those same numbers over the training rows
(out-of-fold, so they are honest). Each is compared with the live window as a Population Stability Index:
    PSI = sum over bins of (live_share - ref_share) * ln(live_share / ref_share)
Under 0.1 is noise, 0.1 to 0.25 is a shift worth a look, over 0.25 is a different population.

What it does with it
  * /admin/intel shows an alert when the score or novelty distribution has moved (PSI >= 0.25) or the model is guessing
    (mean novelty well above training).
  * learning.due_detail() treats a sustained shift as evidence: it brings the next retrain forward (subject to the usual
    minimum gap and the need for new labels). Drift never ships a model by itself; the release gate still decides.
  * The label queue's "Random check of a safe result" sampling is unchanged; drift tells reviewers where to look.

Everything here is best-effort: a failed write or a missing table never reaches a scam check.
"""

from __future__ import annotations

import logging
import math
import os
import time

import store
from scam_detector import ml

log = logging.getLogger("nolecareershield.drift")

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_traffic (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, key TEXT NOT NULL,
    version TEXT NOT NULL, p REAL NOT NULL, flag INTEGER NOT NULL, novelty REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_model_traffic_at ON model_traffic(at);
"""
WINDOW_DAYS = float(os.environ.get("DRIFT_WINDOW_DAYS", "7"))
MIN_CHECKS = int(os.environ.get("DRIFT_MIN_CHECKS", "50"))        # fewer than this and no PSI is computed
PSI_WATCH = 0.1
PSI_ALERT = float(os.environ.get("DRIFT_PSI_ALERT", "0.25"))
NOVELTY_ALERT = float(os.environ.get("DRIFT_NOVELTY_ALERT", "0.15"))   # live mean novelty this far above training
KEEP_DAYS = 120
BINS = 10


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def record(key: str, pred: dict, novelty: float) -> None:
    try:
        with store.db() as conn:
            conn.execute("INSERT INTO model_traffic (at, key, version, p, flag, novelty) VALUES (?,?,?,?,?,?)",
                         (time.time(), key, pred.get("version", ""), float(pred["probability"]), int(bool(pred["flag"])), float(novelty)))
    except Exception:                                   # noqa: BLE001
        log.exception("could not record model traffic")


def configure() -> None:
    ml.MONITOR = record


# ---------- the comparison ----------

def histogram(values, bins: int = BINS) -> list[float]:
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, max(0, int(float(v) * bins)))] += 1
    n = max(1, len(values))
    return [c / n for c in counts]


def psi(live: list[float], ref: list[float], eps: float = 1e-4) -> float:
    """Population Stability Index between two share histograms of the same bins."""
    total = 0.0
    for a, b in zip(live, ref):
        a, b = max(a, eps), max(b, eps)
        total += (a - b) * math.log(a / b)
    return round(total, 4)


def status(conn, model: ml.Model | None = None, window_days: float = WINDOW_DAYS) -> dict:
    """What the live window looks like against the training reference. Always returns something; `measured` says whether
    there was enough traffic to mean anything."""
    m = model or ml.load()
    ref = (m.spec.get("drift_ref") if m else None) or {}
    since = time.time() - window_days * 86400
    rows = store.rows(conn, "SELECT p, flag, novelty FROM model_traffic WHERE at > ?", (since,))
    out = {"window_days": window_days, "checks": len(rows), "measured": False, "reference": bool(ref), "version": m.version if m else None,
           "psi_score": None, "psi_novelty": None, "flag_rate": None, "novelty_mean": None,
           "ref_flag_rate": ref.get("flag_rate"), "ref_novelty_mean": ref.get("novelty_mean"), "level": "ok", "why": ""}
    if not rows:
        out["why"] = "no listing checks recorded yet"
        return out
    ps, ns = [r["p"] for r in rows], [r["novelty"] for r in rows]
    out["flag_rate"] = round(sum(r["flag"] for r in rows) / len(rows), 4)
    out["novelty_mean"] = round(sum(ns) / len(ns), 4)
    if not ref:
        out["why"] = "this model file has no training reference (retrain to add one)"
        return out
    if len(rows) < MIN_CHECKS:
        out["why"] = f"{len(rows)} checks in the window; {MIN_CHECKS} needed before the comparison means anything"
        return out
    out["measured"] = True
    out["psi_score"] = psi(histogram(ps), ref.get("score_hist", []))
    out["psi_novelty"] = psi(histogram(ns), ref.get("novelty_hist", []))
    nov_up = out["novelty_mean"] - float(ref.get("novelty_mean", 0.0))
    reasons = []
    if out["psi_score"] >= PSI_ALERT:
        reasons.append(f"the spread of model scores has moved (PSI {out['psi_score']:.2f})")
    if out["psi_novelty"] >= PSI_ALERT:
        reasons.append(f"the wording being checked has moved away from the training set (PSI {out['psi_novelty']:.2f})")
    if nov_up >= NOVELTY_ALERT:
        reasons.append(f"{out['novelty_mean']:.0%} of words are new to the model, against {float(ref.get('novelty_mean', 0)):.0%} in training")
    if reasons:
        out["level"], out["why"] = "drift", "; ".join(reasons)
    elif max(out["psi_score"], out["psi_novelty"]) >= PSI_WATCH:
        out["level"], out["why"] = "watch", f"a small shift (PSI {max(out['psi_score'], out['psi_novelty']):.2f}); nothing to do yet"
    else:
        out["why"] = "traffic looks like the training data"
    return out


def drifted(conn) -> tuple[bool, str]:
    """For learning.due_detail(): is there a measured shift that should bring the retrain forward?"""
    try:
        s = status(conn)
        return s["level"] == "drift", s["why"]
    except Exception:                                   # noqa: BLE001
        return False, ""


def alert(conn) -> dict | None:
    """For defense.alerts(): one card when the model's world has shifted."""
    try:
        s = status(conn)
    except Exception:                                   # noqa: BLE001
        return None
    if s["level"] != "drift":
        return None
    return {"level": "warn", "title": f"Model drift: {s['why']}",
            "detail": (f"Over the last {int(s['window_days'])} days ({s['checks']} listing checks). The model still only escalates, "
                       "but its confidence means less on text it hasn't seen. New labels from this period will bring the next retrain forward; "
                       "the random 'safe result' checks in the label queue are the fastest way to add them."),
            "ids": [], "kind": "drift"}


def prune(conn, keep_days: float = KEEP_DAYS) -> None:
    conn.execute("DELETE FROM model_traffic WHERE at < ?", (time.time() - keep_days * 86400,))


def html(conn) -> str:
    """A short status block for /admin/model."""
    from ui import esc
    s = status(conn)
    tone = {"ok": "ok", "watch": "warn", "drift": "bad"}[s["level"]]
    lines = [f"<p class='drift drift-{tone}'><strong>Drift:</strong> {esc(s['why'])}</p>"]
    if s["checks"]:
        parts = [f"{s['checks']} checks in {int(s['window_days'])} days", f"flag rate {s['flag_rate']:.1%}"]
        if s["ref_flag_rate"] is not None:
            parts[-1] += f" (training {s['ref_flag_rate']:.1%})"
        parts.append(f"new words {s['novelty_mean']:.0%}" + (f" (training {s['ref_novelty_mean']:.0%})" if s["ref_novelty_mean"] is not None else ""))
        if s["measured"]:
            parts.append(f"PSI scores {s['psi_score']:.2f}, wording {s['psi_novelty']:.2f}")
        lines.append("<p class='muted'>" + esc(" · ".join(parts)) + "</p>")
    return "\n".join(lines)
