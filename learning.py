"""
The scam detector's learning loop: people label, the model retrains itself, and a gate decides what ships.

1. Labels come from two places: reviewers approving or rejecting board listings (jobs.review_label), and things
   people sent in from the scam check ("Send this to our reviewers"), which a reviewer confirms in the label queue.
   Nothing a visitor says becomes a label on its own; a reviewer always decides, so the model can't be poisoned
   by someone spamming "not a scam".
2. Scam waves: a sent-in item that near-copies another from the last 30 days joins its campaign, so one decision
   labels the whole wave and the reviewer sees how big it is.
3. Rolling holdout: the first time a confirmed label is used, it is put in the training set or the live holdout
   (about 1 in 3, whole campaigns together) and stays there. Every retrain must do well on the latest
   holdout, not only on September's.
4. Monthly retrain: when it's been RETRAIN_DAYS since the last run and at least RETRAIN_MIN_NEW new labels exist,
   the maintenance loop retrains in the background. scam_detector/tools/train_model.py writes the new model only
   if it beats the rules and the current model on every frozen holdout with no new false alarm. Otherwise the
   current model stays. Every run is recorded (model_runs) and shown at /admin/model.

The live model lives next to the database (learning/models/scam_model.json) and ml.active_path() prefers it over
the one in the repo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Cookie, Form
from fastapi.responses import HTMLResponse, RedirectResponse

import admin_extra
import store
import ui
from export_labeled import mask
from scam_detector import ml
from ui import esc

router = APIRouter()
log = logging.getLogger("nolecareershield.learning")

LABELS = ("scam", "legit", "lead_gen")
NEAR_COPY = 0.6                  # word-trigram overlap that counts as the same template (same as train_model)
WAVE_DAYS = 30
RETRAIN_DAYS = float(os.environ.get("RETRAIN_DAYS", "30"))
RETRAIN_MIN_NEW = int(os.environ.get("RETRAIN_MIN_NEW", "20"))      # distinct new labels for the monthly fallback
EVIDENCE_MIN_NEW = int(os.environ.get("RETRAIN_EVIDENCE_MIN", "30"))  # distinct new labels that trigger a retrain early
CAMPAIGN_MIN = int(os.environ.get("RETRAIN_CAMPAIGN_MIN", "3"))      # labeled reports behind a confirmed new campaign
MIN_GAP_DAYS = float(os.environ.get("RETRAIN_MIN_GAP_DAYS", "3"))    # never retrain more often than this
WAVE_CAP = int(os.environ.get("RETRAIN_WAVE_CAP", "3"))              # most rows one scam wave may contribute to training
HOLDOUT_EVERY = 3                # about 1 in 3 new labels is held out
_lock = threading.Lock()


def learn_dir() -> Path:
    return Path(store.db_path()).resolve().parent / "learning"


def model_path() -> Path:
    return learn_dir() / "models" / "scam_model.json"


def configure() -> None:
    """Point the detector at the live model (called at startup)."""
    os.environ["SCAM_MODEL_PATH"] = str(model_path())
    import release
    release.configure()


# ---------- scam waves ----------

def _shingles(text: str) -> set:
    t = ml.tokens(text)
    return {" ".join(t[i:i + 3]) for i in range(max(1, len(t) - 2))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def add_submission(conn, *, body: str, sender: str = "", band: str = "", user_label: str = "", user_id=None,
                   kind: str = "message", title: str = "", company: str = "", url: str = "", source: str = "student") -> int:
    """Save something sent in from the scam check, joining it to a scam wave if it near-copies a recent one."""
    now = time.time()
    sh = _shingles(f"{title}\n{body}")
    best = None
    for r in store.rows(conn, "SELECT id, title, body, campaign FROM submitted_checks WHERE created_at > ? ORDER BY id DESC LIMIT 400",
                        (now - WAVE_DAYS * 86400,)):
        j = _jaccard(sh, _shingles(f"{r['title']}\n{r['body']}"))
        if j >= NEAR_COPY and (best is None or j > best[0]):
            best = (j, r)
    campaign = None
    if best:
        campaign = best[1]["campaign"] or best[1]["id"]
        conn.execute("UPDATE submitted_checks SET campaign = ? WHERE id = ? AND campaign IS NULL", (campaign, best[1]["id"]))
    cur = conn.execute("""INSERT INTO submitted_checks (user_id, body, sender, band, user_label, created_at, kind, title, company, url,
                          source, campaign) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (user_id, body, sender[:200], band, user_label, now, kind, title[:200], company[:200], url[:2000], source, campaign))
    import defense
    defense.index_check(conn, cur.lastrowid, "\n".join((title, company, body, sender, url)))
    return cur.lastrowid


# ---------- labeled data ----------

def _assign_splits(conn) -> None:
    """Give every newly confirmed label a permanent place: training or the live holdout. Campaigns stay together."""
    for table, key in (("jobs", "j"), ("submitted_checks", "c")):
        rows = store.rows(conn, f"SELECT * FROM {table} WHERE review_label IN ('scam','legit','lead_gen') AND learn_split IS NULL")
        for r in rows:
            split = None
            if table == "submitted_checks" and r["campaign"]:
                got = conn.execute("SELECT learn_split FROM submitted_checks WHERE (campaign = ? OR id = ?) AND learn_split IS NOT NULL LIMIT 1",
                                   (r["campaign"], r["campaign"])).fetchone()
                split = got[0] if got else None
                seed = f"c{r['campaign']}"
            else:
                seed = f"{key}{r['id']}"
            if not split:
                split = "holdout" if int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % HOLDOUT_EVERY == 0 else "train"
            conn.execute(f"UPDATE {table} SET learn_split = ? WHERE id = ?", (split, r["id"]))


def labeled_rows(conn) -> list[dict]:
    """Every confirmed label from the live board, masked, in the detector's corpus format."""
    out = []
    import defense
    for r in store.rows(conn, "SELECT * FROM jobs WHERE review_label IN ('scam','legit','lead_gen') ORDER BY id"):
        out.append({"id": f"live-j{r['id']}", "label": r["review_label"], "kind": "listing", "title": mask(r["title"]),
                    "company": mask(r["company"]), "description": mask(r["description"]), "url": r["apply_url"] or "",
                    "split": r["learn_split"], "context_flags": [], "reviewed_at": defense._ts(r["reviewed_at"]), "campaign": None,
                    "notes": f"board listing, reviewer label{' by ' + r['reviewer'] if r.get('reviewer') else ''}; "
                             f"detector band={r['band']} score={r['score']}"})
    for r in store.rows(conn, "SELECT * FROM submitted_checks WHERE review_label IN ('scam','legit','lead_gen') ORDER BY id"):
        desc = r["body"] if r["kind"] == "listing" else r["body"] + (f"\n{r['sender']}" if r["sender"] else "")
        out.append({"id": f"live-c{r['id']}", "label": r["review_label"], "kind": r["kind"], "title": mask(r["title"]),
                    "company": mask(r["company"]), "description": mask(desc), "url": r["url"] or "", "split": r["learn_split"],
                    "context_flags": [], "reviewed_at": r["reviewed_at"] or 0, "campaign": r["campaign"] or r["id"],
                    "notes": f"sent in from the scam check ({r['source']}), reviewer label"
                             f"{' by ' + r['reviewer'] if r['reviewer'] else ''}{' (' + r['review_reason'] + ')' if r['review_reason'] else ''}; "
                             f"student said {r['user_label'] or '-'}; detector band={r['band']}"})
    return out


# ---------- the monthly retrain ----------

def _since(conn, t: float) -> int:
    """Distinct new labels since t: a scam wave labeled all at once counts once, so one campaign can't trigger a retrain."""
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t))
    return (conn.execute("SELECT COUNT(DISTINCT COALESCE(campaign, id)) FROM submitted_checks WHERE review_label IN ('scam','legit','lead_gen') "
                         "AND reviewed_at > ?", (t,)).fetchone()[0]
            + conn.execute("SELECT COUNT(*) FROM jobs WHERE review_label IN ('scam','legit','lead_gen') AND reviewed_at > ?", (iso,)).fetchone()[0])


def due_detail(conn) -> tuple[bool, str, str]:
    """(due, why, trigger). Monthly when enough distinct labels exist; earlier when a lot of new evidence arrives or a reviewer
    confirms a new scam campaign; never more often than MIN_GAP_DAYS, and not while a release is being rolled out."""
    import release
    st = release.state(conn)
    if st["stage"] in ("rollout", "watch"):
        return False, f"a model release is in progress ({st['stage']}); retraining waits until it settles", ""
    last = store.row(conn, "SELECT * FROM model_runs WHERE status IN ('shipped','refused','candidate','rolled_back') ORDER BY started_at DESC LIMIT 1")
    since = last["started_at"] if last else 0.0
    elapsed = (time.time() - since) / 86400 if last else 1e9
    new = _since(conn, since)
    if elapsed >= MIN_GAP_DAYS:
        import cases
        camp = [c for c in cases.confirmed_since(conn, since) if json.loads(c["summary"] or "{}").get("distinct", 0) >= CAMPAIGN_MIN]
        if camp:
            return True, f"reviewer confirmed a new scam campaign (case #{camp[0]['id']}); {new} new distinct labels", "new_campaign"
        if new >= EVIDENCE_MIN_NEW:
            return True, f"{new} new distinct labels (early retrain at {EVIDENCE_MIN_NEW})", "evidence"
    if elapsed < RETRAIN_DAYS:
        days = int((since + RETRAIN_DAYS * 86400 - time.time()) // 86400) + 1
        return False, (f"next scheduled retrain in about {days} day{'s' if days != 1 else ''} "
                       f"(sooner at {EVIDENCE_MIN_NEW} distinct new labels or a confirmed new campaign; {new} so far)"), ""
    if new < RETRAIN_MIN_NEW:
        return False, f"waiting for labels: {new} new of the {RETRAIN_MIN_NEW} needed", ""
    return True, f"{new} new distinct labels", "schedule"


def due(conn) -> tuple[bool, str]:
    ok, why, _ = due_detail(conn)
    return ok, why


def cap_waves(rows: list[dict], cap: int = WAVE_CAP) -> list[dict]:
    """At most `cap` training rows per scam wave (the earliest, the latest and ones between), so a template that was sent
    in or labeled hundreds of times counts like a few examples."""
    by: dict = {}
    for r in rows:
        by.setdefault(r.get("campaign") or r["id"], []).append(r)
    out = []
    for rs in by.values():
        if len(rs) <= cap:
            out += rs
        else:
            step = (len(rs) - 1) / (cap - 1) if cap > 1 else 0
            out += [rs[round(i * step)] for i in range(cap)]
    return out


def run_retrain(trigger: str = "schedule", force: bool = False) -> dict:
    """Retrain once. Returns {"status": shipped | refused | skipped | busy | unavailable | error, ...}."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        import release
        with store.db() as conn:
            if not force:
                ok, why = due(conn)
                if not ok:
                    return {"status": "skipped", "why": why}
            elif release.state(conn)["stage"] in ("rollout", "watch"):
                return {"status": "skipped", "why": "a model release is in progress"}
            _assign_splits(conn)
            rows = labeled_rows(conn)
            run_id = conn.execute("INSERT INTO model_runs (started_at, trigger, live_labels) VALUES (?,?,?)",
                                  (time.time(), trigger, len(rows))).lastrowid
        try:
            from scam_detector.tools import train_model
        except (ImportError, SystemExit):
            return _finish(run_id, "unavailable", report="scikit-learn isn't installed on this server, so it can't retrain. "
                                                         "Install requirements.txt (it lists scikit-learn).")
        d = learn_dir()
        (d / "models").mkdir(parents=True, exist_ok=True)
        train_f, hold_f = d / "live_train.jsonl", d / "live_holdout.jsonl"
        train_rows = cap_waves([r for r in rows if r["split"] == "train"])
        train_f.write_text("".join(json.dumps(r) + "\n" for r in train_rows))
        held = [r for r in rows if r["split"] == "holdout"]
        hold_f.write_text("".join(json.dumps(r) + "\n" for r in held))
        cand = release.candidate_path()
        if cand.exists():
            cand.unlink()
        argv = ["--extra", str(train_f), "--out", str(cand), "--current", str(ml.active_path()), "--report-dir", str(d / "models")]
        if held:
            argv[2:2] = ["--holdout-extra", str(hold_f)]
        try:
            train_model.main(argv)
        except Exception as e:                          # noqa: BLE001 - a failed retrain must never take the site down
            log.exception("retrain failed")
            return _finish(run_id, "error", report=f"Training failed: {type(e).__name__}: {e}")
        res = train_model.LAST_RESULT
        report = res.get("report", "")
        if not res.get("written") or not cand.exists():
            return _finish(run_id, "refused", version=res.get("version"), train_rows=res.get("rows", 0), report=report)
        with store.db() as conn:                        # the expanded gate: against the ACTIVE model, on what the site cares about
            candidate, active = ml.Model(json.loads(cand.read_text())), ml.load(ml.active_path())
            passed, checks = release.gate(candidate, active, conn)
            report += "\n\n## Release gate (candidate vs the active model)\n\n| Check | Result | Detail |\n|---|---|---|\n" + "".join(
                f"| {c['name']} | {'pass' if c['passed'] else 'FAIL'} | {c['detail']} |\n" for c in checks)
            if not passed:
                cand.unlink()
                return _finish(run_id, "refused", version=res.get("version"), train_rows=res.get("rows", 0), report=report)
            release.begin_shadow(conn, candidate.version, run_id, "passed the release gate")
        return _finish(run_id, "candidate", version=res.get("version"), train_rows=res.get("rows", 0),
                       report=report + "\nPassed. It now scores alongside the active model before any student sees it.")
    finally:
        _lock.release()


def _finish(run_id: int, status: str, version=None, train_rows: int = 0, report: str = "") -> dict:
    with store.db() as conn:
        conn.execute("UPDATE model_runs SET finished_at = ?, status = ?, version = ?, train_rows = ?, report = ? WHERE id = ?",
                     (time.time(), status, version, train_rows, report, run_id))
    log.info("model retrain %s: %s", run_id, status)
    return {"status": status, "version": version, "run": run_id}


def maybe_retrain() -> None:
    """Called by the site's maintenance loop: moves any release along (or rolls it back), then retrains in the background
    when due, so startup never waits."""
    import release
    try:
        release.tick()
    except Exception:                                   # noqa: BLE001
        log.exception("release step failed")
    try:
        with store.db() as conn:
            ok, _, trigger = due_detail(conn)
    except Exception:                                   # noqa: BLE001
        log.exception("retrain check failed")
        return
    if ok:
        threading.Thread(target=run_retrain, kwargs={"trigger": trigger or "schedule"}, daemon=True).start()


# ---------- reviewer pages ----------

def prioritize(groups: dict, rings: dict, scam_styles: list) -> list:
    """Active learning: show the items whose labels teach the model the most first. Uncertain model calls, disagreement
    between the detector, the student and the AI, new patterns, and rings; every fifth slot is a random pick so obvious
    but new scams aren't starved. Returns [(group key, rows, reasons)]."""
    import random
    from scam_detector.scorer import score_posting
    m = ml.load()
    scored = []
    for k, rs in groups.items():
        r = rs[0]
        why, score = [], 0.3 * min(4, len(rs))
        if m:
            res = score_posting(r["title"], r["body"], r["company"], run_network=False)
            p = m.predict(r["title"], r["body"], r["company"], r["url"], res.findings, res.score)
            closeness = 1 - min(1.0, abs(p["probability"] - m.threshold) / 0.5)
            score += closeness
            if p.get("uncertain"):
                score += 1
                why.append("Model unsure")
        said = {x["user_label"] for x in rs}
        if ("scam" in said and r["band"] in ("clear", "caution")) or ("legit" in said and r["band"] in ("review", "block")):
            score += 1
            why.append("Student and detector disagree")
        if any(x["source"] == "ai_novel" for x in rs):
            score += 1
        if any(x["source"] == "sample" for x in rs):
            score += 0.7                                  # the only way to find confident misses nobody reported
            why.append("Random check of a safe result")
        if len(rs) == 1 and not rings.get(k):
            score += 0.5
        if rings.get(k) and rings[k]["labels"].get("scam"):
            score += 0.5
        sv = defense_style(r)
        for sid, camp, vec in scam_styles:
            if camp != k and defense_cosine(sv, vec) >= 0.8:
                why.append(f"Writes like confirmed scam #{sid}")
                score += 0.5
                break
        scored.append((score, k, rs, why))
    scored.sort(key=lambda x: -x[0])
    rnd = random.Random(time.strftime("%Y-%m-%d"))
    rest = scored[:]
    out = []
    while rest:
        pick = rest.pop(rnd.randrange(len(rest))) if len(out) % 5 == 4 else rest.pop(0)
        out.append((pick[1], pick[2], pick[3] + (["Random pick"] if len(out) % 5 == 4 else [])))
    return out


def defense_web_whoami(session, back: str) -> str:
    import defense_web
    return defense_web.whoami_form(session, back)


def defense_style(r) -> dict:
    import defense
    return defense.style_vector(f"{r['title']}\n{r['body']}")


def defense_cosine(a, b) -> float:
    import defense
    return defense.cosine(a, b)


def pending_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM submitted_checks WHERE review_label IS NULL").fetchone()[0]


_LABEL_BTNS = [("scam", "Scam", "btn-reject"), ("legit", "Real", "btn-approve"), ("lead_gen", "Lead-gen", "btn-ghost"),
               ("skip", "Not a job / skip", "btn-ghost")]


@router.get("/admin/checks", response_class=HTMLResponse)
def label_queue(session: str | None = Cookie(default=None)):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = admin_extra._csrf(session)
    with store.db() as conn:
        pend = store.rows(conn, "SELECT * FROM submitted_checks WHERE review_label IS NULL ORDER BY created_at DESC LIMIT 400")
        groups: dict = {}
        for r in pend:
            groups.setdefault(r["campaign"] or f"i{r['id']}", []).append(r)
        prior = {}
        for k in groups:
            if isinstance(k, int):
                prior[k] = store.rows(conn, "SELECT review_label, COUNT(*) AS n FROM submitted_checks WHERE (campaign = ? OR id = ?) "
                                            "AND review_label IS NOT NULL GROUP BY review_label", (k, k))
        recent = store.rows(conn, "SELECT * FROM submitted_checks WHERE review_label IS NOT NULL ORDER BY reviewed_at DESC LIMIT 12")
        import defense
        ring_map = defense.rings(conn)
        rings = {k: defense.ring_summary(conn, rs[0]["id"], ring_map) for k, rs in groups.items()}
        scams = store.rows(conn, "SELECT id, campaign, title, body FROM submitted_checks WHERE review_label = 'scam' ORDER BY reviewed_at DESC LIMIT 200")
    scam_styles = [(s["id"], s["campaign"] or s["id"], defense.style_vector(f"{s['title']}\n{s['body']}")) for s in scams]
    ordered = prioritize(groups, rings, scam_styles)
    cards = ""
    for k, rs, why in ordered:
        r = rs[0]
        says = {}
        for x in rs:
            if x["user_label"]:
                says[x["user_label"]] = says.get(x["user_label"], 0) + 1
        tags = "".join(f'<span class="pill {"bad" if lab == "scam" else "ok" if lab == "legit" else ""}">{n} say {esc(lab)}</span>' for lab, n in says.items())
        if any(x["source"] == "ai_novel" for x in rs):
            tags += '<span class="pill warn">AI flagged a pattern the rules missed</span>'
        wave = (f'<span class="pill bad">Wave: {len(rs)} near-copies</span>' if len(rs) > 1 else "")
        ring = rings.get(k)
        if ring:
            lab = ", ".join(f"{n} {esc(l)}" for l, n in ring["labels"].items())
            wave += f'<span class="pill bad">Ring: shares contact details with {ring["size"] - 1} other report{"s" if ring["size"] != 2 else ""}{" (" + lab + ")" if lab else ""}</span>'
        tags += "".join(f'<span class="pill info">{esc(w)}</span>' for w in why)
        earlier = "".join(f'<span class="pill">{int(p["n"])} earlier labeled {esc(p["review_label"])}</span>' for p in prior.get(k, []))
        what = (f'<b>{esc(r["title"])}</b>' + (f' · {esc(r["company"])}' if r["company"] else "") if r["kind"] == "listing"
                else f'<b>Message</b>{(" from " + esc(r["sender"])) if r["sender"] else ""}')
        buttons = "".join(f'<button class="{cls}" name="label" value="{v}" type="submit">{esc(t)}{" all " + str(len(rs)) if len(rs) > 1 and v != "skip" else ""}</button>'
                          for v, t, cls in _LABEL_BTNS)
        cards += (f'<div class="rev-card"><div class="row between"><span>{what}</span><span class="row">{wave}{earlier}'
                  f'<span class="pill">detector: {esc(r["band"] or "-")}</span>{tags}</span></div>'
                  f'<p class="small muted">{esc(time.strftime("%Y-%m-%d", time.gmtime(rs[-1]["created_at"])))}'
                  f'{" to " + esc(time.strftime("%Y-%m-%d", time.gmtime(r["created_at"]))) if len(rs) > 1 else ""}</p>'
                  f'<div class="detail-desc" style="font-size:14px;max-height:200px;overflow:auto;white-space:pre-wrap">{esc(r["body"][:3000])}</div>'
                  f'<form class="rev-actions" method="post" action="/admin/checks/label">{csrf}<input type="hidden" name="group" value="{esc(str(k))}">'
                  f'<input name="reason" maxlength="300" placeholder="Why (optional): e.g. asks to deposit a check" style="flex:1;min-width:180px">{buttons}</form></div>')
    done = "".join(f'<li>{esc(time.strftime("%m-%d", time.gmtime(x["reviewed_at"] or x["created_at"])))} · '
                   f'<b>{esc(x["review_label"])}</b>{" by " + esc(x["reviewer"]) if x["reviewer"] else ""}'
                   f'{" (" + esc(x["review_reason"]) + ")" if x["review_reason"] else ""} · {esc((x["title"] or x["body"])[:80])}'
                   f'<form method="post" action="/admin/checks/undo" style="display:inline">{csrf}<input type="hidden" name="cid" value="{int(x["id"])}">'
                   f' <button class="linkbtn" type="submit">undo</button></form></li>' for x in recent)
    import defense
    body = (defense_web_whoami(session, "/admin/checks") + '<p class="lead">Things people sent in from the scam check. Your label is what the model learns from; '
            'nothing a visitor says counts until you confirm it. Near-copies from the last 30 days are grouped into one wave.</p>'
            + (cards or '<div class="empty">Nothing waiting. Labels you confirm train the next model.</div>')
            + (f'<h3 class="sec">Recently labeled</h3><ul class="small">{done}</ul>' if done else ""))
    return admin_extra._page(body, "Label queue", "/admin/checks")


@router.post("/admin/checks/label")
def label_group(group: str = Form(""), label: str = Form(""), reason: str = Form(""), session: str | None = Cookie(default=None),
                csrf: str = Form("")):
    if admin_extra._gate(session, csrf) and label in LABELS + ("skip",):
        import defense
        who, reason = defense.reviewer_name(session), reason.strip()[:300]
        with store.db() as conn:
            now = time.time()
            if group.startswith("i") and group[1:].isdigit():
                ids = [int(group[1:])]
                where, params = "id = ?", (ids[0],)
            elif group.isdigit():
                where, params = "(campaign = ? OR id = ?)", (int(group), int(group))
            else:
                return RedirectResponse("/admin/checks", status_code=303)
            ids = [r[0] for r in conn.execute(f"SELECT id FROM submitted_checks WHERE {where} AND review_label IS NULL", params)]
            for cid in ids:
                conn.execute("UPDATE submitted_checks SET review_label = ?, reviewed_at = ?, reviewer = ?, review_reason = ? WHERE id = ?",
                             (label, now, who, reason, cid))
                defense.log_label(conn, "check", cid, label, who, reason)
            defense.recheck(conn, defense.hashes_of(conn, "check", ids))
    return RedirectResponse("/admin/checks", status_code=303)


@router.post("/admin/checks/undo")
def label_undo(cid: int = Form(0), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if admin_extra._gate(session, csrf):
        with store.db() as conn:
            import defense
            conn.execute("UPDATE submitted_checks SET review_label = NULL, reviewed_at = NULL, reviewer = '', review_reason = '' WHERE id = ?", (cid,))
            defense.log_label(conn, "check", cid, None, defense.reviewer_name(session), "undo")
            defense.recheck(conn, defense.hashes_of(conn, "check", [cid]))    # verdicts that leaned on this label are recomputed
    return RedirectResponse("/admin/checks", status_code=303)


@router.get("/admin/model", response_class=HTMLResponse)
def model_page(session: str | None = Cookie(default=None), started: int = 0):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = admin_extra._csrf(session)
    m = ml.load()
    live = ml.active_path() != ml.MODEL_PATH
    with store.db() as conn:
        runs = store.rows(conn, "SELECT * FROM model_runs ORDER BY started_at DESC LIMIT 12")
        ok, why = due(conn)
        splits = {r[0] or "unused": r[1] for r in conn.execute(
            "SELECT learn_split, COUNT(*) FROM (SELECT learn_split FROM jobs WHERE review_label IN ('scam','legit','lead_gen') "
            "UNION ALL SELECT learn_split FROM submitted_checks WHERE review_label IN ('scam','legit','lead_gen')) GROUP BY learn_split")}
        pending = pending_count(conn)
        import release
        rel = release_html(conn, csrf)
    if m:
        h = m.spec.get("holdout", {})
        hr, hm = h.get("rules"), h.get("with_model")
        held = (f'On the frozen holdouts it catches <b>{hm[0]}/{hm[1]}</b> scams (rules alone {hr[0]}/{hr[1]}), '
                f'wrongly flagging {hm[2]} real job{"s" if hm[2] != 1 else ""}.' if hr and hm else "")
        cur = (f'<div class="card"><b>Active model</b> <span class="pill">{esc(m.version)}</span> '
               f'<span class="pill {"ok" if live else ""}">{"retrained on this board" if live else "shipped with the code"}</span>'
               f'<p class="small muted" style="margin-top:6px">Trained {esc(m.spec.get("trained_at", "?"))} on {int(m.trained_on.get("rows", 0))} labeled rows; '
               f'threshold {m.threshold:.2f}. {held} It can only raise a warning, never reject anything.</p></div>')
    else:
        cur = '<div class="card"><b>No model active.</b> <span class="small muted">The detector is running on rules alone.</span></div>'
    notice = ui.banner("verified", "Retraining started in the background. Refresh in a minute to see the result.") if started else ""
    label_line = (f'<p>Live labels: <b>{sum(splits.values())}</b> confirmed ({splits.get("train", 0)} training, '
                  f'{splits.get("holdout", 0)} frozen holdout, {splits.get("unused", 0)} not used yet). '
                  f'{pending} waiting in the <a href="/admin/checks">label queue</a>.</p>')
    sched = (f'<p class="small muted">Automatic retrain: {"due now" if ok else esc(why)}. Monthly once {RETRAIN_MIN_NEW} distinct new '
             f'labels exist; sooner at {EVIDENCE_MIN_NEW} distinct new labels or when a reviewer confirms a new scam campaign, never more '
             f'often than every {MIN_GAP_DAYS:g} days. A scam wave counts once and adds at most {WAVE_CAP} training rows. A new model '
             f'must pass the release gate, then scores alongside the active one before any student sees it.</p>')
    button = (f'<form method="post" action="/admin/model/retrain">{csrf}<button class="b" type="submit">Retrain now</button> '
              '<span class="small muted">Same gate as the monthly run.</span></form>')
    rows = "".join(f'<details class="card" style="margin-top:8px"><summary><b>{esc(time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["started_at"])))}</b> · '
                   f'{esc(r["trigger"])} · <span class="pill {"ok" if r["status"] in ("shipped", "candidate") else "bad" if r["status"] in ("error", "rolled_back") else ""}">{esc(r["status"])}</span>'
                   f'{" · " + esc(r["version"]) if r["version"] else ""} · {int(r["train_rows"])} rows</summary>'
                   f'<pre style="white-space:pre-wrap;font-size:12px">{esc(r["report"])}</pre></details>' for r in runs)
    body = (cur + rel + f'<div class="card" style="margin-top:12px;display:grid;gap:10px">{label_line}{sched}{button}</div>'
            + '<h3 class="sec">Training runs</h3>' + (rows or '<div class="empty">No runs yet.</div>'))
    return admin_extra._page(notice + body, "Model", "/admin/model")


STAGE_NAMES = {"none": "No release in progress", "shadow": "Scoring alongside the active model (students don't see it)",
               "rollout": "Serving part of the listings", "watch": "Released; watching against the previous model"}


def release_html(conn, csrf: str) -> str:
    import release
    st = release.state(conn)
    logs = store.rows(conn, "SELECT * FROM release_log ORDER BY id DESC LIMIT 12")
    tr = release._cand_vs_active_traffic(conn, st) if st["stage"] in ("shadow", "rollout") else None
    lines = "".join(f'<li>{esc(time.strftime("%Y-%m-%d %H:%M", time.gmtime(l["at"])))} · <b>{esc(l["event"])}</b>'
                    f'{" · " + esc(l["version"]) if l["version"] else ""}{" · " + esc(l["detail"][:300]) if l["detail"] else ""}</li>' for l in logs)
    btns = ""
    if st["stage"] == "shadow":
        btns += f'<button class="b sm" name="action" value="next">Start serving {release.STAGES[0]}%</button>'
    if st["stage"] == "rollout":
        btns += '<button class="b sm" name="action" value="next">Next step</button>'
    if st["stage"] in ("shadow", "rollout"):
        btns += '<button class="b sm ghost" name="action" value="stop">Stop and discard the candidate</button>'
    if st["stage"] == "watch" or (st["stage"] == "none" and release.previous_path().exists()):
        btns += '<button class="b sm ghost" name="action" value="rollback">Restore the previous model</button>'
    traffic = (f'<p class="small">Compared on {tr[0]} real listing checks: candidate flags {tr[1]:.0%}, active {tr[2]:.0%}.</p>' if tr else "")
    return (f'<div class="card" style="margin-top:12px"><b>Release</b> <span class="pill">{esc(st["stage"])}</span>'
            f'{" " + ("<span class=pill>" + esc(st["candidate_version"]) + "</span>") if st["candidate_version"] and st["stage"] != "none" else ""}'
            f'<p class="small">{esc(STAGE_NAMES.get(st["stage"], st["stage"]))}{" (" + str(st["pct"]) + "%)" if st["stage"] == "rollout" else ""}. '
            f'{esc(st["note"] or "")}</p>{traffic}'
            f'<p class="small muted">Automatic release is {"on" if release.auto() else "off (MODEL_AUTO_RELEASE=0)"}: shadow {release.SHADOW_DAYS:g} days, then '
            f'{", ".join(str(p) + "%" for p in release.STAGES)} of listings, {release.STAGE_DAYS:g} days each, each step only with at least '
            f'{release.FRESH_MIN} labels the candidate never saw showing it isn\'t worse. Rollback is always automatic.</p>'
            f'{f"<form method=post action=/admin/model/release class=row>{csrf}{btns}</form>" if btns else ""}'
            f'{f"<ul class=small>{lines}</ul>" if lines else ""}</div>')


@router.post("/admin/model/release")
def release_action(action: str = Form(""), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    import defense, release
    who = defense.reviewer_name(session)
    with store.db() as conn:
        st = release.state(conn)
        if action == "next" and st["stage"] == "shadow":
            release.start_rollout(conn, who=who or "a reviewer")
        elif action == "next" and st["stage"] == "rollout":
            nxt = [p for p in release.STAGES if p > int(st["pct"])]
            if not nxt or nxt[0] >= 100:
                release._promote(conn, st)
            else:
                release.start_rollout(conn, nxt[0], who=who or "a reviewer")
        elif action == "stop" and st["stage"] in ("shadow", "rollout"):
            release.rollback(conn, f"stopped by {who or 'a reviewer'}")
        elif action == "rollback":
            release.rollback(conn, f"restored by {who or 'a reviewer'}")
    return RedirectResponse("/admin/model", status_code=303)


@router.post("/admin/model/retrain")
def retrain_now(session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    threading.Thread(target=run_retrain, kwargs={"trigger": "reviewer", "force": True}, daemon=True).start()
    return RedirectResponse("/admin/model?started=1", status_code=303)
