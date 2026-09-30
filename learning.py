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
RETRAIN_MIN_NEW = int(os.environ.get("RETRAIN_MIN_NEW", "20"))
HOLDOUT_EVERY = 3                # about 1 in 3 new labels is held out
_lock = threading.Lock()


def learn_dir() -> Path:
    return Path(store.db_path()).resolve().parent / "learning"


def model_path() -> Path:
    return learn_dir() / "models" / "scam_model.json"


def configure() -> None:
    """Point the detector at the live model (called at startup)."""
    os.environ["SCAM_MODEL_PATH"] = str(model_path())


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
    for r in store.rows(conn, "SELECT * FROM jobs WHERE review_label IN ('scam','legit','lead_gen') ORDER BY id"):
        out.append({"id": f"live-j{r['id']}", "label": r["review_label"], "kind": "listing", "title": mask(r["title"]),
                    "company": mask(r["company"]), "description": mask(r["description"]), "url": r["apply_url"] or "",
                    "split": r["learn_split"], "context_flags": [],
                    "notes": f"board listing, reviewer label; detector band={r['band']} score={r['score']}"})
    for r in store.rows(conn, "SELECT * FROM submitted_checks WHERE review_label IN ('scam','legit','lead_gen') ORDER BY id"):
        desc = r["body"] if r["kind"] == "listing" else r["body"] + (f"\n{r['sender']}" if r["sender"] else "")
        out.append({"id": f"live-c{r['id']}", "label": r["review_label"], "kind": r["kind"], "title": mask(r["title"]),
                    "company": mask(r["company"]), "description": mask(desc), "url": r["url"] or "", "split": r["learn_split"],
                    "context_flags": [], "notes": f"sent in from the scam check ({r['source']}), reviewer label; "
                                                  f"student said {r['user_label'] or '-'}; detector band={r['band']}"})
    return out


# ---------- the monthly retrain ----------

def _since(conn, t: float) -> int:
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t))
    return (conn.execute("SELECT COUNT(*) FROM submitted_checks WHERE review_label IN ('scam','legit','lead_gen') AND reviewed_at > ?", (t,)).fetchone()[0]
            + conn.execute("SELECT COUNT(*) FROM jobs WHERE review_label IN ('scam','legit','lead_gen') AND reviewed_at > ?", (iso,)).fetchone()[0])


def due(conn) -> tuple[bool, str]:
    last = store.row(conn, "SELECT * FROM model_runs WHERE status IN ('shipped','refused') ORDER BY started_at DESC LIMIT 1")
    since = last["started_at"] if last else 0.0
    if last and time.time() - since < RETRAIN_DAYS * 86400:
        days = int((since + RETRAIN_DAYS * 86400 - time.time()) // 86400) + 1
        return False, f"next scheduled retrain in about {days} day{'s' if days != 1 else ''}"
    new = _since(conn, since)
    if new < RETRAIN_MIN_NEW:
        return False, f"waiting for labels: {new} new of the {RETRAIN_MIN_NEW} needed"
    return True, f"{new} new labels"


def run_retrain(trigger: str = "schedule", force: bool = False) -> dict:
    """Retrain once. Returns {"status": shipped | refused | skipped | busy | unavailable | error, ...}."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        with store.db() as conn:
            if not force:
                ok, why = due(conn)
                if not ok:
                    return {"status": "skipped", "why": why}
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
        train_f.write_text("".join(json.dumps(r) + "\n" for r in rows if r["split"] == "train"))
        held = [r for r in rows if r["split"] == "holdout"]
        hold_f.write_text("".join(json.dumps(r) + "\n" for r in held))
        argv = ["--extra", str(train_f), "--out", str(model_path()), "--current", str(ml.active_path()), "--report-dir", str(d / "models")]
        if held:
            argv[2:2] = ["--holdout-extra", str(hold_f)]
        try:
            train_model.main(argv)
        except Exception as e:                          # noqa: BLE001 - a failed retrain must never take the site down
            log.exception("retrain failed")
            return _finish(run_id, "error", report=f"Training failed: {type(e).__name__}: {e}")
        res = train_model.LAST_RESULT
        return _finish(run_id, "shipped" if res.get("written") else "refused", version=res.get("version"),
                       train_rows=res.get("rows", 0), report=res.get("report", ""))
    finally:
        _lock.release()


def _finish(run_id: int, status: str, version=None, train_rows: int = 0, report: str = "") -> dict:
    with store.db() as conn:
        conn.execute("UPDATE model_runs SET finished_at = ?, status = ?, version = ?, train_rows = ?, report = ? WHERE id = ?",
                     (time.time(), status, version, train_rows, report, run_id))
    log.info("model retrain %s: %s", run_id, status)
    return {"status": status, "version": version, "run": run_id}


def maybe_retrain() -> None:
    """Called by the site's maintenance loop. Retrains in the background when due, so startup never waits."""
    try:
        with store.db() as conn:
            ok, _ = due(conn)
    except Exception:                                   # noqa: BLE001
        log.exception("retrain check failed")
        return
    if ok:
        threading.Thread(target=run_retrain, kwargs={"trigger": "schedule"}, daemon=True).start()


# ---------- reviewer pages ----------

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
    cards = ""
    for k, rs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), -kv[1][0]["created_at"])):
        r = rs[0]
        says = {}
        for x in rs:
            if x["user_label"]:
                says[x["user_label"]] = says.get(x["user_label"], 0) + 1
        tags = "".join(f'<span class="pill {"bad" if lab == "scam" else "ok" if lab == "legit" else ""}">{n} say {esc(lab)}</span>' for lab, n in says.items())
        if any(x["source"] == "ai_novel" for x in rs):
            tags += '<span class="pill warn">AI flagged a pattern the rules missed</span>'
        wave = (f'<span class="pill bad">Wave: {len(rs)} near-copies</span>' if len(rs) > 1 else "")
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
                  f'<form class="rev-actions" method="post" action="/admin/checks/label">{csrf}<input type="hidden" name="group" value="{esc(str(k))}">{buttons}</form></div>')
    done = "".join(f'<li>{esc(time.strftime("%m-%d", time.gmtime(x["reviewed_at"] or x["created_at"])))} · '
                   f'<b>{esc(x["review_label"])}</b> · {esc((x["title"] or x["body"])[:80])}'
                   f'<form method="post" action="/admin/checks/undo" style="display:inline">{csrf}<input type="hidden" name="cid" value="{int(x["id"])}">'
                   f' <button class="linkbtn" type="submit">undo</button></form></li>' for x in recent)
    body = ('<p class="lead">Things people sent in from the scam check. Your label is what the model learns from; '
            'nothing a visitor says counts until you confirm it. Near-copies from the last 30 days are grouped into one wave.</p>'
            + (cards or '<div class="empty">Nothing waiting. Labels you confirm train the next model.</div>')
            + (f'<h3 class="sec">Recently labeled</h3><ul class="small">{done}</ul>' if done else ""))
    return admin_extra._page(body, "Label queue", "/admin/checks")


@router.post("/admin/checks/label")
def label_group(group: str = Form(""), label: str = Form(""), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if admin_extra._gate(session, csrf) and label in LABELS + ("skip",):
        with store.db() as conn:
            now = time.time()
            if group.startswith("i") and group[1:].isdigit():
                conn.execute("UPDATE submitted_checks SET review_label = ?, reviewed_at = ? WHERE id = ? AND review_label IS NULL",
                             (label, now, int(group[1:])))
            elif group.isdigit():
                conn.execute("UPDATE submitted_checks SET review_label = ?, reviewed_at = ? WHERE (campaign = ? OR id = ?) AND review_label IS NULL",
                             (label, now, int(group), int(group)))
    return RedirectResponse("/admin/checks", status_code=303)


@router.post("/admin/checks/undo")
def label_undo(cid: int = Form(0), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if admin_extra._gate(session, csrf):
        with store.db() as conn:
            conn.execute("UPDATE submitted_checks SET review_label = NULL, reviewed_at = NULL WHERE id = ?", (cid,))
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
    sched = (f'<p class="small muted">Automatic retrain: {"due now" if ok else esc(why)}. It runs at most every '
             f'{RETRAIN_DAYS:g} days, once {RETRAIN_MIN_NEW} new labels exist, and ships only if it beats the current model '
             f'on every frozen holdout with no new false alarm.</p>')
    button = (f'<form method="post" action="/admin/model/retrain">{csrf}<button class="b" type="submit">Retrain now</button> '
              '<span class="small muted">Same gate as the monthly run.</span></form>')
    rows = "".join(f'<details class="card" style="margin-top:8px"><summary><b>{esc(time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["started_at"])))}</b> · '
                   f'{esc(r["trigger"])} · <span class="pill {"ok" if r["status"] == "shipped" else "bad" if r["status"] == "error" else ""}">{esc(r["status"])}</span>'
                   f'{" · " + esc(r["version"]) if r["version"] else ""} · {int(r["train_rows"])} rows</summary>'
                   f'<pre style="white-space:pre-wrap;font-size:12px">{esc(r["report"])}</pre></details>' for r in runs)
    body = (cur + f'<div class="card" style="margin-top:12px;display:grid;gap:10px">{label_line}{sched}{button}</div>'
            + '<h3 class="sec">Training runs</h3>' + (rows or '<div class="empty">No runs yet.</div>'))
    return admin_extra._page(notice + body, "Model", "/admin/model")


@router.post("/admin/model/retrain")
def retrain_now(session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf):
        return RedirectResponse("/admin", status_code=303)
    threading.Thread(target=run_retrain, kwargs={"trigger": "reviewer", "force": True}, daemon=True).start()
    return RedirectResponse("/admin/model?started=1", status_code=303)
