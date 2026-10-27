"""
Reference examples for the AI second opinion: the confirmed scams, and the confirmed real postings, closest to what a
student is checking.

Why: the AI knows scams in general; it doesn't know this month's scripts. Showing it the two or three confirmed scams
most like the message (and the closest real jobs, so it doesn't learn "similar topic = scam") lets it recognize a
rewritten version of a scheme reviewers already confirmed, the day after they confirmed it, with no retrain.

What it uses: reviewer-confirmed labels from this board (learning.labeled_rows, contact details masked) plus the labeled
training corpora in scam_detector/data (never the frozen holdouts). Similarity is TF-IDF cosine over the active model's
vocabulary, so it needs no extra model or service.

What it is not: a verdict. Offline it did not catch scams the model misses (a new scheme has no near neighbors), so it
never adds a finding of its own. It only gives the AI context, and the AI can still only raise caution.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path

import store
from scam_detector import ml

log = logging.getLogger("nolecareershield.similar")

DATA = Path(ml.__file__).resolve().parent / "data"
CORPORA = ["field_2026_09_tune.jsonl", "field_2026_10_tune.jsonl", "boards_2026_10_train.jsonl", "labeled_seed.jsonl",
           "real_corpus_clean.jsonl", "external_scams.jsonl"]        # labeled, real, never the frozen holdouts
MIN_SIM = 0.15
EXCERPT = 700
_lock = threading.Lock()
_cache: dict = {"sig": None, "items": []}


def _vec(text: str, vocab: dict) -> dict:
    counts: dict[str, int] = {}
    for t in ml.analyzer(text):
        if t in vocab:
            counts[t] = counts.get(t, 0) + 1
    v = {t: (1.0 + math.log(c)) * vocab[t][0] for t, c in counts.items()}
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / n for t, x in v.items()}


def _cos(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def _corpus_rows() -> list[dict]:
    out = []
    for f in CORPORA:
        p = DATA / f
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("label") in ("scam", "legit"):
                    out.append({"id": f"{f}:{r.get('id') or len(out)}", "label": r["label"], "title": r.get("title", ""),
                                "description": r.get("description", ""), "source": "labeled corpus"})
    return out


def _signature(conn, m: ml.Model) -> tuple:
    last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM label_log").fetchone()[0]
    return (m.version, last)


def index(conn, m: ml.Model | None = None) -> list[dict]:
    """Every confirmed scam and real posting, vectorized; rebuilt when a label changes or the model does."""
    import learning
    m = m or ml.load()
    if m is None:
        return []
    sig = _signature(conn, m)
    with _lock:
        if _cache["sig"] == sig:
            return _cache["items"]
        rows = [{"id": r["id"], "label": r["label"], "title": r["title"], "description": r["description"], "source": "confirmed by a reviewer"}
                for r in learning.labeled_rows(conn) if r["label"] in ("scam", "legit")] + _corpus_rows()
        items = []
        for r in rows:
            v = _vec(ml.posting_text(r["title"], r["description"]), m.vocab)
            if v:
                items.append({**r, "vec": v})
        _cache.update({"sig": sig, "items": items})
        return items


def nearest(text: str, conn=None, k: int = 3, label: str = "scam", min_sim: float = MIN_SIM) -> list[dict]:
    m = ml.load()
    if m is None:
        return []
    if conn is None:
        with store.db() as c:
            items = index(c, m)
    else:
        items = index(conn, m)
    q = _vec(text, m.vocab)
    if not q:
        return []
    scored = sorted(((round(_cos(q, it["vec"]), 3), it) for it in items if it["label"] == label), key=lambda x: -x[0])
    return [{"similarity": s, "id": it["id"], "title": it["title"], "excerpt": it["description"][:EXCERPT], "source": it["source"]}
            for s, it in scored[:k] if s >= min_sim]


def context(text: str) -> tuple[str, dict]:
    """The reference block for the AI prompt, and a short summary of what was shown. Empty when nothing is close. Never raises."""
    import ai
    try:
        scams, real = nearest(text, k=3, label="scam"), nearest(text, k=2, label="legit")
    except Exception:                                   # noqa: BLE001
        log.exception("similar-scam lookup failed")
        return "", {}
    if not scams:
        return "", {}
    parts = [ai.tag("confirmed_scam", f"(similarity {s['similarity']:.2f}, {s['source']})\n{s['title']}\n{s['excerpt']}", 1200) for s in scams]
    parts += [ai.tag("confirmed_real_job", f"(similarity {s['similarity']:.2f}, {s['source']})\n{s['title']}\n{s['excerpt']}", 1200) for s in real]
    return "\n".join(parts), {"scams": [s["id"] for s in scams], "real": [s["id"] for s in real], "top": scams[0]["similarity"]}
