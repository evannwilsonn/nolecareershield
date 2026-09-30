"""Build the interactive demo: one self-contained HTML file.

    python demo/build.py

It is assembled from the real site's pieces so it can't drift:
  * the stylesheet from ui.py (ui.CSS + ui.THEME_CSS, the midnight navy and gold theme) and its self-hosted fonts
  * the scam rules from scam_detector/rulepack/core.json
  * demo/engine.js, a port of the Python engines checked by tests/test_demo_engine.py
  * demo/app.js, the pages, driven by in-memory sample data

Writes demo/NoleCareerShield_Demo.html (body only, for hosting as a Claude artifact)
and demo/index.html (a complete page for any static host). Both embed the landing footage and photos
(about 6 MB), so they are build outputs and not kept in git.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENV", "development")

import css_assist  # noqa: E402
import ui  # noqa: E402
import css_feed  # noqa: E402,F401  (appends the feed styles to ui.CSS)
import css_msg  # noqa: E402,F401  (appends the interview and template styles to ui.CSS)
import css_employer  # noqa: E402,F401  (appends the employer dashboard styles to ui.CSS)
import css_events  # noqa: E402,F401  (appends the event styles to ui.CSS)
import css_hiring  # noqa: E402,F401  (appends the applicant table and listing-control styles to ui.CSS)
import css_team  # noqa: E402,F401  (appends the team page styles to ui.CSS)
import css_public  # noqa: E402,F401  (appends the sign-in vault and landing styles to ui.THEME_CSS)
import public_ui  # noqa: E402  (the sign-in vault and landing sections, shared with the site)

TITLE = "NoleCareerShield Demo"


DEMO_CSS = """
.demo{position:relative;z-index:30;background:linear-gradient(90deg,#050A14,#0C1729 50%,#050A14);color:#AEB9C9;border-bottom:1px solid var(--hair-2);font-size:12.5px;padding:8px 16px;display:flex;gap:8px 14px;justify-content:center;align-items:center;flex-wrap:wrap;text-align:center}
.demo::before{content:"Demo";font:500 10px/1 var(--mono);letter-spacing:.24em;text-transform:uppercase;color:#1B1406;background:var(--foil);padding:5px 8px;border-radius:5px}
.demo .lbl{max-width:70ch;color:#AEB9C9}
.demo .grp{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;align-items:center}
.demo .grp>span{font:500 10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold)}
.demo button{background:rgba(226,190,106,.06);color:var(--gold-2);border:1px solid var(--hair-2);border-radius:999px;padding:4px 12px;font:500 12px var(--sans);cursor:pointer}
.demo button:hover{background:rgba(226,190,106,.14);border-color:var(--gold)}
header{top:env(safe-area-inset-top,0px)}
@media(min-width:901px){.inapp .demo{margin-left:var(--side-w)}}
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
<span class="grp"><span>Explore as:</span><button type="button" data-do="as-student">Student</button><button type="button" data-do="as-employer">Employer</button><button type="button" data-do="as-reviewer">Reviewer</button></span>
<span class="grp"><button type="button" data-go="inbox" id="inboxBtn">Demo inbox</button><button type="button" data-do="reset">Reset demo</button></span></div>
<header><div class="nav"><a class="brand" href="#" data-go="home" aria-label="NoleCareerShield home">{emblem}{brandName}</a>
<div class="nav-actions" id="navActions"></div></div></header>
<div id="app"></div>
<script>var NCS_RULEPACK = {rules};
var NCS_SEED = {seed};
var NCS_BLOCKS = {blocks};
var NCS_FRAMES = {frames};
var NCS_MEDIA = {media};</script>
<script>{engine}</script>
<script>{app}</script>
<script>{fx}</script>
"""


def build() -> tuple[Path, Path]:
    rules = json.loads((ROOT / "scam_detector" / "rulepack" / "core.json").read_text())
    seed = json.loads((HERE / "seed_listings.json").read_text())
    for j in seed:                     # scores are computed live in the browser now
        for k in ("score", "scam_status", "findings"):
            j.pop(k, None)
    safe = lambda obj: json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")
    # The landing-page blocks are the site's own markup; links point at the demo's router instead.
    L = {"join": 'href="#" data-go="start"', "check": 'href="#" data-go="scam"', "check_msg": 'href="#" data-go="scam?kind=message"',
         "emp_signup": 'href="#" data-go="signup?role=employer"', "emp_login": 'href="#" data-go="login?role=employer"',
         "employers": 'href="#" data-go="employers"'}
    night, fair = ui.students_chapters(L)
    blocks = {"marquee": ui.marquee_block(),
              "scan": ui.scan_block('<a href="#" data-go="scam">Check one you found →</a>'),
              "howStudents": ui.how_students(), "howEmployers": ui.how_employers(),
              "cineHero": ui.cine_hero(L), "nightCh": night, "fairCh": fair,
              "empHero": ui.employer_hero(L), "empGets": ui.employer_gets(), "empCh": ui.employer_chapter(L),
              # the public pages in the elite look (public_ui.py): landing sections and the sign-in vault's brand column
              "proof": public_ui.proof(L), "checkTeaser": public_ui.check_teaser(L), "empCta": public_ui.employer_cta(L),
              "empVault": public_ui.employer_vault(L),
              "vaultStudent": public_ui.vault_aside("student"), "vaultEmployer": public_ui.vault_aside("employer")}
    blocks.update({"seal_" + k: public_ui.seal(k) for k in public_ui.SEALS})
    # Footage and photos are embedded too. The hero's frames go in NCS_FRAMES, which static/fx.js reads.
    media = ROOT / "static" / "media"
    uri = lambda name: "data:image/webp;base64," + base64.b64encode((media / name).read_bytes()).decode()
    blocks = {k: re.sub(r"/static/media/([a-z0-9-]+\.webp)\?v=\w+", lambda m: uri(m.group(1)), v) if "{n}" not in v
              else re.sub(r"/static/media/(?!arch-\{n\})([a-z0-9-]+\.webp)\?v=\w+", lambda m: uri(m.group(1)), v)
              for k, v in blocks.items()}
    frames = [uri(f"arch-{i:03d}.webp") for i in range(ui.CINE_FRAMES)]
    extra_media = {"office-960.webp": uri("office-960.webp")}      # the employer home's photo
    if "/static/media/" in "".join(v for v in blocks.values()).replace("/static/media/arch-{n}", ""):
        raise SystemExit("a media link in the landing blocks was not embedded")
    # The fonts are embedded, since the demo is one self-contained file: each @font-face src becomes a data: URL.
    css = ui.CSS + ui.THEME_CSS
    for f in ui.FONT_FILES:
        src = f"url(/static/fonts/{f})"
        if src not in css:
            raise SystemExit(f"@font-face for {f} not found in ui.CSS")
        data = base64.b64encode((ROOT / "static" / "fonts" / f).read_bytes()).decode()
        css = css.replace(src, f"url(data:font/woff2;base64,{data})")
    if "/static/fonts/" in css:
        raise SystemExit("a font link in ui.CSS was not embedded")
    body = SHELL
    for key, val in {"title": TITLE, "css": css + DEMO_CSS, "emblem": ui.crest(30, key="hdr"), "brandName": ui.BRAND_NAME, "rules": safe(rules), "seed": safe(seed),
                     "blocks": safe(blocks), "frames": safe(frames), "media": safe(extra_media), "engine": (HERE / "engine.js").read_text(), "app": (HERE / "app.js").read_text(),
                     "fx": (ROOT / "static" / "fx.js").read_text()}.items():
        body = body.replace("{" + key + "}", val)
    art = HERE / "NoleCareerShield_Demo.html"
    art.write_text(body)
    full = HERE / "index.html"
    full.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                    '<meta name="color-scheme" content="dark"><meta name="theme-color" content="#050A14">'
                    f'<link rel="icon" href="{ui.FAVICON}"></head><body style="margin:0">\n' + body + "</body></html>\n")
    return art, full


if __name__ == "__main__":
    a, f = build()
    print(f"wrote {a.relative_to(ROOT)} ({a.stat().st_size // 1024} KB) and {f.relative_to(ROOT)}")
