"""
How a retrained scam model reaches students: the expanded gate, a background comparison, a staged rollout and
automatic rollback. The active model keeps serving the whole time, until a candidate has earned each step.

1. Gate (at training time). train_model.py's own gate runs first. Then a candidate must, against the active model:
   - catch more of the recent confirmed scams it never trained on (the live holdout), or all of them if the active
     model already does;
   - keep false alarms on every legitimate item within FP_MAX_RATE and add none that the active model doesn't make;
   - lose nothing on the older frozen holdouts (earlier scam techniques);
   - add no false alarm on the hard legitimate set (real but unusual employers);
   - lose no scam campaign held out of training (whole waves are held out together);
   - catch at least as many red-team regression variants.
2. Shadow (SHADOW_DAYS). The candidate scores every listing check alongside the active model; nothing it says is
   shown. It moves on only if labels that arrived after it was built (so it never saw them) show it's no worse, and its
   flag rate on real traffic isn't far above the active model's.
3. Rollout (STAGES percent of listings, STAGE_DAYS each). A stable slice of listings is served by the candidate. The
   same checks run at every step; if the candidate does worse on fresh labels or its flag rate jumps, it's rolled back.
4. Watch (after 100%). The new model is active and the old one is kept. If fresh labels show the new one doing worse
   than the old one, the old one is restored automatically.

MODEL_AUTO_RELEASE=0 stops at "ready" before each step so a reviewer presses the button instead. Rollback is always
automatic. Every step is written to release_log and shown on /admin/model.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

import store
from scam_detector import ml
from scam_detector.scorer import score_posting

log = logging.getLogger("nolecareershield.release")

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_release (id INTEGER PRIMARY KEY CHECK (id = 1), stage TEXT NOT NULL DEFAULT 'none',
    candidate_version TEXT, run_id INTEGER, pct INTEGER NOT NULL DEFAULT 0, created_at REAL, stage_started REAL,
    note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS release_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, event TEXT NOT NULL,
    version TEXT, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS model_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, key TEXT NOT NULL,
    served TEXT NOT NULL, flag INTEGER NOT NULL, p REAL NOT NULL, other TEXT, other_flag INTEGER, other_p REAL);
CREATE INDEX IF NOT EXISTS ix_model_decisions_at ON model_decisions(at);
CREATE INDEX IF NOT EXISTS ix_model_decisions_key ON model_decisions(key);
"""

SHADOW_DAYS = float(os.environ.get("RELEASE_SHADOW_DAYS", "7"))
STAGE_DAYS = float(os.environ.get("RELEASE_STAGE_DAYS", "3"))
WATCH_DAYS = float(os.environ.get("RELEASE_WATCH_DAYS", "14"))
STAGES = [int(x) for x in os.environ.get("RELEASE_STAGES", "10,50,100").split(",")]
FRESH_MIN = int(os.environ.get("RELEASE_FRESH_MIN", "5"))          # labels that arrived after the candidate was built
TRAFFIC_MIN = int(os.environ.get("RELEASE_TRAFFIC_MIN", "30"))     # listing checks scored by both models
FP_MAX_RATE = float(os.environ.get("RELEASE_FP_MAX_RATE", "0.02"))
RECENT_DAYS = 120


def auto() -> bool:
    return os.environ.get("MODEL_AUTO_RELEASE", "1").lower() not in ("0", "false", "no", "off")


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO model_release (id, stage) VALUES (1, 'none')")


def _dir() -> Path:
    import learning
    return learning.learn_dir() / "models"


def candidate_path() -> Path:
    return _dir() / "candidate.json"


def previous_path() -> Path:
    return _dir() / "previous.json"


def active_path() -> Path:
    import learning
    return learning.model_path()


def state(conn) -> dict:
    ensure_schema(conn)
    return dict(store.row(conn, "SELECT * FROM model_release WHERE id = 1"))


def _set(conn, **kw) -> None:
    cols = ", ".join(f"{k} = ?" for k in kw)
    conn.execute(f"UPDATE model_release SET {cols} WHERE id = 1", tuple(kw.values()))
    _cache["at"] = 0


def _log(conn, event: str, version: str | None, detail: str = "") -> None:
    conn.execute("INSERT INTO release_log (at, event, version, detail) VALUES (?,?,?,?)", (time.time(), event, version, detail[:4000]))
    log.info("model release %s %s: %s", event, version, detail[:200])


# ---------- evaluation ----------

def _rules(r: dict) -> dict:
    if "_rules" not in r:
        url = r.get("url") or r.get("apply_url") or ""
        res = score_posting(r.get("title", ""), r.get("description", ""), r.get("company", ""), run_network=False,
                            url_chain=[url] if url else None)
        r["_rules"] = {"findings": res.findings, "score": res.score, "flag": res.band in ("review", "block")}
    return r["_rules"]


def flags(model: ml.Model | None, rows: list[dict]) -> list[bool]:
    """What the site would do: the rules flag it, or (listings only) the model does."""
    out = []
    for r in rows:
        ru = _rules(r)
        f = ru["flag"]
        if not f and model is not None and r.get("kind", "listing") == "listing":
            f = model.predict(r.get("title", ""), r.get("description", ""), r.get("company", ""), r.get("url") or "",
                              ru["findings"], ru["score"])["flag"]
        out.append(bool(f))
    return out


def tally(rows: list[dict], fl: list[bool]) -> dict:
    t = {"scam": 0, "scam_total": 0, "legit_flagged": 0, "legit_total": 0}
    for r, f in zip(rows, fl):
        if r["label"] == "scam":
            t["scam_total"] += 1
            t["scam"] += f
        elif r["label"] == "legit":
            t["legit_total"] += 1
            t["legit_flagged"] += f
    return t


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("label") in ("scam", "legit"):
                r.setdefault("kind", "listing")
                rows.append(r)
    return rows


def suites(conn) -> dict:
    import learning
    from scam_detector.tools import redteam
    data = Path(ml.__file__).resolve().parent / "data"
    live = [r for r in learning.labeled_rows(conn) if r["label"] in ("scam", "legit")]
    cutoff = time.time() - RECENT_DAYS * 86400
    return {
        "recent": [r for r in live if r["split"] == "holdout" and (r.get("reviewed_at") or 0) > cutoff],
        "older": [r for f in ("field_2026_09_holdout.jsonl", "field_2026_10_holdout.jsonl") for r in _load_jsonl(data / f)],
        "hard_legit": _load_jsonl(data / "stress_legit.jsonl"),
        "redteam": _load_jsonl(Path(redteam.REGRESSION)),
        "live_holdout": [r for r in live if r["split"] == "holdout"],
    }


def gate(candidate: ml.Model, active: ml.Model | None, conn) -> tuple[bool, list[dict]]:
    """The expanded gate. Returns (passed, [{name, passed, detail}])."""
    s = suites(conn)
    checks = []

    def both(rows):
        return tally(rows, flags(candidate, rows)), tally(rows, flags(active, rows))

    c, a = both(s["recent"])
    if not c["scam_total"]:
        checks.append({"name": "Recent confirmed scams", "passed": False,
                       "detail": "No recent confirmed scams in the live holdout to test on, so it can't show an improvement."})
    else:
        ok = c["scam"] > a["scam"] or c["scam"] == a["scam"] == a["scam_total"]
        checks.append({"name": "Recent confirmed scams", "passed": ok,
                       "detail": f"candidate {c['scam']}/{c['scam_total']}, active {a['scam']}/{a['scam_total']}"})
    everything = s["recent"] + s["older"] + s["hard_legit"] + s["live_holdout"]
    seen, legit = set(), []
    for r in everything:
        k = r.get("id") or r.get("description", "")[:80]
        if r["label"] == "legit" and k not in seen:
            seen.add(k)
            legit.append(r)
    cl, al = both(legit)
    rate = cl["legit_flagged"] / cl["legit_total"] if cl["legit_total"] else 0.0
    checks.append({"name": "False alarms on legitimate items", "passed": rate <= FP_MAX_RATE and cl["legit_flagged"] <= al["legit_flagged"],
                   "detail": f"candidate {cl['legit_flagged']}/{cl['legit_total']} ({rate:.1%}, limit {FP_MAX_RATE:.0%}), "
                             f"active {al['legit_flagged']}/{al['legit_total']}"})
    c, a = both(s["older"])
    checks.append({"name": "Older scam techniques (frozen holdouts)", "passed": c["scam"] >= a["scam"],
                   "detail": f"candidate {c['scam']}/{c['scam_total']}, active {a['scam']}/{a['scam_total']}"})
    c, a = both(s["hard_legit"])
    checks.append({"name": "Legitimate but unusual employers", "passed": c["legit_flagged"] <= a["legit_flagged"],
                   "detail": f"candidate flags {c['legit_flagged']}/{c['legit_total']}, active {a['legit_flagged']}/{a['legit_total']}"})
    camps: dict = {}
    for r in s["live_holdout"]:
        if r["label"] == "scam":
            camps.setdefault(r.get("campaign") or r["id"], []).append(r)
    lost = []
    for k, rows in camps.items():
        cf, af = flags(candidate, rows), flags(active, rows)
        if any(af) and not any(cf):
            lost.append(str(k))
    checks.append({"name": "Scam campaigns held out of training", "passed": not lost,
                   "detail": (f"{len(camps)} held-out campaigns; " + (f"lost: {', '.join(lost[:5])}" if lost else "none lost")) if camps
                   else "no held-out campaigns yet"})
    c, a = both(s["redteam"])
    checks.append({"name": "Red-team regression variants", "passed": c["scam"] >= a["scam"],
                   "detail": f"candidate {c['scam']}/{c['scam_total']}, active {a['scam']}/{a['scam_total']}" if c["scam_total"]
                   else "no regression variants saved yet"})
    return all(x["passed"] for x in checks), checks


def fresh(conn, since: float, first: ml.Model | None, second: ml.Model | None) -> dict:
    """Both models on labels confirmed after `since` (neither trained on them)."""
    import learning
    rows = [r for r in learning.labeled_rows(conn) if r["label"] in ("scam", "legit") and (r.get("reviewed_at") or 0) > since]
    return {"n": len(rows), "first": tally(rows, flags(first, rows)), "second": tally(rows, flags(second, rows))}


def traffic(conn, since: float) -> dict:
    r = conn.execute("""SELECT COUNT(*), SUM(flag), SUM(other_flag) FROM model_decisions
                        WHERE at > ? AND other IS NOT NULL""", (since,)).fetchone()
    return {"n": r[0] or 0, "served_flags": r[1] or 0, "other_flags": r[2] or 0}


def _cand_vs_active_traffic(conn, st: dict) -> tuple[int, float, float]:
    """(comparisons, candidate flag rate, active flag rate) on real listing checks since the stage began."""
    cv = st["candidate_version"]
    rows = conn.execute("""SELECT served, flag, other, other_flag FROM model_decisions WHERE at > ? AND other IS NOT NULL""",
                        (st["stage_started"] or 0,)).fetchall()
    n = len(rows)
    cf = sum((f if s == cv else of) for s, f, o, of in rows)
    af = sum((of if s == cv else f) for s, f, o, of in rows)
    return n, (cf / n if n else 0.0), (af / n if n else 0.0)


def worse(fr: dict) -> str:
    """Why the first model did worse than the second on fresh labels ('' if it didn't)."""
    a, b = fr["first"], fr["second"]
    if a["scam"] < b["scam"]:
        return f"caught fewer new confirmed scams ({a['scam']} vs {b['scam']} of {a['scam_total']})"
    if a["legit_flagged"] > b["legit_flagged"]:
        return f"flagged more new confirmed-real items ({a['legit_flagged']} vs {b['legit_flagged']} of {a['legit_total']})"
    return ""


# ---------- serving: which model answers, and what the other one would have said ----------

_cache = {"at": 0.0, "st": None, "cand": None}
_lock = threading.Lock()


def _current() -> tuple[dict | None, ml.Model | None]:
    now = time.time()
    if now - _cache["at"] > 30:
        try:
            with store.db() as conn:
                st = state(conn)
            cand = ml.load(candidate_path()) if st["stage"] in ("shadow", "rollout") and candidate_path().exists() else None
        except Exception:                                   # noqa: BLE001
            st, cand = None, None
        _cache.update(at=now, st=st, cand=cand)
    return _cache["st"], _cache["cand"]


def route(key: str, active: ml.Model):
    st, cand = _current()
    if not st or cand is None or cand.version == active.version:
        return active, None
    if st["stage"] == "rollout" and int(key[:8], 16) % 100 < int(st["pct"]):
        return cand, active
    return active, cand


def observe(key: str, served: str, pred: dict, other: str | None, other_pred: dict | None) -> None:
    try:
        with store.db() as conn:
            conn.execute("INSERT INTO model_decisions (at, key, served, flag, p, other, other_flag, other_p) VALUES (?,?,?,?,?,?,?,?)",
                         (time.time(), key, served, int(pred["flag"]), pred["probability"], other,
                          int(other_pred["flag"]) if other_pred else None, other_pred["probability"] if other_pred else None))
    except Exception:                                       # noqa: BLE001
        log.exception("could not record a model decision")


def configure() -> None:
    ml.ROUTE, ml.OBSERVE = route, observe


# ---------- the state machine ----------

def begin_shadow(conn, version: str, run_id: int | None, report: str = "") -> None:
    st = state(conn)
    if st["stage"] in ("shadow",) and st["candidate_version"]:
        _log(conn, "replaced", st["candidate_version"], f"replaced in shadow by {version}")
    _set(conn, stage="shadow", candidate_version=version, run_id=run_id, pct=0, created_at=time.time(), stage_started=time.time(),
         note="scoring alongside the active model")
    _log(conn, "shadow", version, report)


def discard(conn, why: str, event: str = "rejected") -> None:
    st = state(conn)
    _log(conn, event, st["candidate_version"], why)
    _set(conn, stage="none", pct=0, note=why)
    if candidate_path().exists():
        candidate_path().unlink()


def _promote(conn, st: dict) -> None:
    ap, cp, pp = active_path(), candidate_path(), previous_path()
    ap.parent.mkdir(parents=True, exist_ok=True)
    if ap.exists():
        shutil.copyfile(ap, pp)
    else:
        shutil.copyfile(ml.MODEL_PATH, pp)
    tmp = ap.with_suffix(".tmp")
    shutil.copyfile(cp, tmp)
    tmp.replace(ap)
    cp.unlink()
    _set(conn, stage="watch", pct=100, stage_started=time.time(), note="active; the previous model is kept for rollback")
    _log(conn, "promoted", st["candidate_version"], "now serving every listing")
    conn.execute("UPDATE model_runs SET status = 'shipped' WHERE id = ?", (st["run_id"],))


def rollback(conn, why: str) -> bool:
    """Restore the previous model (after a promotion), or drop a candidate that's mid-rollout."""
    st = state(conn)
    if st["stage"] in ("shadow", "rollout"):
        discard(conn, why, "rolled_back" if st["stage"] == "rollout" else "rejected")
        if st["run_id"]:
            conn.execute("UPDATE model_runs SET status = ? WHERE id = ?", ("rolled_back" if st["stage"] == "rollout" else "refused", st["run_id"]))
        return True
    pp = previous_path()
    if not pp.exists():
        return False
    bad = st["candidate_version"]
    tmp = active_path().with_suffix(".tmp")
    shutil.copyfile(pp, tmp)
    tmp.replace(active_path())
    pp.unlink()
    _set(conn, stage="none", pct=0, note=f"restored the previous model: {why}")
    _log(conn, "rolled_back", bad, why)
    if st["run_id"]:
        conn.execute("UPDATE model_runs SET status = 'rolled_back' WHERE id = ?", (st["run_id"],))
    return True


def start_rollout(conn, pct: int | None = None, who: str = "") -> None:
    st = state(conn)
    pct = pct or STAGES[0]
    _set(conn, stage="rollout", pct=pct, stage_started=time.time(), note=f"serving {pct}% of listings")
    _log(conn, "rollout", st["candidate_version"], f"{pct}% of listings" + (f" (started by {who})" if who else ""))


def tick(now: float | None = None) -> str:
    """Advance, hold or roll back the release by what the evidence says. Called by the daily maintenance."""
    now = now or time.time()
    with _lock, store.db() as conn:
        st = state(conn)
        stage = st["stage"]
        if stage == "none":
            return "nothing in release"
        age_days = (now - (st["stage_started"] or now)) / 86400
        active = ml.load(active_path()) if active_path().exists() else ml.load(ml.MODEL_PATH)
        if stage in ("shadow", "rollout"):
            cand = ml.load(candidate_path()) if candidate_path().exists() else None
            if cand is None:
                discard(conn, "the candidate file is missing")
                return "discarded"
            fr = fresh(conn, st["created_at"] or 0, cand, active)
            why = worse(fr) if fr["n"] >= 1 else ""
            n, cr, ar = _cand_vs_active_traffic(conn, st)
            if not why and n >= TRAFFIC_MIN and cr > max(2 * ar, ar + 0.05):
                why = f"flags {cr:.0%} of real listing checks against the active model's {ar:.0%}"
            if why:
                rollback(conn, why)
                return f"stopped: {why}"
            need = SHADOW_DAYS if stage == "shadow" else STAGE_DAYS
            if age_days < need:
                doing = "scoring alongside" if stage == "shadow" else "serving %d%%" % int(st["pct"])
                _set(conn, note=f"{doing}: day {int(age_days) + 1} of {int(need)}")
                return "waiting: time"
            if fr["n"] < FRESH_MIN or (stage == "shadow" and n < TRAFFIC_MIN):
                _set(conn, note=f"waiting for evidence: {fr['n']}/{FRESH_MIN} new labels, {n}/{TRAFFIC_MIN} listing checks compared")
                return "waiting: evidence"
            if not auto():
                _set(conn, note="ready for the next step: press the button (automatic release is off)")
                return "ready"
            if stage == "shadow":
                start_rollout(conn)
                return "rollout started"
            nxt = [p for p in STAGES if p > int(st["pct"])]
            if not nxt or nxt[0] >= 100:
                _promote(conn, st)
                return "promoted"
            start_rollout(conn, nxt[0])
            return f"rollout {nxt[0]}%"
        if stage == "watch":
            prev = ml.load(previous_path()) if previous_path().exists() else None
            if prev is not None:
                fr = fresh(conn, st["stage_started"] or 0, active, prev)
                why = worse(fr)
                if why:
                    rollback(conn, "after release, the new model " + why)
                    return "rolled back"
            if age_days >= WATCH_DAYS:
                _set(conn, stage="none", note="release complete")
                _log(conn, "settled", st["candidate_version"], f"no problems in {int(WATCH_DAYS)} days")
                return "settled"
            return "watching"
    return ""
