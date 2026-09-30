"""Build the interactive demo: one self-contained HTML file.

    python demo/build.py

It is assembled from the real site's pieces so it can't drift:
  * the stylesheet from ui.py (the Kami x Notion x Bento design system)
  * the scam rules from scam_detector/rulepack/core.json
  * demo/engine.js, a port of the Python engines checked by tests/test_demo_engine.py
  * demo/app.js, the pages, driven by in-memory sample data

Writes demo/NoleCareerShield_Demo.html (body only, for hosting as a Claude artifact)
and demo/index.html (a complete page for any static host).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENV", "development")

import ui  # noqa: E402

TITLE = "NoleCareerShield Demo"


def themed_css(css: str) -> str:
    """ui.py switches to dark with prefers-color-scheme only. The demo also honours an explicit
    light/dark choice from the page that hosts it (data-theme on the root element)."""
    m = re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", css, re.S)
    if not m:
        raise SystemExit("dark-theme block not found in ui.CSS")
    tokens = m.group(1)
    dark = ('@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' + tokens + "}}\n"
            ':root[data-theme="dark"]{' + tokens + "}")
    return css[:m.start()] + dark + css[m.end():]


DEMO_CSS = """
.demo{background:var(--ink);color:var(--canvas);font-size:13px;padding:8px 16px;display:flex;gap:8px 12px;justify-content:center;align-items:center;flex-wrap:wrap;text-align:center}
.demo .lbl{opacity:.85;max-width:64ch}
.demo .grp{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;align-items:center}
.demo button{background:transparent;color:inherit;border:1px solid color-mix(in srgb,var(--canvas) 45%,transparent);border-radius:999px;padding:3px 11px;font:500 12px var(--sans);cursor:pointer}
.demo button:hover{background:color-mix(in srgb,var(--canvas) 14%,transparent)}
header{top:env(safe-area-inset-top,0px)}
.side{top:calc(57px + env(safe-area-inset-top,0px))}
body{background:var(--canvas)}
a[href="#"]{cursor:pointer}
.b,.chipf,.job,.side a,.seg a,.tabs a{cursor:pointer}
.bubble a{text-decoration:underline}
.verdict.ok .ic,.verdict.caution .ic,.verdict.warn .ic,.verdict.bad .ic{flex:none}
@media(max-width:620px){.demo .lbl{font-size:12px}}
"""

SHELL = """<title>{title}</title>
<style>{css}</style>
<div class="demo" id="demo" role="region" aria-label="Demo controls"><span class="lbl">Interactive demo with sample data. The scam checks, matches and resume scores run the real detector and rules in your browser; nothing is saved or sent. Students: log in with jordan@fsu.edu.</span>
<span class="grp"><span>Explore as:</span><button type="button" data-do="as-employer">Employer</button><button type="button" data-do="as-reviewer">Reviewer</button></span>
<span class="grp"><button type="button" data-go="inbox" id="inboxBtn">Demo inbox</button><button type="button" data-do="reset">Reset demo</button></span></div>
<header><div class="nav"><a class="brand" href="#" data-go="home" aria-label="NoleCareerShield home">{emblem}<span class="brand-name">Nole<b>CareerShield</b></span></a>
<div class="nav-actions" id="navActions"></div></div></header>
<div id="app"></div>
<script>var NCS_RULEPACK = {rules};
var NCS_SEED = {seed};</script>
<script>{engine}</script>
<script>{app}</script>
"""


def build() -> tuple[Path, Path]:
    rules = json.loads((ROOT / "scam_detector" / "rulepack" / "core.json").read_text())
    seed = json.loads((HERE / "seed_listings.json").read_text())
    for j in seed:                     # scores are computed live in the browser now
        for k in ("score", "scam_status", "findings"):
            j.pop(k, None)
    safe = lambda obj: json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")
    body = SHELL
    for key, val in {"title": TITLE, "css": themed_css(ui.CSS) + DEMO_CSS, "emblem": ui.EMBLEM, "rules": safe(rules), "seed": safe(seed),
                     "engine": (HERE / "engine.js").read_text(), "app": (HERE / "app.js").read_text()}.items():
        body = body.replace("{" + key + "}", val)
    art = HERE / "NoleCareerShield_Demo.html"
    art.write_text(body)
    full = HERE / "index.html"
    full.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                    '<meta name="color-scheme" content="light dark"></head><body style="margin:0">\n' + body + "</body></html>\n")
    return art, full


if __name__ == "__main__":
    a, f = build()
    print(f"wrote {a.relative_to(ROOT)} ({a.stat().st_size // 1024} KB) and {f.relative_to(ROOT)}")
