"""
Investigation cases: every drift alert on /admin/intel becomes a case a reviewer can work through.

A case gathers, automatically:
- representative examples (the reports behind the alert),
- the contact details they share,
- what the detector said about each (band, rules that fired, the model's probability),
- how many distinct reports support it (near-copies of one template count once),
- a proposed detection change: phrases common to the case's reports that no rule covers yet, with every legitimate
  item the phrase would also hit (so the reviewer sees the cost before promoting anything).

Nothing in a case changes the detector. A reviewer confirms it (a real new technique), dismisses it (with a reason), or
marks it resolved (with what was changed). A confirmed case counts as a confirmed new campaign for retraining
(learning.py), and the proposal downloads as an inert rulepack fragment for tools/regress.py.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Cookie, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import admin_extra
import defense
import store
from ui import esc

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
    title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL,
    updated_at REAL NOT NULL, summary TEXT NOT NULL DEFAULT '{}', reviewer TEXT NOT NULL DEFAULT '', decision_note TEXT NOT NULL DEFAULT '',
    decided_at REAL);
CREATE TABLE IF NOT EXISTS case_members (case_id INTEGER NOT NULL, check_id INTEGER NOT NULL, PRIMARY KEY (case_id, check_id));
"""
STATUSES = ("open", "confirmed", "dismissed", "resolved")
KIND_NAMES = {"missed": "Confirmed scams the rules missed", "wave": "Wave the rules call safe", "spike": "Rising count",
              "ct": "Look-alike domain", "uncertain": "Model unsure more often"}


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _week(t: float | None = None) -> str:
    return time.strftime("%G-W%V", time.gmtime(t or time.time()))


def _members_for(conn, alert: dict) -> list[int]:
    if alert.get("ids"):
        return [int(i) for i in alert["ids"]]
    if alert.get("wave"):
        return [r[0] for r in conn.execute("SELECT id FROM submitted_checks WHERE campaign = ? OR id = ? ORDER BY id",
                                           (alert["wave"], alert["wave"]))]
    if alert.get("metric") == "ai_only_scam":
        return [r[0] for r in conn.execute("SELECT id FROM submitted_checks WHERE source = 'ai_novel' AND created_at > ? ORDER BY id DESC LIMIT 40",
                                           (time.time() - 7 * 86400,))]
    return []


def case_key(alert: dict) -> str | None:
    kind = alert.get("kind")
    if kind == "missed":
        return f"missed:{_week()}"
    if kind == "wave":
        return f"wave:{alert['wave']}"
    if kind == "spike":
        return f"spike:{alert['metric']}:{_week()}"
    if kind == "ct":
        return f"ct:{alert['domain']}"
    if kind == "uncertain":
        return f"uncertain:{_week()}"
    return None


def sync(conn) -> list[int]:
    """Open a case for every current alert that doesn't have one; add new reports to cases still open. Returns case ids."""
    ensure_schema(conn)
    ids = []
    now = time.time()
    for a in defense.alerts(conn):
        key = case_key(a)
        if not key:
            continue
        row = conn.execute("SELECT id, status FROM cases WHERE key = ?", (key,)).fetchone()
        if row is None:
            cur = conn.execute("INSERT INTO cases (key, kind, title, detail, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                               (key, a["kind"], a["title"][:200], a.get("detail", "")[:600], now, now))
            cid, status = cur.lastrowid, "open"
        else:
            cid, status = row
        if status == "open":
            for m in _members_for(conn, a):
                conn.execute("INSERT OR IGNORE INTO case_members (case_id, check_id) VALUES (?,?)", (cid, m))
            conn.execute("UPDATE cases SET title = ?, detail = ?, updated_at = ? WHERE id = ?", (a["title"][:200], a.get("detail", "")[:600], now, cid))
            conn.execute("UPDATE cases SET summary = ? WHERE id = ?", (json.dumps(build_summary(conn, cid, a)), cid))
        ids.append(cid)
    return ids


# ---------- what goes in a case ----------

def _legit_texts(conn) -> list[tuple[str, str]]:
    """(where, text) for everything known to be legitimate: confirmed-real reports, approved listings, labeled legit data."""
    out = [(f"report #{r['id']}", f"{r['title']}\n{r['body']}") for r in
           store.rows(conn, "SELECT id, title, body FROM submitted_checks WHERE review_label = 'legit' ORDER BY id DESC LIMIT 1500")]
    out += [(f"listing #{r['id']} ({r['company']})", f"{r['title']}\n{r['description']}") for r in
            store.rows(conn, "SELECT id, title, company, description FROM jobs WHERE review_label = 'legit' OR review_status = 'approved' ORDER BY id DESC LIMIT 1500")]
    data = Path(__file__).resolve().parent / "scam_detector" / "data"
    for f in sorted(data.glob("*.jsonl")):
        if f.name.startswith("redteam"):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("label") == "legit":
                out.append((f"{f.name}:{r.get('id', i + 1)}", f"{r.get('title', '')}\n{r.get('description', '')}"))
    return out


def propose(texts: list[str], legit: list[tuple[str, str]], max_phrases: int = 6) -> list[dict]:
    """Phrases in at least half of the case's reports (and at least two) that no current rule matches, ranked by support and
    then by how few legitimate items they'd also hit. Each comes with that collateral."""
    from scam_detector import rules as rules_mod
    from scam_detector.tools.mine_candidates import ngrams
    if len(texts) < 2:
        return []
    support: dict[str, int] = {}
    for t in texts:
        for g in set(ngrams(t)):
            support[g] = support.get(g, 0) + 1
    need = max(2, (len(texts) + 1) // 2)
    cands = [g for g, n in support.items() if n >= need and not any(rx.search(g) for r in rules_mod.RULES for rx in r.patterns)]
    cands = [g for g in cands if not any(g != h and g in h and support[h] == support[g] for h in cands)]
    legit_norm = [(w, " ".join(re.findall(r"[a-z0-9$%'\-]+", rules_mod.normalize(t).lower()))) for w, t in legit]
    out = []
    for g in sorted(cands, key=lambda g: (-support[g], -len(g)))[:40]:
        hits = [w for w, t in legit_norm if f" {g} " in f" {t} "]
        out.append({"phrase": g, "support": support[g], "of": len(texts), "legit_hits": len(hits), "legit_examples": hits[:5]})
    out.sort(key=lambda p: (p["legit_hits"] > 0, -p["support"], p["legit_hits"]))
    return out[:max_phrases]


def build_summary(conn, cid: int, alert: dict | None = None) -> dict:
    from scam_detector import ml
    from scam_detector.scorer import score_posting
    members = store.rows(conn, """SELECT sc.* FROM case_members m JOIN submitted_checks sc ON sc.id = m.check_id
                                  WHERE m.case_id = ? ORDER BY sc.id""", (cid,))
    distinct = {r["campaign"] or r["id"] for r in members}
    model = ml.load()
    seen = []
    for r in members[:40]:
        res = score_posting(r["title"], r["body"] + ("\n" + r["sender"] if r["sender"] else ""), r["company"], run_network=False)
        p = model.predict(r["title"], r["body"], r["company"], r["url"], res.findings, res.score)["probability"] if model else None
        seen.append({"id": r["id"], "band": res.band, "score": res.score, "rules": [f["rule_id"] for f in res.findings][:6],
                     "model": p, "label": r["review_label"], "wave": r["campaign"] or r["id"]})
    missed = [s for s in seen if s["band"] in ("clear", "caution") and not (s["model"] is not None and model and s["model"] >= model.threshold)]
    reps, used = [], set()
    for r in members:
        w = r["campaign"] or r["id"]
        if w in used:
            continue
        used.add(w)
        reps.append({"id": r["id"], "text": (r["title"] + "\n" if r["title"] else "") + r["body"][:600], "label": r["review_label"]})
        if len(reps) == 3:
            break
    ids = [r["id"] for r in members]
    shared = []
    if ids:
        marks = ",".join("?" * len(ids))
        shared = [dict(r) for r in store.rows(conn, f"""SELECT kind, shown, hash, COUNT(DISTINCT check_id) AS n FROM check_indicators
                                                       WHERE check_id IN ({marks}) GROUP BY hash HAVING n >= 2 ORDER BY n DESC LIMIT 10""", tuple(ids))]
    by_wave: dict = {}                                  # one text per wave, so a template sent 30 times counts once
    for r in members:
        by_wave.setdefault(r["campaign"] or r["id"], f"{r['title']}\n{r['body']}")
    texts = list(by_wave.values())
    labels: dict = {}
    for r in members:
        labels[r["review_label"] or "unlabeled"] = labels.get(r["review_label"] or "unlabeled", 0) + 1
    return {"reports": len(members), "distinct": len(distinct), "labels": labels, "examples": reps, "shared": shared,
            "detector": seen, "missed": len(missed), "proposal": propose(texts, _legit_texts(conn)) if texts else [],
            "domain": (alert or {}).get("domain"), "built_at": time.time()}


def proposal_fragment(case: dict, summary: dict) -> dict:
    """An inert rulepack fragment (status proposed, unreviewed) for tools/regress.py, from the phrases with no legit collateral."""
    phrases = [p["phrase"] for p in summary.get("proposal", []) if p["legit_hits"] == 0][:8]
    if not phrases:
        return {"version": "proposed", "rules": []}
    return {"version": "proposed", "rules": [{
        "id": f"case_{case['id']:03d}", "status": "proposed", "reviewed": False, "severity": "warning", "weight": 20,
        "title": "Technique from investigation case #%d (edit before promoting)" % case["id"],
        "why": f"Seen in {summary['distinct']} distinct reports in case #{case['id']} and in no known legitimate item.",
        "phrases": phrases, "patterns": [], "guards": ["negation"], "min_matches": 1, "bonus": 3,
        "added": "case", "source": f"case {case['id']}"}]}


# ---------- pages ----------

def _pill(status: str) -> str:
    return f'<span class="pill {"bad" if status == "open" else "ok" if status == "resolved" else "warn" if status == "confirmed" else ""}">{esc(status)}</span>'


@router.get("/admin/cases", response_class=HTMLResponse)
def cases_page(session: str | None = Cookie(default=None), show: str = "open"):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    with store.db() as conn:
        sync(conn)
        where = "status = 'open'" if show == "open" else "1=1"
        rows = store.rows(conn, f"SELECT * FROM cases WHERE {where} ORDER BY status = 'open' DESC, updated_at DESC LIMIT 100")
    items = ""
    for c in rows:
        s = json.loads(c["summary"] or "{}")
        items += (f'<li><a href="/admin/cases/{c["id"]}"><b>#{c["id"]} {esc(c["title"])}</b></a> {_pill(c["status"])}'
                  f'<span class="ev">{esc(KIND_NAMES.get(c["kind"], c["kind"]))} · {s.get("distinct", 0)} distinct report{"s" if s.get("distinct", 0) != 1 else ""}'
                  f' · {s.get("missed", 0)} the detector misses today · opened {time.strftime("%b %d", time.gmtime(c["created_at"]))}</span></li>')
    tog = ('<a href="/admin/cases?show=all">Show closed cases too</a>' if show == "open" else '<a href="/admin/cases">Open cases only</a>')
    body = (f'<p class="lead">Each alert opens a case with the evidence gathered for you. Confirm it if it\'s a real new technique, '
            f'dismiss it with a reason, or resolve it once a rule or label fixed it. Nothing here changes the detector by itself.</p>'
            f'<p class="small">{tog}</p><ul class="reasons card">{items or "<li class=muted>No cases.</li>"}</ul>')
    return admin_extra._page(body, "Cases", "/admin/cases")


@router.get("/admin/cases/{cid}", response_class=HTMLResponse)
def case_page(cid: int, session: str | None = Cookie(default=None)):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    csrf = admin_extra._csrf(session)
    with store.db() as conn:
        ensure_schema(conn)
        c = store.row(conn, "SELECT * FROM cases WHERE id = ?", (cid,))
        if not c:
            return RedirectResponse("/admin/cases", status_code=303)
        if c["status"] == "open":
            conn.execute("UPDATE cases SET summary = ? WHERE id = ?", (json.dumps(build_summary(conn, cid)), cid))
            c = store.row(conn, "SELECT * FROM cases WHERE id = ?", (cid,))
    s = json.loads(c["summary"] or "{}")
    ex = "".join(f'<li><span class="pill">{"report #" + str(e["id"])}{" · " + esc(e["label"]) if e["label"] else ""}</span>'
                 f'<span class="ev" style="white-space:pre-wrap">{esc(e["text"])}</span></li>' for e in s.get("examples", []))
    sh = "".join(f'<li>{esc(x["kind"])} <code>{esc(x["shown"])}</code> in {x["n"]} reports</li>' for x in s.get("shared", []))
    det = "".join(f'<tr><td>#{d["id"]}</td><td>{esc(d["band"])} ({d["score"]})</td><td>{"-" if d["model"] is None else format(d["model"], ".2f")}</td>'
                  f'<td class="small">{esc(", ".join(d["rules"]) or "none")}</td><td>{esc(d["label"] or "unlabeled")}</td></tr>' for d in s.get("detector", [])[:20])
    prop = "".join(f'<tr><td><code>{esc(p["phrase"])}</code></td><td>{p["support"]}/{p["of"]}</td>'
                   f'<td>{"none" if not p["legit_hits"] else str(p["legit_hits"]) + ": " + esc(", ".join(p["legit_examples"]))}</td></tr>'
                   for p in s.get("proposal", []))
    labels = ", ".join(f"{n} {esc(k)}" for k, n in s.get("labels", {}).items())
    decided = (f'<p class="small">Decided {time.strftime("%Y-%m-%d", time.gmtime(c["decided_at"]))}{" by " + esc(c["reviewer"]) if c["reviewer"] else ""}: '
               f'{esc(c["decision_note"])}</p>' if c["decided_at"] else "")
    unl = s.get("labels", {}).get("unlabeled", 0)
    actions = f"""<form method="post" action="/admin/cases/{cid}/decide" class="card">{csrf}
<div class="form-field"><label>Note (required to dismiss or resolve)</label><input name="note" maxlength="400" placeholder="e.g. new 'mystery shopper' script; added rule case_{cid:03d}"></div>
<div class="row"><button class="b sm" name="status" value="confirmed">Confirm: a real new technique</button>
<button class="b sm sec" name="status" value="resolved">Resolved</button><button class="b sm ghost" name="status" value="dismissed">Dismiss</button>
{'<button class="b sm ghost" name="status" value="open">Reopen</button>' if c["status"] != "open" else ""}</div></form>
{f'<form method="post" action="/admin/cases/{cid}/label" class="row">{csrf}<button class="b sm" name="label" value="scam">Label the {unl} unlabeled reports scam</button><button class="b sm ghost" name="label" value="legit">…or real</button><span class="small muted">Recorded with your name and "case #{cid}".</span></form>' if unl else ""}"""
    body = f"""<p><a href="/admin/cases">← All cases</a></p>
<section class="card"><h2>#{cid} {esc(c["title"])} {_pill(c["status"])}</h2><p class="small muted">{esc(KIND_NAMES.get(c["kind"], c["kind"]))} · {esc(c["detail"])}</p>{decided}
<p><b>{s.get("reports", 0)}</b> reports, <b>{s.get("distinct", 0)}</b> distinct after grouping near-copies ({labels or "none labeled"}).
The detector as it is today misses <b>{s.get("missed", 0)}</b> of them.</p></section>
<section class="card"><h2>Representative examples</h2><ul class="reasons">{ex or "<li class=muted>No reports attached to this alert.</li>"}</ul></section>
<section class="card"><h2>Shared contact details</h2><ul class="small">{sh or "<li class=muted>None shared by two or more reports.</li>"}</ul></section>
<section class="card"><h2>What the detector says about each</h2>{f'<table class="tbl"><tr><th>Report</th><th>Rules band</th><th>Model</th><th>Rules that fired</th><th>Label</th></tr>{det}</table>' if det else '<p class="muted">Nothing to score.</p>'}</section>
<section class="card"><h2>Proposed detection change</h2><p class="small muted">Phrases common to this case that no rule covers. The last column is every
legitimate item (confirmed-real reports, approved listings, labeled data) the phrase would also hit. Only collateral-free phrases go into the
download, as an inert proposed rule for <code>python -m scam_detector.tools.regress --candidate</code>.</p>
{f'<table class="tbl"><tr><th>Phrase</th><th>In reports</th><th>Would also hit (legit)</th></tr>{prop}</table><p><a class="b sm ghost" href="/admin/cases/{cid}/proposal.json">Download proposed rule</a></p>' if prop else '<p class="muted">No phrase is common enough yet. Contact-detail memory already covers the shared details above once they are confirmed.</p>'}</section>
{actions}"""
    return admin_extra._page(body, f"Case #{cid}", "/admin/cases")


@router.get("/admin/cases/{cid}/proposal.json")
def case_proposal(cid: int, session: str | None = Cookie(default=None)):
    if not admin_extra._ok(session):
        return RedirectResponse("/admin", status_code=303)
    with store.db() as conn:
        c = store.row(conn, "SELECT * FROM cases WHERE id = ?", (cid,))
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(proposal_fragment(c, json.loads(c["summary"] or "{}")),
                        headers={"Content-Disposition": f'attachment; filename="case_{cid:03d}_proposed.json"'})


@router.post("/admin/cases/{cid}/decide")
def case_decide(cid: int, status: str = Form(""), note: str = Form(""), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf) or status not in STATUSES:
        return RedirectResponse("/admin", status_code=303)
    note = note.strip()[:400]
    if status in ("dismissed", "resolved") and not note:
        return RedirectResponse(f"/admin/cases/{cid}?need_note=1", status_code=303)
    with store.db() as conn:
        if status == "open":
            conn.execute("UPDATE cases SET status = 'open', decided_at = NULL, updated_at = ? WHERE id = ?", (time.time(), cid))
        else:
            conn.execute("UPDATE cases SET status = ?, decision_note = ?, reviewer = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                         (status, note, defense.reviewer_name(session), time.time(), time.time(), cid))
    return RedirectResponse(f"/admin/cases/{cid}", status_code=303)


@router.post("/admin/cases/{cid}/label")
def case_label(cid: int, label: str = Form(""), session: str | None = Cookie(default=None), csrf: str = Form("")):
    if not admin_extra._gate(session, csrf) or label not in ("scam", "legit"):
        return RedirectResponse("/admin", status_code=303)
    who = defense.reviewer_name(session)
    with store.db() as conn:
        ids = [r[0] for r in conn.execute("""SELECT sc.id FROM case_members m JOIN submitted_checks sc ON sc.id = m.check_id
                                             WHERE m.case_id = ? AND sc.review_label IS NULL""", (cid,))]
        for i in ids:
            conn.execute("UPDATE submitted_checks SET review_label = ?, reviewed_at = ?, reviewer = ?, review_reason = ? WHERE id = ?",
                         (label, time.time(), who, f"case #{cid}", i))
            defense.log_label(conn, "check", i, label, who, f"case #{cid}")
        defense.recheck(conn, defense.hashes_of(conn, "check", ids))
    return RedirectResponse(f"/admin/cases/{cid}", status_code=303)


def confirmed_since(conn, since: float) -> list[dict]:
    """Cases a reviewer confirmed as a real new technique since `since` (learning.py treats these as new campaigns)."""
    ensure_schema(conn)
    return store.rows(conn, "SELECT * FROM cases WHERE status IN ('confirmed','resolved') AND decided_at > ?", (since,))
