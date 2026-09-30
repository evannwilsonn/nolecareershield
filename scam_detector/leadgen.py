"""
Lead-generation axis.

A lead-gen listing (an aggregator that wraps a real job in a signup wall, affiliate
redirects, or an unnamed employer) is NOT fraud, and telling a student "treat this
as a scam" would be wrong and would teach them to ignore the warning. It is a
different problem with a different remedy: find the employer's own posting.

So this is scored on its own axis with its own verdict. It never moves the fraud
band. The tell usually lives in the URL and the apply flow, not the words, which is
why most of the signal here is structural (url_flow.py) or user-observed
(context flags).

Weights are judgment calibrated on four real examples. That is far too few to claim
a measured accuracy; treat this axis as a transparent heuristic until the review
queue has produced more labeled cases.
"""

from __future__ import annotations

import re
from typing import Iterable, List

from .rules import Finding, normalize

FLAG_POINTS = {
    "signup_wall_reported":       (4, "Forced account signup before you can see the listing"),
    "apply_leaves_platform":      (3, "Apply sends you to a different site or off the platform"),
    "cross_posted_multiple_names": (3, "The same listing appears under several company names"),
    "heavy_email_after_apply":    (3, "Heavy email volume after applying"),
    "employer_unnamed":           (4, "The hiring company is never named"),
    "no_company_page":            (2, "The named employer has no real company page"),
}

URL_POINTS = {
    "url_signup_wall":     (4, "The apply link forces an account signup"),
    "url_paid_click":      (4, "The apply link is paid-per-click traffic"),
    "url_tracking_params": (2, "The apply link carries campaign tracking parameters"),
    "url_redirect_hop":    (2, "The apply link passes through a redirect hop"),
    "url_domain_mismatch": (3, "The apply link doesn't lead to the named employer"),
}

TEXT_PATTERNS = [
    (re.compile(r"\b(?:we are|is|are)\s+not\s+the\s+employer(?:\s+of\s+record)?\b|\baggregat(?:or|ed)\b|\bcross-?posted\b", re.I),
     3, "The listing describes itself as an aggregator"),
    (re.compile(r"\ba\s+(?:remote\s+|growing\s+|leading\s+)?(?:company|firm|organization|business)\s+(?:is\s+)?(?:seeking|looking|hiring)\b|\bour\s+client\b|\b(?:confidential|undisclosed)\s+(?:employer|company|client)\b", re.I),
     2, "The employer is described but not named"),
    (re.compile(r"\bregardless\s+of\s+(?:your\s+)?experience\b", re.I),
     1, "Generic 'regardless of experience' boilerplate"),
]

FLAG_THRESHOLD = 6
LIKELY_THRESHOLD = 8

VERDICT = ("This looks like an aggregator or lead-generation listing: the link goes through a middleman, "
           "not the employer. It may collect your email and profile. Find the employer's own posting "
           "before you apply.")


def assess_lead_gen(text: str, url_findings: Iterable[Finding], context_flags: Iterable[str]) -> dict:
    points = 0
    reasons: List[dict] = []
    seen_kinds = set()

    for f in url_findings:
        spec = URL_POINTS.get(f.rule_id)
        if spec:
            points += spec[0]
            seen_kinds.add("url")
            reasons.append({"source": "link", "points": spec[0], "reason": spec[1], "matched": f.matched[:2]})

    for flag in context_flags or []:
        spec = FLAG_POINTS.get(flag)
        if spec:
            points += spec[0]
            seen_kinds.add("observed")
            reasons.append({"source": "you reported", "points": spec[0], "reason": spec[1], "matched": []})

    norm = normalize(text)
    for rx, pts, reason in TEXT_PATTERNS:
        m = rx.search(norm)
        if m:
            points += pts
            seen_kinds.add("text")
            reasons.append({"source": "text", "points": pts, "reason": reason, "matched": [m.group(0)[:80]]})

    flag = points >= FLAG_THRESHOLD
    level = "likely" if points >= LIKELY_THRESHOLD else ("possible" if flag else None)
    return {"flag": flag, "level": level, "points": points, "reasons": reasons,
            "verdict": VERDICT if flag else ""}
