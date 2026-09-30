"""The home page's scroll scene: a fake job listing that the real detector takes apart.

The flags are not written by hand. `scan_model()` runs the sample through scam_detector and msgcheck.check_listing
and uses the titles and verdict they return, so the scene can't claim something the detector doesn't do.
tests/test_showcase.py fails if a rule stops firing on its step.

The same HTML is used by the site (app.landing) and the demo (demo/build.py embeds it), with three placeholders:
{JOIN} and {CHECK} are the link attributes for the two buttons and {COUNT} is the live-listings line.
"""
from __future__ import annotations

from functools import lru_cache

import msgcheck
from ui import esc

TITLE = "Remote Administrative Assistant"
COMPANY = "QuickCash Staffing"
META = "QuickCash Staffing · Remote · Part-time"
CONTACT = "quickcash.hiring@gmail.com"

# The listing in reading order. A number marks a phrase the detector flags, and which step flags it.
BODY = [
    ("Congratulations, ", 0), ("you've been selected, no interview needed", 1),
    ("! This part-time remote assistant role pays ", 0), ("$500 weekly", 2), (". ", 0),
    ("We'll mail you a check to buy equipment from our approved vendor.", 3), (" ", 0),
    ("Deposit it and send the balance by Zelle.", 4), (" ", 0),
    ("Text our hiring manager on WhatsApp", 5), (" to get started.", 0),
]
# step -> the rule that flags it (its title is what the scene shows)
STEP_RULES = {1: "instant_hire", 2: "weekly_stipend", 3: "fake_check_funds", 4: "irreversible_pay", 5: "off_platform", 6: "personal_email"}


def description() -> str:
    return "".join(t for t, _ in BODY)


def _norm(s: str) -> str:
    return s.lower().replace("’", "'")


@lru_cache(maxsize=1)
def scan_model() -> dict:
    """Run the sample through the real listing check. Each step keeps its rule only if that rule fired on the
    step's own phrase."""
    r = msgcheck.check_listing(TITLE, description(), COMPANY, contact=CONTACT)
    by_id = {f["rule_id"]: f for f in r["findings"]}
    phrases = {s: _norm(t) for t, s in BODY if s} | {6: _norm(CONTACT)}
    steps = []
    for s, rid in STEP_RULES.items():
        f = by_id.get(rid)
        if f and any(_norm(m) in phrases[s] for m in f["matched"]):
            steps.append({"n": s, "rule_id": rid, "title": f["title"], "severity": f["severity"]})
    return {"steps": steps, "score": r["score"], "signals": len(r["findings"]), "verdict": r["title"],
            "advice": r["steps"][0] if r["steps"] else r["advice"], "level": r["key"]}


@lru_cache(maxsize=1)
def scan_template() -> str:
    m = scan_model()
    fired = {s["n"] for s in m["steps"]}
    mark = lambda text, s: (f'<mark data-s="{s}">{esc(text)}<sup>{s}</sup></mark>' if s in fired else esc(text))
    body = "".join(mark(t, s) if s else esc(t) for t, s in BODY)
    flags = "".join(f'<li data-s="{s["n"]}" class="{s["severity"]}"><span class="k">{s["n"]}</span><b>{esc(s["title"])}</b>'
                    f'<span class="sev">{"Critical" if s["severity"] == "critical" else "Warning"}</span></li>' for s in m["steps"])
    last = len(STEP_RULES) + 1
    return f"""<section class="scan" data-scan style="--n:{last}" aria-labelledby="scan-h"><div class="scan-in">
<div class="scan-copy">
<div class="eyebrow">For FSU students · Scam-checked</div>
<h1 id="scan-h">Know it's real <em>before you apply.</em></h1>
<p>Every listing here is scanned for scam signals and approved by a person. <span class="live-only">Scroll to watch the detector take a fake one apart.</span><span class="static-only">Here's what it does to a fake one.</span></p>
<div class="cta"><a class="primary" {{JOIN}}>Join or log in with your @fsu.edu email</a><a class="secondary" {{CHECK}}>Try the scam check</a></div>
<div class="count">{{COUNT}}</div>
</div>
<div class="scan-track"><div class="scan-stage">
<article class="scan-card" aria-label="A sample scam listing, marked up by the detector">
<span class="scan-line" aria-hidden="true"></span>
<div class="scan-top"><div><div class="scan-title">{esc(TITLE)}</div><div class="scan-co">{esc(META)}</div></div><span class="scan-tag">Sample</span></div>
<p class="scan-body">{body}</p>
<p class="scan-apply">Apply: {mark(CONTACT, 6)}</p>
<div class="scan-stamp" data-s="{last}" aria-hidden="true">{esc(m["verdict"])}</div>
</article>
<ol class="scan-flags" aria-label="What the detector found">{flags}</ol>
<div class="scan-verdict" data-s="{last}"><b>{esc(m["verdict"])}</b><span class="meta">Scam risk {m["score"]}/100 from {m["signals"]} signals</span>
<p>{esc(m["advice"])} <a {{CHECK}}>Check one you found →</a></p></div>
</div></div>
</div></section>"""


def scan_section(join_attrs: str, check_attrs: str, count_line: str) -> str:
    return (scan_template().replace("{JOIN}", join_attrs).replace("{CHECK}", check_attrs)
            .replace("{COUNT}", esc(count_line)))
