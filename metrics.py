"""
What the detector gets wrong, measured, and the random sample that finds what it never sends to anyone.

Random low-risk sample: a small, random share of scam checks that come out "No known scam signs" or "Be careful" is kept
(without a name, emails and phone numbers masked; the contact details are kept only as keyed hashes) and goes to the
label queue as "Random check of a safe result". It stays unlabeled until a reviewer decides, so the detector never learns
from its own assumption that it was safe. Reviewed samples estimate how many confident misses get through.

Health numbers (/admin/intel): confirmed misses and false alarms, what the random sample found, reviewer workload,
time from the first report of a new technique to detection, and what the model served.
"""
from __future__ import annotations

import math
import os
import random
import time

import store

SAMPLE_RATE = float(os.environ.get("LOW_RISK_SAMPLE_RATE", "0.03"))
SAMPLE_DAILY_MAX = int(os.environ.get("LOW_RISK_SAMPLE_DAILY_MAX", "8"))
_rng = random.Random()


def maybe_sample(r: dict, *, kind: str, text: str, title: str = "", company: str = "", url: str = "", sender: str = "",
                 rng: random.Random | None = None) -> int | None:
    """Keep a random low-risk check for review. Returns the new check id, or None."""
    import defense
    import learning
    from export_labeled import mask
    if r.get("band") not in ("clear", "caution") or r.get("level", 0) >= 2 or SAMPLE_RATE <= 0:
        return None
    if (rng or _rng).random() >= SAMPLE_RATE:
        return None
    try:
        with store.db() as conn:
            if defense._stat(conn, "sampled", 1) >= SAMPLE_DAILY_MAX:
                return None
            cid = learning.add_submission(conn, body=mask(text)[:8000], sender=mask(sender)[:200], band=r["band"], kind=kind,
                                          title=title[:200], company=company[:200], url=url[:2000], source="sample")
            conn.execute("DELETE FROM check_indicators WHERE check_id = ?", (cid,))
            defense.index_check(conn, cid, "\n".join((title, company, text, sender, url)))   # hashes from the unmasked text
        defense.bump("sampled")
        return cid
    except Exception:                                       # noqa: BLE001 - sampling must never break a check
        import logging
        logging.getLogger("nolecareershield.metrics").exception("low-risk sample failed")
        return None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def health(conn, days: int = 90) -> dict:
    since = time.time() - days * 86400
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since))
    one = lambda q, p=(): conn.execute(q, p).fetchone()[0] or 0
    out: dict = {"days": days}
    out["missed_checks"] = one("SELECT COUNT(*) FROM submitted_checks WHERE review_label = 'scam' AND band IN ('clear','caution') "
                               "AND source != 'sample' AND reviewed_at > ?", (since,))
    out["missed_listings"] = one("SELECT COUNT(*) FROM jobs WHERE review_label = 'scam' AND scam_status = 'clear' AND reviewed_at > ?", (iso,))
    out["caught"] = (one("SELECT COUNT(*) FROM submitted_checks WHERE review_label = 'scam' AND band IN ('review','block') AND reviewed_at > ?", (since,))
                     + one("SELECT COUNT(*) FROM jobs WHERE review_label = 'scam' AND scam_status != 'clear' AND reviewed_at > ?", (iso,)))
    out["false_alarm_checks"] = one("SELECT COUNT(*) FROM submitted_checks WHERE review_label = 'legit' AND band IN ('review','block') AND reviewed_at > ?", (since,))
    out["false_alarm_listings"] = one("SELECT COUNT(*) FROM jobs WHERE review_label = 'legit' AND scam_status IN ('flagged','held') AND reviewed_at > ?", (iso,))
    out["legit_total"] = (one("SELECT COUNT(*) FROM submitted_checks WHERE review_label = 'legit' AND reviewed_at > ?", (since,))
                          + one("SELECT COUNT(*) FROM jobs WHERE review_label = 'legit' AND reviewed_at > ?", (iso,)))
    s_rev = one("SELECT COUNT(*) FROM submitted_checks WHERE source = 'sample' AND review_label IS NOT NULL AND created_at > ?", (since,))
    s_scam = one("SELECT COUNT(*) FROM submitted_checks WHERE source = 'sample' AND review_label = 'scam' AND created_at > ?", (since,))
    out["sample"] = {"taken": one("SELECT COUNT(*) FROM submitted_checks WHERE source = 'sample' AND created_at > ?", (since,)),
                     "reviewed": s_rev, "scams": s_scam, "interval": wilson(s_scam, s_rev)}
    week = time.time() - 7 * 86400
    out["workload"] = {"labels_7d": one("SELECT COUNT(*) FROM label_log WHERE at > ? AND label IS NOT NULL", (week,)),
                       "queue": one("SELECT COUNT(*) FROM submitted_checks WHERE review_label IS NULL"),
                       "median_hours_to_label": _median([r[0] for r in conn.execute(
                           "SELECT (reviewed_at - created_at) / 3600.0 FROM submitted_checks WHERE reviewed_at > ? AND review_label IS NOT NULL",
                           (since,))])}
    ttd = []
    for c in store.rows(conn, """SELECT c.id, c.decided_at, MIN(sc.created_at) AS first FROM cases c
                                 JOIN case_members m ON m.case_id = c.id JOIN submitted_checks sc ON sc.id = m.check_id
                                 WHERE c.status = 'resolved' AND c.decided_at > ? GROUP BY c.id""", (since,)):
        ttd.append((c["decided_at"] - c["first"]) / 86400)
    out["time_to_detection_days"] = {"cases": len(ttd), "median": _median(ttd), "worst": max(ttd) if ttd else None}
    out["model"] = {"decisions_7d": one("SELECT COUNT(*) FROM model_decisions WHERE at > ?", (week,)),
                    "flags_7d": one("SELECT SUM(flag) FROM model_decisions WHERE at > ?", (week,))}
    return out


def _median(xs: list) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def health_html(conn) -> str:
    from ui import esc
    h = health(conn)
    s, w, t, m = h["sample"], h["workload"], h["time_to_detection_days"], h["model"]
    missed = h["missed_checks"] + h["missed_listings"]
    fa = h["false_alarm_checks"] + h["false_alarm_listings"]
    lo, hi = s["interval"]
    samp = (f'{s["scams"]} scam{"s" if s["scams"] != 1 else ""} in {s["reviewed"]} reviewed (of {s["taken"]} taken). '
            f'Likely share of "safe" results that are scams: {lo:.0%} to {hi:.0%}.' if s["reviewed"] else
            f'{s["taken"]} taken, none reviewed yet. They\'re in the label queue as "Random check of a safe result".')
    fmt = lambda x, unit: "-" if x is None else f"{x:.1f} {unit}"
    rows = [
        ("Confirmed scams the detector missed", f"{missed} ({h['missed_checks']} sent-in checks, {h['missed_listings']} board listings); caught {h['caught']}"),
        ("False alarms (confirmed real, but flagged)", f"{fa} of {h['legit_total']} confirmed-real items"),
        ("Random sample of 'safe' results", samp),
        ("Reviewer workload", f"{w['labels_7d']} labels in the last 7 days; {w['queue']} waiting; median {fmt(w['median_hours_to_label'], 'hours')} from report to label"),
        ("First report to detection (resolved cases)", f"{t['cases']} cases; median {fmt(t['median'], 'days')}, slowest {fmt(t['worst'], 'days')}"),
        ("Model on real listing checks", f"{m['decisions_7d']} scored in the last 7 days, {int(m['flags_7d'] or 0)} sent for a second look"),
    ]
    return ('<table class="tbl">' + "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in rows) + "</table>"
            f'<p class="small muted">Last {h["days"]} days. Misses and false alarms count only what reviewers confirmed; the random sample is the '
            f'only estimate of misses nobody reported.</p>')
