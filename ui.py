"""
The look of NoleCareerShield, in one place.

Design system: a mix of three Open Design systems (github.com/nexu-io/open-design):
  * Kami   - warm parchment canvas, ivory cards, serif headings at one weight (500),
             a single accent colour used sparingly, numbered section heads, no gradients.
  * Notion - warm-neutral greys, whisper borders (1px, ~10% ink), soft multi-layer shadows,
             pill badges, and the quiet left sidebar for the signed-in app.
  * Bento  - the signed-in home is a modular grid of tiles.
The single accent is garnet; gold appears only as a small highlight. One self-hosted font (Archivo,
static/fonts), no third-party requests, light and dark themes from the same tokens. The public landing
pages are cinematic: full-bleed footage and photography (static/media) with big condensed type.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
from pathlib import Path

import security
from security import make_csrf

_viewer: contextvars.ContextVar = contextvars.ContextVar("viewer", default=None)


def esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


EMBLEM = """<svg viewBox="0 0 40 40" width="30" height="30" aria-hidden="true">
<path d="M20 3 L34 8 V19 C34 28 28 34 20 37 C12 34 6 28 6 19 V8 Z" fill="var(--accent)"/>
<path d="M20 11 L22.4 17.6 L29 20 L22.4 22.4 L20 29 L17.6 22.4 L11 20 L17.6 17.6 Z" fill="var(--gold)"/>
</svg>"""

# Small stroke icons (24px grid), drawn for this site.
_ICON_PATHS = {
    "home": '<path d="M4 11 12 4l8 7"/><path d="M6 10v9h12v-9"/>',
    "jobs": '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5.5v2"/><path d="M3.5 12.5h17"/>',
    "feed": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 12.5h8M8 16h5"/>',
    "chat": '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z"/>',
    "spark": '<path d="M12 3.5 13.8 10.2 20.5 12 13.8 13.8 12 20.5 10.2 13.8 3.5 12 10.2 10.2Z"/>',
    "file": '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4"/><path d="M9.5 12h6M9.5 15.5h6"/>',
    "shield": '<path d="M12 3.5 19 6v6c0 4.5-3 7.5-7 8.5-4-1-7-4-7-8.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "user": '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1-3.6 3.8-5.5 7-5.5s6 1.9 7 5.5"/>',
    "people": '<circle cx="9" cy="9" r="3"/><path d="M3.5 19c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5"/><circle cx="16.5" cy="8" r="2.5"/><path d="M15.5 13.6c2.4-.3 4.4 1.1 5 3.9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "flag": '<path d="M6 21V4"/><path d="M6 4h11l-2 4 2 4H6"/>',
    "send": '<path d="M4 12 20 4l-5 16-3-7z"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "out": '<path d="M14 4h5v16h-5"/><path d="M10 8l-4 4 4 4M6 12h9"/>',
}


def icon(name: str, size: int = 18) -> str:
    return (f'<svg class="ic" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICON_PATHS.get(name, "")}</svg>')


CSS = """
@font-face{font-family:"Archivo";font-style:normal;font-display:swap;font-weight:100 900;font-stretch:62% 125%;src:url(/static/fonts/archivo.woff2) format("woff2-variations"),url(/static/fonts/archivo.woff2) format("woff2")}
:root{
--canvas:#f5f4ed;--surface:#faf9f5;--sunk:#efede4;--sand:#e8e6dc;--line:#e3e0d5;--line-2:#d9d5c8;--whisper:rgba(20,20,19,.10);
--ink:#141413;--ink-2:#3d3d3a;--muted:#5c5a54;--faint:#77756d;
--accent:#782F40;--accent-hover:#5E2432;--accent-ink:#782F40;--accent-tint:#f3e8e8;--on-accent:#faf9f5;
--gold:#CEB888;--gold-tint:#f4eedd;--gold-ink:#6e5a2c;
--ok:#2f6b4c;--ok-tint:#e5efe7;--warn:#8c560f;--warn-tint:#f5ead6;--bad:#9e3527;--bad-tint:#f5e2dd;--info:#2d4a6b;--info-tint:#e6ecf2;
--shadow:0 4px 18px rgba(20,20,19,.04),0 2px 8px rgba(20,20,19,.027),0 .8px 3px rgba(20,20,19,.02);
--shadow-deep:0 1px 3px rgba(20,20,19,.02),0 7px 15px rgba(20,20,19,.03),0 23px 52px rgba(20,20,19,.06);
--display:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--serif:var(--display);
--sans:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--stage:#1a1315;--stage-2:#241a1d;--on-stage:#f3eee6;--on-stage-2:#b9aea9;--ease:cubic-bezier(.16,1,.3,1);
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
--canvas:#161614;--surface:#1e1e1c;--sunk:#141412;--sand:#2a2926;--line:#302f2b;--line-2:#3b3a35;--whisper:rgba(240,238,230,.10);
--ink:#efede5;--ink-2:#d6d3c9;--muted:#aeaa9f;--faint:#8e8b81;
--accent:#9a4458;--accent-hover:#b04f66;--accent-ink:#e3a3b2;--accent-tint:#35222a;--on-accent:#fbf7f3;
--gold:#CEB888;--gold-tint:#302a1c;--gold-ink:#dcc796;
--ok:#8fcaa6;--ok-tint:#1d2c23;--warn:#e6b46c;--warn-tint:#33281a;--bad:#f0a193;--bad-tint:#38211d;--info:#a9c2de;--info-tint:#1e2833;
--shadow:0 1px 2px rgba(0,0,0,.3);--shadow-deep:0 12px 40px rgba(0,0,0,.45);color-scheme:dark;}}
*{box-sizing:border-box;margin:0}
html{-webkit-text-size-adjust:100%}
body{font-family:var(--sans);font-size:15px;background:var(--canvas);color:var(--ink);line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
:focus-visible{outline:2px solid var(--accent-ink);outline-offset:2px;border-radius:4px}
.ic{flex:none;display:block}
.wrap{max-width:920px;margin:0 auto;padding:0 20px}
/* ---------- header ---------- */
header{background:color-mix(in srgb,var(--canvas) 88%,transparent);backdrop-filter:saturate(1.2) blur(8px);border-bottom:1px solid var(--whisper);position:sticky;top:0;z-index:20}
.nav{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 20px;max-width:1180px;margin:0 auto}
.brand{display:flex;align-items:center;gap:9px;text-decoration:none}
.brand-name{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:19px;color:var(--ink);letter-spacing:-.01em}
.brand-name b{font-weight:500;color:var(--accent-ink)}
.nav-actions{display:flex;gap:2px 4px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.nav a.ghost,.nav .ghostbtn{text-decoration:none;color:var(--muted);font-size:14px;font-weight:500;padding:8px 11px;border-radius:7px;background:none;border:none;font-family:inherit;cursor:pointer}
.nav a.ghost:hover,.nav .ghostbtn:hover{color:var(--ink);background:var(--whisper)}
.nav a.btn{background:var(--accent);color:var(--on-accent);text-decoration:none;padding:8px 15px;border-radius:8px;font-size:14px;font-weight:600;margin-left:4px}
.nav a.btn:hover{background:var(--accent-hover)}
.who{font-size:13px;color:var(--faint);padding:0 6px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:620px){.nav{padding:10px 14px}.brand-name{font-size:17px}.nav a.ghost,.nav .ghostbtn{padding:7px 8px;font-size:13.5px}.who{display:none}.nav a.opt{display:none}}
/* ---------- public pages ---------- */
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--accent-ink)}
.cta .primary{background:var(--accent);color:var(--on-accent)}
.cta .primary:hover{background:var(--accent-hover)}
.cta .secondary{background:var(--surface);color:var(--ink);box-shadow:0 0 0 1px var(--line-2) inset}
.cta .secondary:hover{box-shadow:0 0 0 1px var(--accent-ink) inset}
/* ---------- signed-in app layout (Notion-style sidebar) ---------- */
.app{display:grid;grid-template-columns:236px minmax(0,1fr);max-width:1180px;margin:0 auto;min-height:calc(100vh - 60px)}
.side{border-right:1px solid var(--whisper);padding:18px 12px;position:sticky;top:57px;height:calc(100vh - 57px);overflow:auto}
.side nav{display:flex;flex-direction:column;gap:1px}
.side .grp{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);padding:14px 10px 6px}
.side a{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink-2);font-size:14.5px;font-weight:500;padding:7px 10px;border-radius:7px}
.side a:hover{background:var(--whisper);color:var(--ink)}
.side a.on{background:var(--sand);color:var(--ink)}
.side a.on .ic{color:var(--accent-ink)}
.side .count{margin-left:auto;background:var(--accent);color:var(--on-accent);font-size:11px;font-weight:700;border-radius:999px;padding:1px 7px;min-width:20px;text-align:center}
.side .tip{margin:18px 6px 0;font-size:12.5px;color:var(--muted);background:var(--surface);border:1px solid var(--whisper);border-radius:10px;padding:12px}
.side .tip a{display:inline;padding:0;font-size:inherit;font-weight:600;color:var(--accent-ink);text-decoration:underline;text-underline-offset:2px}
.side .tip a:hover{background:none}
.main{padding:8px 32px 40px;min-width:0}
.main .wrap{max-width:none;padding:0}
@media(max-width:900px){.app{grid-template-columns:1fr}.side{position:static;height:auto;border-right:none;border-bottom:1px solid var(--whisper);padding:8px 10px}
.side nav{flex-direction:row;overflow-x:auto;gap:4px;scrollbar-width:none}.side nav::-webkit-scrollbar{display:none}.side .grp,.side .tip{display:none}
.side a{white-space:nowrap;padding:7px 10px;font-size:14px}.main{padding:4px 16px 36px}}
/* ---------- page heads (Kami numbered section) ---------- */
.page-head{margin:26px 0 22px}
.page-head .num{font-family:var(--display);font-stretch:84%;font-size:14px;color:var(--accent-ink);letter-spacing:.03em}
.page-head h1,h2.page{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:clamp(26px,3.2vw,32px);line-height:1.18;letter-spacing:-.015em;color:var(--ink);margin:6px 0 6px}
h2.page{margin:28px 0 8px}
.page-head p,.lead{color:var(--muted);font-size:15.5px;margin-bottom:22px;max-width:62ch}
.page-head p{margin-bottom:0}
h3.sec{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:19px;margin:28px 0 10px;letter-spacing:-.005em}
h3.sec small{font-family:var(--sans);font-size:13px;color:var(--faint);font-weight:400;margin-left:6px}
/* ---------- cards, bento ---------- */
.card{background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:18px 20px;transition:box-shadow .2s}
.card+.card{margin-top:12px}
.card.lift:hover{box-shadow:var(--shadow)}
.bento{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px;margin:6px 0 20px}
.tile{background:var(--surface);border:1px solid var(--whisper);border-radius:14px;padding:18px 18px 16px;grid-column:span 2;display:flex;flex-direction:column;gap:8px;min-width:0}
.tile.tall{grid-row:span 2}.tile.w3{grid-column:span 3}.tile.w4{grid-column:span 4}.tile.w6{grid-column:span 6}
.tile.tint{background:var(--accent-tint);border-color:transparent}
.tile.goldt{background:var(--gold-tint);border-color:transparent}
.tile h3{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:18px;letter-spacing:-.005em;display:flex;align-items:center;gap:8px}
.tile h3 .ic{color:var(--accent-ink)}
.tile p{color:var(--muted);font-size:13.5px}
.tile .big{font-family:var(--display);font-stretch:84%;font-size:38px;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums}
.tile .foot{margin-top:auto;padding-top:6px}
@media(max-width:900px){.bento{grid-template-columns:repeat(2,minmax(0,1fr))}.tile,.tile.w3,.tile.w4,.tile.w6{grid-column:span 2}.tile.tall{grid-row:auto}}
.meter{height:7px;background:var(--sand);border-radius:999px;overflow:hidden}
.meter i{display:block;height:100%;background:var(--accent);border-radius:999px}
.meter.ok i{background:var(--ok)}.meter.warn i{background:var(--warn)}.meter.bad i{background:var(--bad)}
/* ---------- buttons ---------- */
.b{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:none;border-radius:8px;padding:9px 15px;font:600 14px/1.2 var(--sans);cursor:pointer;text-decoration:none;background:var(--accent);color:var(--on-accent);transition:background .15s,box-shadow .15s}
.b:hover{background:var(--accent-hover)}
.b.sec{background:var(--sand);color:var(--ink)}.b.sec:hover{background:var(--line-2)}
.b.ghost{background:transparent;color:var(--accent-ink);box-shadow:0 0 0 1px var(--line-2) inset}.b.ghost:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;background:transparent}
.b.danger{background:transparent;color:var(--bad);box-shadow:0 0 0 1px var(--line-2) inset}.b.danger:hover{background:var(--bad-tint)}
.b.sm{padding:6px 11px;font-size:13px;border-radius:7px}
.b[disabled]{opacity:.55;cursor:not-allowed}
.submit-btn,.apply-btn{display:inline-block;background:var(--accent);color:var(--on-accent);border:none;border-radius:8px;padding:12px 24px;font:600 15px/1.2 var(--sans);cursor:pointer;text-decoration:none}
.submit-btn:hover,.apply-btn:hover{background:var(--accent-hover)}
.linkbtn{background:none;border:none;color:var(--accent-ink);text-decoration:underline;cursor:pointer;font:inherit;padding:0}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.row.between{justify-content:space-between}
.stack>*+*{margin-top:10px}
.muted{color:var(--muted)}.faint{color:var(--faint)}.small{font-size:13px}
/* ---------- pills, chips, badges ---------- */
.pill{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;background:var(--sand);color:var(--ink-2);white-space:nowrap;letter-spacing:.01em}
.pill.accent{background:var(--accent-tint);color:var(--accent-ink)}
.pill.gold{background:var(--gold-tint);color:var(--gold-ink)}
.pill.ok{background:var(--ok-tint);color:var(--ok)}.pill.warn{background:var(--warn-tint);color:var(--warn)}.pill.bad{background:var(--bad-tint);color:var(--bad)}.pill.info{background:var(--info-tint);color:var(--info)}
.chip{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--sunk);color:var(--muted);font-weight:500;box-shadow:0 0 0 1px var(--whisper) inset}
.badge{font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px;white-space:nowrap}
.badge.verified{background:var(--ok-tint);color:var(--ok)}
.badge.warning{background:var(--warn-tint);color:var(--warn)}
.badge.held{background:var(--bad-tint);color:var(--bad)}
/* ---------- jobs ---------- */
.controls{margin:22px 0 8px}
.searchbar{display:flex;gap:8px;margin-bottom:14px}
.searchbar input{flex:1}
.searchbar button{background:var(--accent);color:var(--on-accent);border:none;border-radius:8px;padding:0 20px;font-weight:600;font-size:14px;cursor:pointer}
.filter-row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.filter-row .label{font-size:11px;color:var(--faint);font-weight:600;align-self:center;margin-right:4px;text-transform:uppercase;letter-spacing:.08em}
.chipf{background:var(--surface);color:var(--muted);padding:5px 12px;border-radius:999px;font-size:13px;text-decoration:none;font-weight:500;box-shadow:0 0 0 1px var(--whisper) inset}
.chipf:hover{color:var(--ink)}
.chipf.active{background:var(--ink);color:var(--canvas);box-shadow:none}
.results-head{font-size:13px;color:var(--faint);margin:18px 0 10px}
.job{background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:16px 18px;margin-bottom:10px;text-decoration:none;color:inherit;display:block;transition:box-shadow .2s,border-color .2s}
.job:hover{box-shadow:var(--shadow);border-color:var(--line-2)}
.job-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.job-title{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:18px;color:var(--ink);letter-spacing:-.005em}
.job-co{color:var(--muted);font-size:14px;margin-top:1px}
.job-meta{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.why{font-size:13px;color:var(--ok);margin-top:8px}
.empty{text-align:center;color:var(--muted);padding:48px 20px;font-size:15px;background:var(--surface);border:1px dashed var(--line-2);border-radius:12px}
.detail-desc{white-space:pre-wrap;margin:18px 0;font-size:15px;line-height:1.7;max-width:70ch}
.finding{border-left:2px solid var(--line-2);padding:5px 0 5px 12px;margin:8px 0;font-size:13.5px}
.finding.critical{border-color:var(--bad)}.finding.warning{border-color:var(--warn)}.finding.note{border-color:var(--faint)}
.finding b{font-weight:600}
.back{color:var(--muted);text-decoration:none;font-size:14px;display:inline-block;margin:22px 0 6px}
.back:hover{color:var(--ink)}
/* ---------- banners ---------- */
.banner{border-radius:10px;padding:13px 15px;margin-bottom:18px;font-size:14px;border:1px solid transparent}
.banner.verified{background:var(--ok-tint);color:var(--ok)}
.banner.warning{background:var(--warn-tint);color:var(--warn)}
.banner.held{background:var(--bad-tint);color:var(--bad)}
.banner.info{background:var(--info-tint);color:var(--info)}
/* ---------- forms ---------- */
.form-field{margin-bottom:16px}
label{display:block;font-size:14px;font-weight:600;margin-bottom:5px}
.hint{font-size:13px;color:var(--muted);margin-bottom:7px}
input,textarea,select{width:100%;border:1px solid var(--line-2);border-radius:8px;padding:10px 12px;font-family:inherit;font-size:15px;background:var(--surface);color:var(--ink)}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent-ink);box-shadow:0 0 0 3px var(--accent-tint)}
textarea{min-height:140px;resize:vertical;line-height:1.55}
input[type=checkbox],input[type=radio]{width:auto;accent-color:var(--accent)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}
@media(max-width:620px){.grid2{grid-template-columns:1fr}}
.checks{display:flex;flex-wrap:wrap;gap:7px}
.chk{position:relative}
.chk input{position:absolute;opacity:0;inset:0;margin:0;cursor:pointer}
.chk span{display:inline-block;font-size:13.5px;font-weight:500;padding:6px 12px;border-radius:999px;background:var(--surface);box-shadow:0 0 0 1px var(--line-2) inset;color:var(--ink-2);cursor:pointer}
.chk input:checked+span{background:var(--accent);color:var(--on-accent);box-shadow:none}
.chk input:focus-visible+span{outline:2px solid var(--accent-ink);outline-offset:2px}
.toggle{display:flex;gap:10px;align-items:flex-start;font-weight:400;font-size:14.5px;margin-bottom:12px}
.toggle input{margin-top:4px}
.toggle b{font-weight:600}
.steps{display:flex;gap:6px;margin:6px 0 22px}
.steps span{flex:1;height:4px;border-radius:999px;background:var(--sand)}
.steps span.on{background:var(--accent)}
.stepname{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}
.navform{display:inline;margin:0}
.inline-form{margin:0 0 14px;display:block}
.counter{font-size:12px;color:var(--faint);text-align:right;margin-top:4px}
/* ---------- auth ---------- */
.auth{max-width:440px;margin:36px auto 12px;background:var(--surface);border:1px solid var(--whisper);border-radius:16px;padding:30px 28px;box-shadow:var(--shadow)}
.auth-title{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:28px;text-align:center;color:var(--ink);margin-bottom:6px}
.auth.start{text-align:center;padding-top:34px}.auth.start .form-field{text-align:left}
.startmark{width:56px;height:56px;margin:0 auto 14px;display:grid;place-items:center;border-radius:14px;background:var(--accent-tint)}
.startmark svg{width:34px;height:34px}.start-foot{margin-top:18px;font-size:14px;color:var(--muted)}.start-foot a{color:var(--accent-ink);font-weight:600}
.auth-sub{text-align:center;color:var(--muted);font-size:14px;margin-bottom:18px}
.tabs{display:flex;gap:4px;background:var(--sunk);border-radius:10px;padding:4px;margin:16px 0 22px;box-shadow:0 0 0 1px var(--whisper) inset}
.tabs a{flex:1;text-align:center;text-decoration:none;color:var(--muted);font-size:14px;font-weight:600;padding:8px 10px;border-radius:7px}
.tabs a.active{background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
.label-row{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.forgot{font-size:14px;color:var(--accent-ink);margin-bottom:5px}
.pwbox{position:relative}
.pwbox input{padding-right:64px}
.showpw{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--muted);font:inherit;font-size:14px;font-weight:600;cursor:pointer;padding:6px 8px}
.rules{list-style:none;padding:0;margin:-6px 0 16px;font-size:13px;color:var(--muted);display:grid;grid-template-columns:1fr 1fr;gap:2px 12px}
.rules li::before{content:"○ "}
.rules li.ok{color:var(--ok)}.rules li.ok::before{content:"✓ "}
.submit-btn.wide,.outline-btn{display:block;width:100%;text-align:center;text-decoration:none}
.fine{font-size:13px;color:var(--muted);text-align:center;margin-top:10px}
.or{display:flex;align-items:center;gap:12px;color:var(--faint);font-size:14px;margin:20px 0}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
.outline-btn{border-radius:8px;padding:12px 16px;font-weight:600;font-size:15px;color:var(--ink);background:var(--surface);box-shadow:0 0 0 1px var(--line-2) inset}
.outline-btn:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;color:var(--accent-ink)}
.choose{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:8px 0 24px}
@media(max-width:640px){.choose{grid-template-columns:1fr}.auth{padding:24px 18px}}
.choose .card h3{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:20px;margin-bottom:6px}
.choose p{color:var(--muted);font-size:14px;margin-bottom:16px}
.choose .row a{text-decoration:none;font-size:14px;font-weight:600;padding:9px 16px;border-radius:8px}
.choose .row a.pri{background:var(--accent);color:var(--on-accent)}.choose .row a.sec{box-shadow:0 0 0 1px var(--line-2) inset;color:var(--ink)}
.prose p{margin:0 0 14px;max-width:64ch}.prose h3{margin:26px 0 8px;font-family:var(--display);font-weight:650;font-stretch:84%;font-size:19px}.prose ul{margin:0 0 14px 20px;max-width:64ch}.prose li{margin-bottom:4px}
/* ---------- review queue ---------- */
.rev-card{background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:18px 20px;margin-bottom:12px}
.rev-score{display:inline-block;font-weight:700;padding:3px 10px;border-radius:999px;font-size:12.5px}
.rev-score.clear{background:var(--ok-tint);color:var(--ok)}.rev-score.flagged{background:var(--warn-tint);color:var(--warn)}.rev-score.held{background:var(--bad-tint);color:var(--bad)}
.rev-actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.rev-actions button{border:none;border-radius:8px;padding:8px 15px;font-weight:600;font-size:14px;cursor:pointer;font-family:inherit}
.btn-approve{background:var(--ok);color:#fff}
.btn-reject{background:var(--sand);color:var(--bad)}
.admin-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 18px}
/* ---------- avatars, people ---------- */
.avatar{width:38px;height:38px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-family:var(--display);font-stretch:84%;font-size:16px;background:var(--gold-tint);color:var(--gold-ink);flex:none}
.avatar.emp{border-radius:10px;background:var(--accent-tint);color:var(--accent-ink)}
.avatar.lg{width:64px;height:64px;font-size:26px}
.person{display:flex;gap:12px;align-items:center;min-width:0}
.person .nm{font-weight:600;font-size:14.5px;line-height:1.25}
.person .sub{font-size:12.5px;color:var(--muted);line-height:1.3}
.skills{display:flex;flex-wrap:wrap;gap:6px}
/* ---------- messaging ---------- */
.inbox{display:grid;grid-template-columns:300px minmax(0,1fr);border:1px solid var(--whisper);border-radius:14px;background:var(--surface);overflow:hidden;min-height:540px}
.threads{border-right:1px solid var(--whisper);overflow:auto;max-height:72vh}
.threads a{display:block;text-decoration:none;padding:13px 15px;border-bottom:1px solid var(--whisper)}
.threads a:hover{background:var(--canvas)}
.threads a.on{background:var(--sand)}
.threads .t1{display:flex;justify-content:space-between;gap:8px;font-size:14px;font-weight:600}
.threads .t2{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.threads .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);display:inline-block;margin-left:6px;flex:none;align-self:center}
.convo{display:flex;flex-direction:column;min-width:0}
.convo-head{padding:13px 18px;border-bottom:1px solid var(--whisper);display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.thread{flex:1;overflow:auto;padding:18px;display:flex;flex-direction:column;gap:10px;max-height:58vh;background:var(--canvas)}
.bubble{max-width:78%;padding:10px 13px;border-radius:14px;font-size:14.5px;white-space:pre-wrap;word-wrap:break-word;line-height:1.5}
.bubble.them{background:var(--surface);border:1px solid var(--whisper);border-bottom-left-radius:4px;align-self:flex-start}
.bubble.me{background:var(--accent);color:var(--on-accent);border-bottom-right-radius:4px;align-self:flex-end}
.bubble .meta{display:block;font-size:11px;opacity:.7;margin-top:4px}
.bubble.flag{border-color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
.scanbox{align-self:flex-start;max-width:78%;background:var(--warn-tint);color:var(--warn);border-radius:10px;padding:9px 12px;font-size:13px}
.scanbox.bad{background:var(--bad-tint);color:var(--bad)}
.scanbox ul{margin:4px 0 0 18px}
.composer{border-top:1px solid var(--whisper);padding:12px;display:flex;gap:8px;align-items:flex-end;background:var(--surface)}
.composer textarea{min-height:46px;max-height:180px;height:46px;resize:none}
@media(max-width:820px){.inbox{grid-template-columns:1fr}.threads{max-height:none;border-right:none}.inbox.open .threads{display:none}.inbox:not(.open) .convo{display:none}}
/* ---------- assistant ---------- */
.chat{border:1px solid var(--whisper);border-radius:14px;background:var(--surface);display:flex;flex-direction:column;min-height:560px}
.chat .log{flex:1;padding:20px;display:flex;flex-direction:column;gap:14px;overflow:auto;max-height:64vh}
.chat .say{max-width:88%;font-size:14.5px;line-height:1.6;white-space:pre-wrap}
.chat .say.me{align-self:flex-end;background:var(--sand);padding:9px 13px;border-radius:14px 14px 4px 14px}
.chat .say.bot{align-self:flex-start}
.chat .say.bot .who{display:flex;gap:7px;align-items:center;font-size:12px;font-weight:600;color:var(--accent-ink);padding:0;margin-bottom:4px}
.chat .cards{display:grid;gap:8px;margin-top:10px}
.chat .cards .job{margin:0}
.chat .sugg{display:flex;flex-wrap:wrap;gap:7px;padding:0 20px 14px}
.chat .sugg button{background:var(--canvas);border:none;box-shadow:0 0 0 1px var(--line-2) inset;border-radius:999px;padding:7px 12px;font:500 13px var(--sans);color:var(--ink-2);cursor:pointer}
.chat .sugg button:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;color:var(--accent-ink)}
.chat form{border-top:1px solid var(--whisper);padding:12px;display:flex;gap:8px}
.chat form textarea{min-height:46px;height:46px;resize:none}
.typing{color:var(--faint);font-size:13px}
.aimode{font-size:12px;color:var(--faint)}
/* ---------- verdicts (scam check) ---------- */
.verdict{border-radius:14px;padding:20px 22px;margin:18px 0;border:1px solid transparent}
.verdict h2{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:24px;margin:2px 0 6px;display:flex;align-items:center;gap:10px}
.verdict.ok{background:var(--ok-tint);color:var(--ok)}
.verdict.caution{background:var(--info-tint);color:var(--info)}
.verdict.warn{background:var(--warn-tint);color:var(--warn)}
.verdict.bad{background:var(--bad-tint);color:var(--bad)}
.verdict p{color:inherit;opacity:.92}
.reasons{margin:10px 0 0;padding:0;list-style:none}
.reasons li{background:var(--surface);color:var(--ink);border-radius:10px;padding:10px 12px;margin-top:8px;font-size:14px;border:1px solid var(--whisper)}
.reasons li b{font-weight:600}
.reasons li .ev{display:block;font-size:12.5px;color:var(--muted);margin-top:3px}
.next{counter-reset:n;list-style:none;padding:0}
.next li{counter-increment:n;padding-left:34px;position:relative;margin:10px 0;font-size:14.5px}
.next li::before{content:counter(n);position:absolute;left:0;top:0;width:24px;height:24px;border-radius:50%;background:var(--sand);color:var(--ink);font:600 12px/24px var(--sans);text-align:center}
/* ---------- resume ---------- */
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
.split>.card+.card{margin-top:0}
@media(max-width:960px){.split{grid-template-columns:1fr}}
.score{display:flex;align-items:center;gap:16px}
.ring{--p:0;width:86px;height:86px;border-radius:50%;background:conic-gradient(var(--accent) calc(var(--p)*1%),var(--sand) 0);display:grid;place-items:center;flex:none}
.ring b{width:68px;height:68px;border-radius:50%;background:var(--surface);display:grid;place-items:center;font-family:var(--display);font-weight:650;font-stretch:84%;font-size:26px;font-variant-numeric:tabular-nums}
.cat{display:grid;grid-template-columns:150px 1fr 44px;gap:10px;align-items:center;font-size:13.5px;margin:7px 0}
.cat span:last-child{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.sugg-item{border:1px solid var(--whisper);border-radius:10px;padding:12px 14px;margin-top:10px;background:var(--canvas)}
.sugg-item .was{color:var(--muted);font-size:13.5px;text-decoration:line-through;text-decoration-color:var(--faint)}
.sugg-item .now{font-size:14.5px;margin-top:6px}
.sugg-item .iss{font-size:12.5px;color:var(--warn);margin-top:4px}
.kw{display:flex;flex-wrap:wrap;gap:6px}
textarea.resume{min-height:420px;font-family:var(--sans);font-size:14.5px;line-height:1.55}
/* ---------- feed ---------- */
.post{background:var(--surface);border:1px solid var(--whisper);border-radius:14px;padding:16px 18px;margin-bottom:12px}
.post .head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.post .body{white-space:pre-wrap;word-wrap:break-word;font-size:15px;margin:12px 0 10px;line-height:1.6}
.post .lnk{font-size:13px;word-break:break-all}
.post .acts{display:flex;gap:6px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--whisper);padding-top:10px;margin-top:6px}
.post .acts form{margin:0}
.post .acts button,.post .acts a{background:none;border:none;font:500 13px var(--sans);color:var(--muted);padding:6px 9px;border-radius:7px;cursor:pointer;text-decoration:none}
.post .acts button:hover,.post .acts a:hover{background:var(--whisper);color:var(--ink)}
.post .acts .on{color:var(--accent-ink)}
.comments{margin-top:10px;border-left:2px solid var(--line);padding-left:12px}
.comment{font-size:14px;margin:8px 0}
.comment b{font-weight:600}
.composer-card{background:var(--surface);border:1px solid var(--whisper);border-radius:14px;padding:14px 16px;margin-bottom:16px}
.composer-card textarea{min-height:84px}
.seg{display:inline-flex;background:var(--sunk);border-radius:10px;padding:3px;gap:2px;box-shadow:0 0 0 1px var(--whisper) inset;flex-wrap:wrap}
.seg a{text-decoration:none;font-size:13px;font-weight:600;color:var(--muted);padding:6px 11px;border-radius:7px}
.seg a.on{background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
table.t{width:100%;border-collapse:collapse;font-size:14px}
table.t th{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line)}
table.t td{padding:10px;border-bottom:1px solid var(--whisper);vertical-align:top}
/* ---------- profile (LinkedIn header + sections, Handshake side column) ---------- */
.phero{padding:0;overflow:hidden}
.pbanner{height:118px;background:linear-gradient(120deg,var(--accent-tint),var(--gold-tint));position:relative}
.pbanner.emp{background:linear-gradient(120deg,var(--gold-tint),var(--sunk))}
.pbanner::after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(135deg,transparent 0 22px,var(--whisper) 22px 23px);opacity:.7}
.pinfo{padding:0 24px 20px}
.avatar.xl{width:108px;height:108px;font-size:38px;margin-top:-54px;border:4px solid var(--surface);position:relative;z-index:1}
.phero h1{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:28px;line-height:1.2;margin-top:10px;letter-spacing:-.01em}
.phero .pron{font-family:var(--sans);font-size:14px;color:var(--faint);font-weight:400}
.phero .headline{font-size:15.5px;color:var(--ink-2);margin-top:3px;max-width:62ch}
.phero .school,.phero .where{font-size:14px;color:var(--muted);margin-top:3px}
.plinks a{color:var(--accent-ink);font-weight:600;text-decoration:none;margin-right:12px}
.opento{margin-top:14px;background:var(--sunk);border-radius:10px;padding:10px 14px;font-size:14px;display:inline-block;box-shadow:0 0 0 1px var(--whisper) inset}
.opento b{font-weight:600;margin-right:6px}
.opento a{color:var(--accent-ink);font-weight:600;margin-left:6px}
.pgrid{display:grid;grid-template-columns:280px minmax(0,1fr);gap:14px;margin-top:14px;align-items:start}
.pside{display:flex;flex-direction:column;gap:12px;position:sticky;top:76px}
.pmain{display:flex;flex-direction:column;gap:12px;min-width:0}
.pside .card+.card,.pmain .card+.card{margin-top:0}
.phead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px}
.phead h2{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:19px;letter-spacing:-.005em}
.iconbtn{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:50%;color:var(--muted);text-decoration:none;flex:none}
.iconbtn:hover{background:var(--whisper);color:var(--ink)}
.entry{display:grid;grid-template-columns:48px minmax(0,1fr);gap:14px;padding:14px 0;border-top:1px solid var(--whisper)}
.entries>.entry:first-child{border-top:none;padding-top:4px}
.entry.slim{display:flex;justify-content:space-between;align-items:center;padding:8px 0;font-size:14.5px}
.logo{width:48px;height:48px;border-radius:10px;background:var(--sand);display:grid;place-items:center;font-family:var(--display);font-stretch:84%;font-size:17px;color:var(--ink-2)}
.logo.edu{background:var(--accent-tint);color:var(--accent-ink)}
.entry .t{font-weight:600;font-size:15px;line-height:1.35}.entry .s{font-size:14px;color:var(--ink-2)}.entry .m{font-size:13px;color:var(--faint)}
.entry .desc,.pcard .desc{white-space:pre-wrap;font-size:14px;margin-top:8px;line-height:1.6;overflow-wrap:anywhere}
.entry .small{display:inline-block;margin-top:6px;color:var(--accent-ink);font-weight:600;text-decoration:none}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.lf+.lf{margin-top:12px}
.lfl{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:600}
.pdata{margin-top:10px}
@media(max-width:960px){.pgrid{grid-template-columns:1fr}.pside{position:static}.pinfo{padding:0 16px 16px}}
/* ---------- job fit ---------- */
.fit{display:grid;grid-template-columns:auto minmax(0,1fr);gap:18px;align-items:center}
.fit .ring{width:96px;height:96px}.fit .ring b{width:76px;height:76px;font-size:28px}
.fitlabel{font-family:var(--display);font-weight:650;font-stretch:84%;font-size:22px}
.fitparts{margin-top:14px}
.fitparts .cat{grid-template-columns:170px 1fr 44px}
.fitparts .why2{grid-column:1/-1;font-size:12.5px;color:var(--muted);margin:-4px 0 4px}
.checklist{list-style:none;padding:0;margin:0;display:grid;gap:6px}
.checklist li{display:grid;grid-template-columns:22px minmax(0,1fr);gap:8px;font-size:14px;align-items:start}
.checklist .st{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700}
.checklist .met .st{background:var(--ok-tint);color:var(--ok)}.checklist .missing .st{background:var(--warn-tint);color:var(--warn)}
.checklist .unknown .st{background:var(--sand);color:var(--muted)}
.checklist .ev{display:block;font-size:12.5px;color:var(--muted)}
@media(max-width:620px){.fit{grid-template-columns:1fr}.fitparts .cat{grid-template-columns:120px 1fr 40px}}
/* ---------- visitors ---------- */
.job.teaser .pill{white-space:nowrap}.job.teaser .job-title{filter:none}
/* ---------- hiring ---------- */
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0 8px}
.stat{background:var(--surface);border-radius:12px;box-shadow:0 0 0 1px var(--whisper) inset;padding:12px 14px}
.stat .n{font-family:var(--display);font-stretch:84%;font-size:28px;font-weight:500;line-height:1.1;font-variant-numeric:tabular-nums}
.stat .l{font-size:13px;color:var(--ink-2)}.stat .s{font-size:12px;color:var(--faint);margin-top:2px}
.stats.two{grid-template-columns:repeat(2,minmax(0,1fr))}.stats.two .l{font-size:12px}
.pside .fitparts .cat{grid-template-columns:minmax(0,1fr) 64px 30px}
.stats.sm{margin:12px 0 0}.stats.sm .stat{padding:8px 10px;background:var(--sunk)}.stats.sm .n{font-size:20px}
a.hjob{display:block;text-decoration:none;color:inherit;margin-bottom:10px}
.mcard{margin-bottom:10px}.mcard .chips .chip{font-size:12px}
.ring.sm{width:52px;height:52px}.ring.sm b{width:40px;height:40px;font-size:17px}
.cform{display:grid;grid-template-columns:200px minmax(0,1fr) auto;gap:10px;align-items:end;margin-top:10px}
.cform .form-field{margin:0}
@media(max-width:620px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.cform{grid-template-columns:1fr}}
/* ---------- footer ---------- */
footer{color:var(--faint);font-size:12px;border-top:1px solid var(--whisper);margin-top:48px;padding:22px;text-align:center;line-height:1.7}
footer .tm{display:block;margin-top:6px;font-size:11.5px}
footer a{color:var(--muted)}
/* ---------- display type, motion and effects ----------
   Borrowed from the reference sites: condensed uppercase display type, a cursor-reactive dot grid,
   a light that follows the cursor around card borders, one marquee, and one scroll-driven listing scan.
   Everything degrades to a still page without JS, without scroll-driven animation, and under reduced motion. */
.display{font-family:var(--display);font-weight:800;font-stretch:70%;text-transform:uppercase;letter-spacing:-.005em;line-height:.9}
.display em{font-style:normal;color:var(--accent-ink)}
.page-head h1,h2.page{font-weight:700;font-stretch:78%;letter-spacing:0;font-size:clamp(28px,3.6vw,38px);line-height:1.05}
.brand-name{font-weight:700;font-stretch:88%;letter-spacing:0}
.b,.submit-btn,.apply-btn,.cta a,.nav a.btn{transition:background .15s,box-shadow .15s,transform .15s var(--ease)}
.b:active,.submit-btn:active,.apply-btn:active,.cta a:active,.nav a.btn:active{transform:translateY(1px) scale(.985)}
/* display lines that rise into place */
.display .ln{display:block;overflow:hidden;padding-bottom:.04em}
.display .ln>span{display:inline-block}
.display .dot{color:var(--gold)}
/* ---------- cinematic landing: full-bleed footage and photography with big type over it ----------
   The student hero is a camera move through a brick archway, scrubbed by scroll: static/fx.js draws
   the frames onto a canvas and sets --p (0 to 1) on the section. With no JS, reduced motion or a slow
   connection it is a still photo with the first caption, and nothing is pinned. */
main>.cine:first-child,main>.chapter.top:first-child{margin-top:calc(-1 * var(--hdr,55px))}
.cine,.chapter{position:relative;isolation:isolate;background:#120d0c;color:#fff}
.cine-stage{position:relative;height:100vh;height:100svh;min-height:560px;max-height:1100px;overflow:hidden}
.cine-media,.ch-media{position:absolute;inset:0;z-index:-1;overflow:hidden}
.cine-media .pan,.ch-media .pan{position:absolute;inset:-2.5%;will-change:transform}
.cine-media img,.cine-media canvas,.ch-media img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:var(--fx,62%) 50%;display:block}
.cine-media canvas{opacity:0;transition:opacity .6s}
.cine.ready .cine-media canvas{opacity:1}
.scrim{position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(180deg,rgba(12,8,7,.5),rgba(12,8,7,0) 22%),linear-gradient(90deg,rgba(12,8,7,.8),rgba(12,8,7,.46) 40%,rgba(12,8,7,0) 74%),linear-gradient(0deg,rgba(12,8,7,.6),rgba(12,8,7,0) 44%)}
.cine-copy{position:absolute;inset:0;max-width:1180px;margin:0 auto;padding:0 20px clamp(44px,9vh,96px);display:grid;align-items:end}
.cap{grid-area:1/1;max-width:900px}
.cine .eyebrow,.chapter .eyebrow{color:var(--gold);letter-spacing:.14em}
.cine h1.display,.chapter .display{color:#fff;margin:12px 0 18px}
.cine h1.display{font-size:clamp(50px,10.2vw,146px)}
.cine .display em,.chapter .display em{color:var(--gold)}
.cap p,.ch-copy p{font-size:clamp(16px,1.45vw,19px);color:rgba(255,255,255,.84);max-width:44ch;margin:0 0 26px}
.cap .note{margin:14px 0 0;font-size:clamp(15px,1.3vw,17px)}
.cap p.big{font-size:clamp(46px,8.8vw,128px);line-height:.9;color:#fff;max-width:none;margin:0}
.cine .cta,.chapter .cta{display:flex;gap:10px;flex-wrap:wrap}
.cine .cta a,.chapter .cta a{text-decoration:none;padding:13px 24px;border-radius:9px;font-weight:600;font-size:15px}
.cine .cta .secondary,.chapter .cta .secondary{background:rgba(255,255,255,.08);color:#fff;box-shadow:0 0 0 1px rgba(255,255,255,.42) inset;-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
.cine .cta .secondary:hover,.chapter .cta .secondary:hover{background:rgba(255,255,255,.16);box-shadow:0 0 0 1px #fff inset}
.cine .cta .primary:hover,.chapter .cta .primary:hover{background:var(--accent-hover)}
.cap.c1,.cap.c2,.cine-rail{display:none}
.cine-rail{position:absolute;left:0;right:0;bottom:22px;max-width:1140px;margin:0 auto;padding:0 20px;align-items:center;gap:14px;font-size:11.5px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.7)}
.cine-rail .bar{flex:1;height:1px;background:rgba(255,255,255,.22);position:relative;overflow:hidden}
.cine-rail .bar i{position:absolute;inset:0;background:var(--gold);transform-origin:left;transform:scaleX(var(--p,0))}
/* live: pinned while the camera moves; captions cross-fade on --p */
.cine.live{height:340vh}
.cine.live .cine-stage{position:sticky;top:0}
.cine.live .cap.c1,.cine.live .cap.c2{display:block}
.cine.live .cine-rail{display:flex}
.cine.live .cap{--o:clamp(0,min(calc((var(--p,0) - var(--a)) * 12),calc((var(--b) - var(--p,0)) * 12)),1);opacity:var(--o);transform:translateY(calc((1 - var(--o)) * 30px));pointer-events:none}
.cine.live .c0{--a:-9;--b:.2}.cine.live .c1{--a:.28;--b:.58}.cine.live .c2{--a:.66;--b:9}
.cine.live[data-cap="0"] .c0{pointer-events:auto}
.cine.live:not([data-cap="0"]) .c0{visibility:hidden}
/* photo chapters */
.chapter{overflow:hidden;min-height:min(92vh,900px);min-height:min(92svh,900px);display:grid;align-items:end}
.chapter.top{min-height:100vh;min-height:100svh;max-height:1100px}
.ch-copy{max-width:1180px;width:100%;margin:0 auto;padding:140px 20px clamp(48px,10vh,104px)}
.chapter .display{font-size:clamp(46px,8.4vw,124px)}
.chapter.top h1.display{font-size:clamp(46px,8.8vw,128px)}
@media(max-width:700px){.scrim{background:linear-gradient(180deg,rgba(12,8,7,.5),rgba(12,8,7,0) 26%),linear-gradient(0deg,rgba(12,8,7,.86),rgba(12,8,7,.5) 46%,rgba(12,8,7,0) 78%)}}
/* what employers get */
.gets{max-width:1120px;margin:0 auto;padding:56px 20px 0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.gets .hb{background:var(--surface);border:1px solid var(--whisper);border-radius:16px;padding:22px 22px 20px}
.gets .hb .ic{color:var(--accent-ink);margin-bottom:16px}
.gets h3{font-family:var(--display);font-weight:750;font-stretch:78%;font-size:22px;line-height:1.1;margin-bottom:8px}
.gets p{color:var(--muted);font-size:14.5px}
@media(max-width:820px){.gets{grid-template-columns:1fr;padding-top:40px}}
/* the header floats over the footage until you scroll past it (fx.js adds html.over and header.solid) */
html.over header{transition:background .35s,border-color .35s}
html.over header:not(.solid){background:transparent;border-bottom-color:transparent;-webkit-backdrop-filter:none;backdrop-filter:none}
html.over header:not(.solid) .brand-name{color:#fff}
html.over header:not(.solid) .brand-name b{color:var(--gold)}
html.over header:not(.solid) .nav a.ghost,html.over header:not(.solid) .nav .ghostbtn,html.over header:not(.solid) .who{color:rgba(255,255,255,.88)}
html.over header:not(.solid) .nav a.ghost:hover,html.over header:not(.solid) .nav .ghostbtn:hover{color:#fff;background:rgba(255,255,255,.14)}
/* marquee (one per page) */
.marquee{border-block:1px solid var(--whisper);overflow:hidden;background:var(--surface);padding:14px 0;
  -webkit-mask:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent);mask:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent)}
.marquee .track{display:flex;width:max-content;gap:0}
.marquee ul{display:flex;list-style:none;padding:0;margin:0}
.marquee li{font-family:var(--display);font-weight:750;font-stretch:72%;text-transform:uppercase;font-size:clamp(20px,2.4vw,30px);letter-spacing:.005em;color:var(--ink-2);padding:0 22px;white-space:nowrap;display:flex;align-items:center;gap:22px}
.marquee li::after{content:"";width:9px;height:9px;background:var(--gold);transform:rotate(45deg);flex:none}
.marquee .cap{font-size:12.5px;color:var(--faint);text-align:center;margin-top:8px}
/* the scanner: a fake listing read by the real detector as you scroll (static/fx.js drives it). With no JS or reduced
   motion it is shown finished: every phrase marked, every flag listed, the stamp down. */
.scan{background:var(--stage);color:var(--on-stage);position:relative}
.scan-stick{max-width:1160px;margin:0 auto;padding:84px 20px;display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:56px;align-items:center}
.scan h2.display{font-size:clamp(42px,4.8vw,70px);color:var(--on-stage);margin:12px 0 18px}
.scan h2.display em{color:var(--gold)}
.scan .eyebrow{color:var(--gold);letter-spacing:.14em}
.scan-copy p{color:var(--on-stage-2);font-size:17px;max-width:40ch;margin:0}
.scan-cta{margin-top:22px!important}
.scan-cta a{color:var(--gold);font-weight:600;text-decoration:none}.scan-cta a:hover{text-decoration:underline}
.scan-side,.scan-board{position:relative;min-width:0}
.scan .live-only,.scan.armed .static-only{display:none}.scan.armed .live-only{display:inline}
.scan-card{position:relative;overflow:hidden;background:#faf8f3;color:#1c1917;border-radius:14px;padding:20px 22px 18px;box-shadow:0 24px 60px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.06)}
.scan-card .top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.scan-card h3{font-size:16.5px;font-weight:700;line-height:1.3}
.scan-card .tag{font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#6b655c;border:1px solid #d9d3c7;border-radius:999px;padding:3px 9px;flex:none}
.scan-card .co{font-size:12.5px;color:#6b655c;margin:2px 0 12px}
.scan-card .body{font-size:14.5px;line-height:1.85;margin:0}
.scan-card .apply{font-size:13px;color:#6b655c;margin:12px 0 0}
.scan-card mark{background:color-mix(in srgb,var(--sev,#c2410c) 13%,transparent);color:inherit;border-radius:2px;box-shadow:inset 0 -2px 0 var(--sev,#c2410c);transition:box-shadow .35s var(--ease),background-color .45s}
.scan-card mark.crit{--sev:#b91c1c}.scan-card mark.warn{--sev:#b7791f}
.scan-card sup{font-size:10px;font-weight:700;color:var(--sev,#b7791f);margin:0 2px 0 1px;transition:opacity .3s}
.scan-card sup.crit{--sev:#b91c1c}.scan-card sup.warn{--sev:#b7791f}
.scan-line{position:absolute;left:0;right:0;top:0;height:2px;background:var(--gold);box-shadow:0 0 14px 2px color-mix(in srgb,var(--gold) 70%,transparent);opacity:0;pointer-events:none;z-index:2}
.scan-line::before{content:"";position:absolute;left:0;right:0;bottom:2px;height:56px;background:linear-gradient(0deg,color-mix(in srgb,var(--gold) 22%,transparent),transparent)}
.scan-stamp{position:absolute;right:16px;bottom:14px;z-index:3;border:2.5px solid #b91c1c;color:#b91c1c;background:rgba(250,248,243,.94);border-radius:8px;padding:5px 12px;
  font-family:var(--display);font-weight:800;font-stretch:72%;text-transform:uppercase;font-size:21px;letter-spacing:.01em;line-height:1.1;white-space:nowrap;transform:rotate(-3deg)}
/* the flags, filling in as the line reaches each phrase */
.scan-flags{list-style:none;padding:0;margin:14px 0 0;display:grid;gap:6px}
.scan-flags li{display:flex;align-items:center;gap:10px;background:var(--stage-2);border:1px solid rgba(243,238,230,.1);border-radius:9px;padding:8px 12px;font-size:13.5px;font-weight:600;
  transition:opacity .4s var(--ease),transform .4s var(--ease)}
.scan-flags .n{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:800;flex:none;background:#e3b964;color:#2a1f0a}
.scan-flags li.crit .n{background:#f0a193;color:#3a1410}
.scan-flags .sev{margin-left:auto;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--on-stage-2);font-weight:700}
.scan-flags li.crit .sev{color:#f0a193}
.scan-verdict{margin-top:14px;border-radius:12px;padding:13px 16px;background:#3a1a17;border:1px solid rgba(240,161,147,.35);color:#fbe4df;transition:opacity .5s var(--ease),transform .5s var(--ease)}
.scan-verdict b{font-family:var(--display);font-weight:800;font-stretch:72%;text-transform:uppercase;font-size:20px;letter-spacing:.01em;color:#f0a193;margin-right:8px}
.scan-verdict span{font-size:13px}
.scan-verdict p{font-size:13px;margin:4px 0 0;color:#e8cfc9}.scan-verdict a{color:#fff;font-weight:600}
@media(max-width:900px){
  .scan-stick{grid-template-columns:1fr;gap:34px;padding:60px 20px}
  .scan-card{padding:16px 16px 52px}.scan-card .body{font-size:13.5px;line-height:1.7}.scan-card .co{margin-bottom:8px}
  .scan-stamp{bottom:12px;right:12px;font-size:17px}
  .scan-flags{margin-top:10px;gap:5px}.scan-flags li{padding:6px 10px;font-size:12.5px}.scan-flags .n{width:18px;height:18px}
}
/* armed by fx.js: things appear as the scan line reaches them */
.scan.armed .scan-line{opacity:1}
.scan.armed .scan-card mark:not(.on){box-shadow:inset 0 -2px 0 transparent;background-color:transparent}
.scan.armed .scan-card mark.flash{background-color:color-mix(in srgb,var(--sev) 30%,transparent)}
.scan.armed .scan-card sup:not(.on){opacity:0}
.scan.armed .scan-flags li:not(.on){opacity:0;transform:translateX(12px)}
.scan.armed .scan-verdict:not(.on){opacity:0;transform:translateY(10px)}
.scan.armed .scan-stamp{opacity:0;transform:rotate(-3deg) scale(1.15)}
.scan.armed .scan-stamp.on{opacity:1;transform:rotate(-3deg) scale(1);transition:opacity .25s,transform .35s var(--ease)}
.scan.armed.done .scan-line{opacity:0;transition:opacity .6s}
@media(min-width:901px){.scan.pinned{height:250vh}.scan.pinned .scan-stick{position:sticky;top:0;min-height:100vh;min-height:100svh}}
/* phones: the copy scrolls away normally and only the card and its flags pin, just under the header */
@media(max-width:900px){.scan.pinned .scan-track{height:calc(var(--bh,100svh) + 240svh)}.scan.pinned .scan-board{position:sticky;top:calc(var(--hdr,55px) + 12px)}}
/* how it works: an asymmetric bento instead of three equal cards */
.how-bento{max-width:1120px;margin:0 auto;padding:64px 20px 20px;display:grid;grid-template-columns:1.25fr 1fr;grid-template-rows:auto auto;gap:16px}
.how-bento .hb{background:var(--surface);border:1px solid var(--whisper);border-radius:16px;padding:24px 24px 22px;position:relative}
.how-bento.three{grid-template-rows:auto auto auto}.how-bento.three .hb.lead{grid-row:span 3}
.how-bento .hb.lead{grid-row:span 2;background:var(--accent);color:var(--on-accent);border-color:transparent;display:flex;flex-direction:column;justify-content:flex-end;min-height:320px}
.how-bento .hb.lead .big{font-family:var(--display);font-weight:800;font-stretch:66%;text-transform:uppercase;font-size:clamp(40px,5vw,64px);line-height:.9;margin-bottom:auto;padding-bottom:28px}
.how-bento .hb.lead p{color:color-mix(in srgb,var(--on-accent) 82%,transparent)}
.how-bento .hb.gold{background:var(--gold-tint)}
.how-bento h3{font-family:var(--display);font-weight:750;font-stretch:78%;font-size:24px;line-height:1.1;margin-bottom:8px}
.how-bento p{color:var(--muted);font-size:14.5px;max-width:46ch}
@media(max-width:820px){.how-bento{grid-template-columns:1fr;padding:44px 20px 12px}.how-bento .hb.lead{grid-row:auto;min-height:0}}
.section-title{font-size:clamp(36px,5vw,64px);margin:64px 0 12px}
.home-list{max-width:1120px;margin:0 auto;padding:0 20px 24px}
.teasers{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}.teasers .job{margin:0}
/* reveal on scroll (public pages only) */
@supports (animation-timeline:view()){@media (prefers-reduced-motion:no-preference){
  .rv{animation:rv-in linear both;animation-timeline:view();animation-range:entry 0% cover 28%}
}}
@keyframes rv-in{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:no-preference){
  .cine .c0 .ln>span,.chapter.top .ln>span{animation:ln-up 1s var(--ease) .1s both}
  .cine .c0 .ln:nth-child(2)>span,.chapter.top .ln:nth-child(2)>span{animation-delay:.18s}
  .cine .c0 .eyebrow,.cine .c0 p,.cine .c0 .cta,.chapter.top .eyebrow,.chapter.top p,.chapter.top .cta{animation:fade-up 1s var(--ease) .32s both}
  .chapter.top .ch-media img{animation:settle 2.4s var(--ease) both}
  .marquee .track{animation:marquee 46s linear infinite}
  .marquee:hover .track{animation-play-state:paused}
}
@keyframes ln-up{from{transform:translateY(105%)}to{transform:none}}
@keyframes fade-up{from{opacity:0;transform:translateY(18px)}}
@keyframes settle{from{transform:scale(1.08)}to{transform:none}}
@supports (animation-timeline:view()){@media (prefers-reduced-motion:no-preference){
  .chapter:not(.top) .ch-media img{animation:ch-drift linear both;animation-timeline:view();animation-range:cover 0% cover 100%}
  .chapter:not(.top){view-timeline:--ch block}
  .chapter:not(.top) .ch-copy>*{animation:rv-in linear both;animation-timeline:--ch;animation-range:entry 35% entry 85%}
  .chapter:not(.top) .ch-copy>:nth-child(n+3){animation-range:entry 45% entry 95%}
}}
@keyframes ch-drift{from{transform:scale(1.16) translateY(-3%)}to{transform:scale(1.03) translateY(3%)}}
@keyframes marquee{to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.marquee .track{width:auto;flex-wrap:wrap;justify-content:center}.marquee ul[aria-hidden]{display:none}.marquee ul{flex-wrap:wrap;justify-content:center;row-gap:8px}}
/* a light that follows the cursor around card borders (fine pointers only) */
@media (hover:hover) and (pointer:fine){
  .spot,.card,.tile,.job,.hb,.rev-card,.post,.stat{position:relative}
  .spot::before,.card::before,.tile::before,.job::before,.hb::before,.rev-card::before,.post::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1.5px;pointer-events:none;opacity:0;transition:opacity .35s;
    background:radial-gradient(240px circle at var(--mx,50%) var(--my,50%),var(--gold),color-mix(in srgb,var(--accent) 60%,transparent) 35%,transparent 70%);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0)}
  .spot:hover::before,.card:hover::before,.tile:hover::before,.job:hover::before,.hb:hover::before,.rev-card:hover::before,.post:hover::before{opacity:1}
  .spot::after,.tile::after,.job::after,.hb::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .35s;
    background:radial-gradient(420px circle at var(--mx,50%) var(--my,50%),color-mix(in srgb,var(--gold) 9%,transparent),transparent 60%)}
  .spot:hover::after,.tile:hover::after,.job:hover::after,.hb:hover::after{opacity:1}
  .how-bento .hb.lead::after{background:radial-gradient(420px circle at var(--mx,50%) var(--my,50%),rgba(255,255,255,.08),transparent 60%)}
}
/* ---------- signed-in pages: welcome band, KPIs, fit badges, funnel, pipeline, reviewer desk ----------
   Quiet on purpose: numbers count up once, rings and bars draw in when they reach the screen, nothing loops.
   fx.js adds html.fx (never under reduced motion); without it everything is simply shown finished. */
@property --ringp{syntax:"<number>";inherits:false;initial-value:0}
.ring{--ringp:var(--p);background:conic-gradient(var(--accent) calc(var(--ringp)*1%),var(--sand) 0)}
.ring.in,.fitb.in i{transition:--ringp 1.2s var(--ease)}
.meter i{transform-origin:left}.meter.in i{transition:transform 1.1s var(--ease)}
html.fx .ring:not(.in),html.fx .fitb:not(.in) i{--ringp:0}
html.fx .meter:not(.in) i,html.fx .funnel:not(.in) .fb{transform:scaleX(0)}
html.fx .risk:not(.in) .gauge b{left:0}
@media (prefers-reduced-motion:no-preference){
  html.fx .checklist.in li{animation:fade-up .45s var(--ease) both}
  html.fx .checklist:not(.in) li{opacity:0}
  html.fx .checklist.in li:nth-child(2){animation-delay:.05s}html.fx .checklist.in li:nth-child(3){animation-delay:.1s}
  html.fx .checklist.in li:nth-child(4){animation-delay:.15s}html.fx .checklist.in li:nth-child(5){animation-delay:.2s}
  html.fx .checklist.in li:nth-child(n+6){animation-delay:.25s}
}
/* welcome band on each role's home */
.hello{position:relative;isolation:isolate;overflow:hidden;background:var(--stage);color:var(--on-stage);border-radius:18px;padding:30px 30px 24px;margin:0 0 18px}
.hello .ph{position:absolute;inset:0;z-index:-1;background:var(--ph) 70% 50%/cover no-repeat;opacity:.55;
  -webkit-mask:linear-gradient(90deg,transparent 18%,#000 78%);mask:linear-gradient(90deg,transparent 18%,#000 78%)}
.hello .eyebrow{color:var(--gold);letter-spacing:.14em}
.hello h1{font-family:var(--display);font-weight:800;font-stretch:70%;text-transform:uppercase;font-size:clamp(34px,4.8vw,58px);line-height:.92;margin:10px 0 12px;letter-spacing:-.005em;color:var(--on-stage)}
.hello h1 em{font-style:normal;color:var(--gold)}
.hello p{color:var(--on-stage-2);max-width:52ch;font-size:15px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px 18px;margin-top:24px;max-width:640px}
.kpi{display:block;text-decoration:none;color:inherit;border-top:1px solid rgba(243,238,230,.2);padding-top:10px}
.kpi .n{font-family:var(--display);font-weight:750;font-stretch:72%;font-size:42px;line-height:1;font-variant-numeric:tabular-nums;display:block;transition:color .2s}
.kpi .l{font-size:12.5px;color:var(--on-stage-2);display:block;margin-top:5px}
a.kpi:hover .n,.kpi.hot .n{color:var(--gold)}
.hello .foot{margin-top:18px;display:flex;gap:8px;flex-wrap:wrap}
.hello .b.sec{background:rgba(255,255,255,.08);color:var(--on-stage);box-shadow:0 0 0 1px rgba(255,255,255,.3) inset}
.hello .b.sec:hover{background:rgba(255,255,255,.15)}
@media(max-width:620px){.hello{padding:24px 18px 20px;border-radius:14px}.kpi .n{font-size:34px}.hello .ph{opacity:.35}}
/* fit badge: a small ring next to the number */
.fitb{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--accent-ink);background:var(--accent-tint);border-radius:999px;padding:3px 10px 3px 4px;white-space:nowrap;flex:none}
.fitb i{--ringp:var(--p);width:17px;height:17px;border-radius:50%;background:conic-gradient(currentColor calc(var(--ringp)*1%),color-mix(in srgb,currentColor 20%,transparent) 0);
  -webkit-mask:radial-gradient(circle,transparent 4.6px,#000 5.2px);mask:radial-gradient(circle,transparent 4.6px,#000 5.2px)}
.fitb b{font-weight:600}
.fitb.hi{color:var(--ok);background:var(--ok-tint)}.fitb.lo{color:var(--muted);background:var(--sunk)}
/* employer funnel: every number measured against how many students viewed */
.stats.funnel .stat{position:relative;overflow:hidden}
.stats.funnel .fb{position:absolute;left:0;right:0;bottom:0;height:3px;background:var(--sand)}
.stats.funnel .fb i{display:block;height:100%;width:calc(var(--f,0) * 100%);background:var(--accent);border-radius:0 3px 3px 0}
.stats.funnel .fb{transform-origin:left}.stats.funnel.in .fb{transition:transform 1.1s var(--ease)}
.stats.funnel.in .stat:nth-child(2) .fb{transition-delay:.08s}.stats.funnel.in .stat:nth-child(3) .fb{transition-delay:.16s}.stats.funnel.in .stat:nth-child(4) .fb{transition-delay:.24s}
/* candidate pipeline */
.pipe{display:flex;gap:4px;margin:0 0 14px;flex-wrap:wrap}
.pstep{flex:1 1 90px;background:var(--sunk);border-radius:8px;padding:8px 12px;box-shadow:0 0 0 1px var(--whisper) inset;min-width:0}
.pstep .n{font-family:var(--display);font-weight:750;font-stretch:72%;font-size:24px;line-height:1;display:block;color:var(--faint);font-variant-numeric:tabular-nums}
.pstep .l{font-size:11.5px;color:var(--muted);font-weight:600}
.pstep.has{background:var(--surface)}.pstep.has .n{color:var(--accent-ink)}
/* reviewer desk: the queue counts as big numbers, with keyboard hints */
.desk{background:var(--stage);color:var(--on-stage);border-radius:18px;padding:26px 26px 0;margin:0 0 18px;overflow:hidden}
.desk-top{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;flex-wrap:wrap}
.desk .eyebrow{color:var(--gold);letter-spacing:.14em}
.desk h1{font-family:var(--display);font-weight:800;font-stretch:70%;text-transform:uppercase;font-size:clamp(32px,4.2vw,50px);line-height:.95;margin-top:8px;color:var(--on-stage)}
.keys{font-size:12px;color:var(--on-stage-2);display:flex;gap:5px;align-items:center}
kbd{font:600 11px var(--sans);min-width:20px;height:20px;display:inline-grid;place-items:center;padding:0 5px;border-radius:5px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2)}
.desk kbd{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.25);color:var(--on-stage)}
.qtabs{display:flex;gap:0;margin-top:22px;overflow-x:auto;scrollbar-width:none}
.qtabs a{flex:1 0 auto;text-decoration:none;color:var(--on-stage-2);padding:10px 16px 14px 0;margin-right:16px;border-bottom:2px solid transparent;min-width:84px}
.qtabs a .n{display:block;font-family:var(--display);font-weight:750;font-stretch:72%;font-size:30px;line-height:1;color:var(--on-stage);font-variant-numeric:tabular-nums}
.qtabs a .n.zero{color:rgba(243,238,230,.3)}
.qtabs a .l{font-size:12px;font-weight:600;display:block;margin-top:4px;white-space:nowrap}
.qtabs a:hover .l{color:var(--on-stage)}
.qtabs a.on{border-bottom-color:var(--gold)}.qtabs a.on .l{color:var(--gold)}
.rev-card{scroll-margin-top:84px;transition:box-shadow .2s}
.rev-card.cur{box-shadow:0 0 0 2px var(--gold),var(--shadow-deep)}
.rev-card:focus{outline:none}
.hello,.desk{box-shadow:0 0 0 1px var(--whisper) inset}
@media (hover:none){.keys{display:none}}
/* reviewer gauge: 0-100 in four zones (0-25 green, 26-50 yellow, 51-75 orange, 76-100 red), solid colours; the marker
   sits at the score (ui.risk_position) */
.risk{--g:#5f9a7b;--y:#d3b04f;--o:#d98e57;--r:#c1554b;
  display:flex;align-items:center;gap:8px;margin-top:12px;font-size:11.5px;font-weight:600;color:var(--muted)}
.risk .end{font-size:10.5px;color:var(--faint);font-weight:500;font-variant-numeric:tabular-nums}
.risk .gauge{position:relative;flex:1;max-width:360px;height:6px;display:grid;grid-template-columns:repeat(4,1fr);gap:2px;margin:0 8px}
.risk .gauge i{border-radius:2px}.risk .gauge i:first-child{border-radius:999px 2px 2px 999px}.risk .gauge i:last-child{border-radius:2px 999px 999px 2px}
.risk .gauge .z0{background:var(--g)}.risk .gauge .z1{background:var(--y)}.risk .gauge .z2{background:var(--o)}.risk .gauge .z3{background:var(--r)}
.risk .gauge b{position:absolute;top:50%;left:var(--pos);width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:var(--surface);border:3px solid var(--mk);box-shadow:0 1px 4px rgba(20,20,19,.28)}
.risk.z0{--mk:var(--g)}.risk.z1{--mk:var(--y)}.risk.z2{--mk:var(--o)}.risk.z3{--mk:var(--r)}
.risk .rl{color:color-mix(in oklab,var(--mk) 80%,var(--ink));margin-left:4px;font-family:var(--display);font-weight:750;font-stretch:80%;font-size:15px;font-variant-numeric:tabular-nums;min-width:3ch}
.risk.in .gauge b{transition:left 1s var(--ease)}
/* easy apply, connections and follows */
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.chip.easy{background:var(--accent-tint);color:var(--accent-ink);font-weight:600}
.appl{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
.appl summary{cursor:pointer;font-size:14px}
.appl .qa{margin-top:10px}.appl .q{font-size:12.5px;color:var(--muted);font-weight:600}.appl .a{font-size:14px;white-space:pre-wrap;margin-top:2px}
.appl .a.resume{font-family:var(--serif);font-size:13px;max-height:260px;overflow:auto;padding:10px 12px;border-radius:10px;background:var(--sunk)}
.easy .pick{display:inline-flex;gap:6px;align-items:center;margin-right:16px;font-size:14px}
.easy fieldset,.easyset{border:0;padding:0;margin:0 0 16px}.easy legend,.easyset legend{font-size:14px;font-weight:600;margin-bottom:6px}
.qrow{display:grid;grid-template-columns:1fr 158px 120px;gap:8px;margin-top:8px}
@media (max-width:640px){.qrow{grid-template-columns:1fr 1fr}.qrow input{grid-column:1/-1}}
.netstrip{gap:12px;align-items:center;margin-top:12px;flex-wrap:wrap}
.ncard{padding:14px 16px;margin-bottom:10px}.rnote{margin:-4px 0 12px 8px}
.cform2{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.cnote{max-width:260px;min-height:0;padding:7px 10px;font-size:13px}
/* profile covers use the site's own photography */
.pbanner.ph{height:150px;background:var(--ph) 50% 60%/cover no-repeat}
.pbanner.ph::after{background:linear-gradient(180deg,rgba(18,13,12,0) 40%,rgba(18,13,12,.35));opacity:1}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

import css_assist, css_jobs, css_resume  # noqa: E402  page styles, one file per area (css_feed appends itself from feed.py)
CSS += css_jobs.CSS + css_resume.CSS + css_assist.CSS

# Kept for compatibility with older imports.
BASE_CSS = CSS

# The one inline script the site runs, and only on account pages: Show/Hide on password fields and
# the live checklist under a new password. The page policy allows exactly this text by hash.
PAGE_SCRIPT = (
    "(function(){"
    "document.querySelectorAll('[data-showpw]').forEach(function(b){b.hidden=false;"
    "b.addEventListener('click',function(){var i=document.getElementById(b.getAttribute('data-showpw'));"
    "var s=i.type==='password';i.type=s?'text':'password';b.textContent=s?'Hide':'Show';"
    "b.setAttribute('aria-pressed',s?'true':'false');});});"
    "var pw=document.querySelector('[data-pwcheck]');"
    "if(pw){var R=[['len',function(v){return v.length>=8}],['upper',function(v){return /[A-Z]/.test(v)}],"
    "['num',function(v){return /[0-9]/.test(v)}],['sym',function(v){return /[!-\\/:-@\\[-`{-~]/.test(v)}]];"
    "var u=function(){R.forEach(function(r){var e=document.querySelector('[data-rule=\"'+r[0]+'\"]');"
    "if(e){e.className=r[1](pw.value)?'ok':''}})};pw.addEventListener('input',u);u();}"
    "})();"
)
PAGE_SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(PAGE_SCRIPT.encode()).digest()).decode()


# ---------- viewer helpers ----------

def viewer() -> dict | None:
    return (_viewer.get() or {}).get("user")


def viewer_token() -> str | None:
    return (_viewer.get() or {}).get("token")


def viewer_extra() -> dict:
    return (_viewer.get() or {}).get("extra") or {}


def user_csrf() -> str:
    tok = viewer_token()
    return make_csrf("user:" + tok) if tok else ""


def user_csrf_input() -> str:
    return f'<input type="hidden" name="csrf" value="{user_csrf()}">'


def initials(name: str) -> str:
    parts = [p for p in (name or "").replace("@", " ").split() if p[:1].isalnum()]
    return esc("".join(p[0] for p in parts[:2]).upper() or "?")


# ---------- navigation ----------

def _logout_form() -> str:
    v = _viewer.get() or {}
    return (f'<form class="navform" method="post" action="/logout">'
            f'<input type="hidden" name="csrf" value="{make_csrf("user:" + v["token"])}">'
            f'<button class="ghostbtn" type="submit">Log out</button></form>')


def _nav_links(admin: bool) -> str:
    v = _viewer.get() or {}
    user = v.get("user")
    extra = '<a class="ghost" href="/admin">Review queue</a>' if admin else ''
    if user:
        post = '<a class="btn" href="/post">Post a job</a>' if user["role"] == "employer" else ''
        return extra + f'<span class="who">{esc(user["email"])}</span>' + _logout_form() + post
    return (extra + '<a class="ghost opt" href="/check">Scam check</a>'
            '<a class="ghost" href="/login">Log in</a><a class="btn" href="/employers">For employers</a>')


_STUDENT_NAV = [
    ("", [("home", "/", "Home"), ("jobs", "/jobs", "Jobs"), ("spark", "/assistant", "Career assistant"),
          ("feed", "/feed", "Feed"), ("chat", "/messages", "Messages"), ("people", "/network", "Network")]),
    ("Career tools", [("send", "/applications", "Applications"), ("file", "/resume", "Resume studio"), ("shield", "/check", "Scam check")]),
    ("You", [("user", "/profile", "Profile")]),
]
_EMPLOYER_NAV = [
    ("", [("home", "/", "Home"), ("jobs", "/jobs", "Jobs"), ("feed", "/feed", "Feed"),
          ("chat", "/messages", "Messages"), ("people", "/talent", "Find students")]),
    ("Hiring", [("jobs", "/hiring", "Your listings"), ("plus", "/post", "Post a job"), ("shield", "/check", "Scam check")]),
    ("You", [("user", "/profile", "Company profile")]),
]


def _sidebar(active: str) -> str:
    user = viewer()
    groups = _STUDENT_NAV if user["role"] == "student" else _EMPLOYER_NAV
    unread = viewer_extra().get("unread", 0)
    reqs = viewer_extra().get("requests", 0)
    out = []
    for grp, items in groups:
        if grp:
            out.append(f'<div class="grp">{esc(grp)}</div>')
        for ic, href, label in items:
            on = ' class="on" aria-current="page"' if href == active else ""
            count = (f'<span class="count" aria-label="{unread} unread">{unread}</span>' if href == "/messages" and unread else
                     f'<span class="count" aria-label="{reqs} connection requests">{reqs}</span>' if href == "/network" and reqs else "")
            out.append(f'<a href="{href}"{on}>{icon(ic)}<span>{esc(label)}</span>{count}</a>')
    tip = ('<div class="tip"><b>Stay safe:</b> real employers never ask you to pay, deposit a check, or buy gift cards. '
           '<a href="/check?kind=message">Check a message</a>.</div>')
    return f'<aside class="side"><nav aria-label="Main">{"".join(out)}</nav>{tip}</aside>'


def _footer() -> str:
    return """<footer>Every listing is scanned for scam signals and reviewed by a human before it appears. A verified badge is not a guarantee. Always confirm an employer through their own website before sharing personal information.
<span class="tm"><a href="/about">About</a> · <a href="/privacy">Privacy</a> · <a href="/report">Report a listing</a> · <a href="/check">Scam check</a></span>
<span class="tm">An independent student project. Not affiliated with, sponsored by, or endorsed by Florida State University; uses no university trademarks or logos.</span></footer>"""


def shell(body: str, title: str = "NoleCareerShield", hero: str = "", admin: bool = False,
          scripts: bool = False, active: str | None = None, js: bool = False, wide: bool = False) -> str:
    """One page. Signed-in people get the app layout (sidebar) unless it's an admin or auth page.
    `scripts` adds the hashed inline password script; `js` adds /static/app.js (same-origin)."""
    user = viewer()
    tail = ""
    if scripts:
        if security.turnstile_enabled():
            tail += '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        tail += f"<script>{PAGE_SCRIPT}</script>"
    if js:
        tail += f'<script src="/static/app.js?v={APP_JS_VERSION}" defer></script>'
    tail += f'<script src="/static/fx.js?v={FX_JS_VERSION}" defer></script>'
    csrf_meta = f'<meta name="csrf" content="{user_csrf()}">' if (user and js) else ""
    head = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{csrf_meta}
<meta name="color-scheme" content="light dark"><link rel="preload" href="/static/fonts/archivo.woff2" as="font" type="font/woff2" crossorigin><style>{CSS}</style></head><body>
<header><div class="nav">
<a class="brand" href="/">{EMBLEM}<span class="brand-name">Nole<b>CareerShield</b></span></a>
<div class="nav-actions">{_nav_links(admin)}</div>
</div></header>"""
    if user and not admin and active is not None:
        return (head + f'<div class="app">{_sidebar(active)}<main class="main" id="main">'
                f'<div class="wrap">{body}</div>{_footer()}</main></div>{tail}</body></html>')
    if wide:        # landing pages: full-width sections, all inside <main>
        return head + f'<main id="main">{hero}{body}</main>{_footer()}{tail}</body></html>'
    return head + f'{hero}<div class="wrap"><main id="main">{body}</main></div>{_footer()}{tail}</body></html>'


def page_head(title: str, lede: str = "", num: str = "") -> str:
    n = f'<div class="num">{esc(num)}</div>' if num else ""
    p = f"<p>{lede}</p>" if lede else ""
    return f'<div class="page-head">{n}<h1>{esc(title)}</h1>{p}</div>'


def banner(kind: str, text: str, raw: bool = False) -> str:
    return f'<div class="banner {kind}" role="{"alert" if kind in ("warning", "held") else "status"}">{text if raw else esc(text)}</div>'


# ---------- landing-page blocks (shared with the demo, which inlines them at build time) ----------

# Patterns the detector catches, in plain words (see scam_detector/rulepack/core.json).
SCAM_PATTERNS = ["Fake checks", "Gift-card pay", "Pay-to-train programs", "Reshipping from home", "Text-only interviews",
                 "Crypto ATM gigs", "Task-app deposits", "Look-alike FSU emails", "Offers you never applied for",
                 "Personal-email recruiters", "Bank details up front"]


def marquee_block() -> str:
    items = "".join(f"<li>{esc(p)}</li>" for p in SCAM_PATTERNS)
    return (f'<section class="marquee" aria-label="Scam patterns the checker catches"><div class="track">'
            f'<ul>{items}</ul><ul aria-hidden="true">{items}</ul></div></section>')


# A fake listing for the landing-page scanner. Its flags are NOT written by hand: scan_findings() runs the
# real detector on it, and tests/test_app.py fails if the detector stops catching any of SCAN_EXPECTED.
SCAN_SAMPLE = {
    "title": "Remote Administrative Assistant", "company": "QuickCash Staffing", "meta": "Remote · Part-time",
    "body": ("Congratulations, you've been selected, no interview needed! This part-time remote assistant role pays "
             "$500 weekly. We'll mail you a check to buy equipment from our approved vendor. Deposit it and send the "
             "balance by Zelle. Text our hiring manager on WhatsApp to get started."),
    "apply": "quickcash.hiring@gmail.com",
}
# rule -> a phrase in the sample it must underline. The test fails if a rule stops firing there.
SCAN_EXPECTED = {"instant_hire": "you've been selected", "weekly_stipend": "$500 weekly", "fake_check_funds": "mail you a check",
                 "advance_fee": "check to buy", "money_mule": "approved vendor", "irreversible_pay": "send the balance by Zelle",
                 "off_platform": "WhatsApp", "personal_email": "@gmail.com"}


def scan_findings() -> dict:
    """Run the sample through the public scam check's listing tab (msgcheck.check_listing, the same code a student
    gets) and place each finding in the text: {findings: [{rule_id, title, severity, spans}], score, title, advice}."""
    import re
    import msgcheck
    s = SCAN_SAMPLE
    r = msgcheck.check_listing(s["title"], s["body"], s["company"], contact=s["apply"])
    text = s["body"] + "\n" + s["apply"]
    placed = []
    for f in r["findings"]:
        spans = []
        for phrase in f.get("matched") or []:
            rx = re.compile(r"\s+".join(re.escape(w) for w in phrase.split()), re.I)
            m = rx.search(text)
            if m:
                spans.append((m.start(), m.end()))
        placed.append({"rule_id": f["rule_id"], "title": f["title"], "severity": f["severity"], "spans": sorted(spans)})
    # Number the flags in reading order: by where each one's last underline ends.
    placed.sort(key=lambda f: (f["spans"][-1][1] if f["spans"] else 10 ** 6, f["spans"][0][0] if f["spans"] else 0))
    return {"score": r["score"], "band": r["band"], "title": r["title"], "advice": (r["steps"] or [r["advice"]])[0],
            "findings": placed, "text": text}


def _scan_text(text: str, findings: list, breaks: tuple = ()) -> str:
    """The sample text with every flagged phrase underlined and a numbered marker after each flag. A NUL is left at
    each position in `breaks`, so the caller can split the result into pieces (the card breaks along them)."""
    cuts = {0, len(text)} | set(breaks)
    for f in findings:
        for a, b in f["spans"]:
            cuts |= {a, b}
    cuts = sorted(cuts)
    ends: dict[int, list] = {}
    for i, f in enumerate(findings, 1):
        if f["spans"]:
            ends.setdefault(f["spans"][-1][1], []).append((i, f))
    sev = lambda f: "crit" if f["severity"] == "critical" else "warn"
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if a in breaks:
            out.append("\x00")
        seg = esc(text[a:b])
        cover = [(i, f) for i, f in enumerate(findings, 1) if any(x <= a and b <= y for x, y in f["spans"])]
        if cover:
            worst = min(cover, key=lambda t: t[1]["severity"] != "critical")[1]
            out.append(f'<mark class="{sev(worst)}" data-f="{" ".join(str(i) for i, _ in cover)}">{seg}</mark>')
        else:
            out.append(seg)
        for i, f in ends.get(b, []):
            out.append(f'<sup class="{sev(f)}" data-f="{i}">{i}</sup>')
    return "".join(out)


def scan_block(cta_html: str) -> str:
    """Rendered finished (every flag underlined, listed and stamped), so it reads without JS or with reduced motion.
    static/fx.js arms it and replays the scan as you scroll."""
    s, r = SCAN_SAMPLE, scan_findings()
    body, _, apply = _scan_text(r["text"], r["findings"]).rpartition("\n")
    crit = lambda f: f["severity"] == "critical"
    flags = "".join(
        f'<li class="{"crit" if crit(f) else "warn"}" data-f="{i}">'
        f'<span class="n">{i}</span>{esc(f["title"])}<span class="sev">{"Critical" if crit(f) else "Warning"}</span></li>'
        for i, f in enumerate(r["findings"], 1))
    n = len(r["findings"])
    return f"""<section class="scan" data-scan aria-labelledby="scan-h"><div class="scan-stick">
<div class="scan-copy"><div class="eyebrow">A fake listing, read by the real detector</div>
<h2 class="display" id="scan-h">Know it's real<br><em>before you apply.</em></h2>
<p>This listing is made up. <span class="live-only">Scroll and watch the scam check read it.</span><span class="static-only">Here's what the scam check found in it.</span> Every flag is something the detector caught on its own, not something we wrote in.</p>
<p class="scan-cta">{cta_html}</p></div>
<div class="scan-side"><div class="scan-track"><div class="scan-board"><div class="scan-card"><div class="scan-line" aria-hidden="true"></div>
<div class="top"><h3>{esc(s["title"])}</h3><span class="tag">Sample</span></div><p class="co">{esc(s["company"])} · {esc(s["meta"])}</p>
<p class="body">{body}</p><p class="apply">Apply: {apply}</p><div class="scan-stamp" aria-hidden="true">{esc(r["title"])}</div></div>
<ol class="scan-flags" aria-label="What the detector found">{flags}</ol></div></div>
<div class="scan-verdict"><b>{esc(r["title"])}</b><span>Scam risk {r["score"]}/100 from {n} signals.</span>
<p>{esc(r["advice"])} {cta_html}</p></div></div>
</div></section>"""


def how_bento(lead_big: str, lead_text: str, tiles: list[tuple[str, str]], three: bool = False) -> str:
    cells = "".join(f'<div class="hb{" gold" if i == 0 else ""} rv"><h3>{esc(t)}</h3><p>{esc(p)}</p></div>' for i, (t, p) in enumerate(tiles))
    return (f'<section class="how-bento{" three" if three else ""}"><div class="hb lead rv"><div class="big">{lead_big}</div>'
            f'<p>{esc(lead_text)}</p></div>{cells}</section>')


def how_students() -> str:
    return how_bento("Only vetted<br>listings.", "Every posting is scam-scanned, then a person approves it. Employers are reviewed before they can message you.",
                     [("Tools that work for you", "A job assistant that knows your skills, a resume reviewer and tailorer, and a checker for any suspicious message."),
                      ("An FSU-only feed", "Only verified students and approved employers post, and employer posts must be opportunities or advice for FSU students.")])


def how_employers() -> str:
    return how_bento("Verified students.<br>Reviewed employers.", "Students answer your messages because they know every employer here was checked by a person.",
                     [("Create your account", "Use an email on your company's domain. It helps us verify you faster and raises your trust score."),
                      ("Get approved", "A person checks your website, email and how you work with FSU students, usually within a business day."),
                      ("Post and match", "Each listing is scam-scanned and reviewed, then shown with your trust score. Your ranked matches are ready as soon as it's live.")],
                     three=True)


# ---------- cinematic landing blocks ----------
# Footage and photos live in static/media (made for this site; no real FSU buildings, people or marks).
# `links` maps a name to the attributes of each link, so the demo can point them at its own router.

SITE_LINKS = {"join": 'href="/login"', "check": 'href="/check"', "check_msg": 'href="/check?kind=message"',
              "emp_signup": 'href="/signup/employer"', "emp_login": 'href="/login/employer"'}
RULE_COUNT = len(json.loads((Path(__file__).resolve().parent / "scam_detector" / "rulepack" / "core.json").read_text())["rules"])
CINE_FRAMES = 75          # static/media/arch-000.webp .. arch-074.webp, 1280x720
MEDIA_VERSION = "1"       # app.py sets this from the files, so browsers can cache them for good


def media_url(name: str) -> str:
    return f"/static/media/{name}?v={MEDIA_VERSION}"


def _photo(name: str, focus: str = "62%", eager: bool = False) -> str:
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<img src="{media_url(name + "-1920.webp")}" srcset="{media_url(name + "-960.webp")} 960w, '
            f'{media_url(name + "-1920.webp")} 1920w" sizes="100vw" width="1920" height="1080" alt="" {load} '
            f'decoding="async" style="--fx:{focus}">')


def cine_hero(links: dict | None = None) -> str:
    """Student landing hero: a camera move through a brick archway into the quad, scrubbed by scroll."""
    L = links or SITE_LINKS
    frames = media_url("arch-{n}.webp")
    return f"""<section class="cine" data-cine data-frames="{frames}" data-count="{CINE_FRAMES}" aria-label="Welcome">
<div class="cine-stage"><div class="cine-media" aria-hidden="true"><div class="pan" data-pan>
<img src="{media_url("arch-000.webp")}" width="1280" height="720" alt="" fetchpriority="high"><canvas></canvas></div></div><div class="scrim"></div>
<div class="cine-copy">
<div class="cap c0"><div class="eyebrow">For FSU students</div>
<h1 class="display"><span class="ln"><span>Student jobs.</span></span><span class="ln"><span><em>Checked</em> for scams<span class="dot">.</span></span></span></h1>
<p>Every listing is scanned, then approved by a professional, before an FSU student ever sees it.</p>
<div class="cta"><a class="primary" {L["join"]}>Join with your FSU email</a><a class="secondary" {L["check"]}>Try the scam check</a></div></div>
<div class="cap c1"><p class="display big">Scanned for<br><em>scam signals</em><span class="dot">.</span></p>
<p class="note">Fake checks, gift-card pay, look-alike school emails: {RULE_COUNT} patterns in all.</p></div>
<div class="cap c2"><p class="display big">Then approved<br>by a <em>professional</em><span class="dot">.</span></p>
<p class="note">Nothing reaches the board on a score alone.</p></div>
</div>
<div class="cine-rail" aria-hidden="true"><span>Scroll</span><span class="bar"><i></i></span><span>Checked</span></div>
</div></section>"""


def chapter(photo: str, eyebrow: str, title_html: str, text: str, cta_html: str = "", focus: str = "62%",
            top: bool = False) -> str:
    """A full-bleed photo with big type over it. `top` makes it the page's first section (with the h1)."""
    h = "h1" if top else "h2"
    return (f'<section class="chapter{" top" if top else ""}"><div class="ch-media" aria-hidden="true"><div class="pan"{" data-pan" if top else ""}>'
            f'{_photo(photo, focus, eager=top)}</div><div class="scrim"></div></div><div class="ch-copy">'
            f'<div class="eyebrow">{esc(eyebrow)}</div><{h} class="display">{title_html}</{h}><p>{esc(text)}</p>'
            f'{f"<div class=cta>{cta_html}</div>" if cta_html else ""}</div></section>')


def students_chapters(links: dict | None = None) -> tuple[str, str]:
    """The two photo chapters on the student landing: before the scanner, and before the listings."""
    L = links or SITE_LINKS
    night = chapter("night", "11:48 pm, a new message",
                    '<span class="ln"><span>Not every offer</span></span><span class="ln"><span>is <em>what it seems</em><span class="dot">.</span></span></span>',
                    "Most fake jobs look almost real. The scam check reads a listing or a message the way scammers write them, line by line.",
                    f'<a class="secondary" {L["check"]}>Check one you got</a>', focus="58%")
    fair = chapter("fair", "Employers, checked first",
                   '<span class="ln"><span>Meet employers</span></span><span class="ln"><span><em>vetted</em> by a professional<span class="dot">.</span></span></span>',
                   "Every employer is reviewed before they can post a job or message you, and every listing is reviewed again.",
                   f'<a class="primary" {L["join"]}>Join with your FSU email</a>', focus="50%")
    return night, fair


def employer_hero(links: dict | None = None, reach: str = "") -> str:
    L = links or SITE_LINKS
    return chapter("office", "For employers",
                   '<span class="ln"><span>Hire FSU students.</span></span><span class="ln"><span>On a board they <em>trust</em><span class="dot">.</span></span></span>',
                   f"{reach}Every student is a confirmed @fsu.edu account, and every employer and listing is reviewed by a person.",
                   f'<a class="primary" {L["emp_signup"]}>Create an employer account</a><a class="secondary" {L["emp_login"]}>Employer log in</a>',
                   focus="66%", top=True)


def employer_gets() -> str:
    tiles = [("people", "Ranked matches for every listing", "Each student who opted in, scored against your listing on their whole profile, with the evidence: skills, projects, coursework, GPA."),
             ("chat", "Invite to apply in one click", "A ready-to-send message about the role. Students see you're an approved employer."),
             ("jobs", "Candidates and listing stats", "Track students from new to hired, and see how many viewed and clicked Apply.")]
    cells = "".join(f'<div class="hb rv">{icon(ic, 24)}<h3>{esc(t)}</h3><p>{esc(p)}</p></div>' for ic, t, p in tiles)
    return f'<section class="gets" aria-label="What employers get">{cells}</section>'


def employer_chapter(links: dict | None = None) -> str:
    L = links or SITE_LINKS
    return chapter("fair", "Before the career fair",
                   '<span class="ln"><span>Meet them</span></span><span class="ln"><span>before the <em>fair</em><span class="dot">.</span></span></span>',
                   "Students answer because every employer here was checked by a person. Your ranked matches are ready the day a listing goes live.",
                   f'<a class="primary" {L["emp_signup"]}>Create an employer account</a>', focus="50%")


# ---------- signed-in pieces (the demo has JS twins of these in demo/app.js) ----------

def kpi(n, label: str, href: str = "", hot: bool = False) -> str:
    tag, attr = ("a", f' href="{href}"') if href else ("div", "")
    return f'<{tag} class="kpi{" hot" if hot else ""}"{attr}><span class="n">{n}</span><span class="l">{esc(label)}</span></{tag}>'


def hello_band(eyebrow: str, title_html: str, lede: str, kpis: str = "", photo: str = "", foot: str = "") -> str:
    """The dark welcome band at the top of each role's home. `photo` is a static/media file name."""
    ph = f'<div class="ph" aria-hidden="true" style="--ph:url({media_url(photo)})"></div>' if photo else ""
    return (f'<section class="hello">{ph}<div class="eyebrow">{esc(eyebrow)}</div><h1>{title_html}</h1><p>{esc(lede)}</p>'
            f'{f"<div class=kpis>{kpis}</div>" if kpis else ""}{f"<div class=foot>{foot}</div>" if foot else ""}</section>')


def fit_badge(score: int, label: str = "") -> str:
    """'Fit 81' with a small ring. Green at 65 and up (good or strong fit), grey under 45."""
    tone = " hi" if score >= 65 else " lo" if score < 45 else ""
    return (f'<span class="fitb{tone}" style="--p:{int(score)}" title="{esc(label or "Fit score")}">'
            f'<i aria-hidden="true"></i><b>Fit {int(score)}</b></span>')


def desk(title: str, tabs: list[tuple[str, str, int | None, bool]]) -> str:
    """Reviewer header: title, the queues as big counts (href, label, count, active), keyboard hints."""
    cells = "".join(
        f'<a href="{h}"{" class=on aria-current=page" if on else ""}><span class="n{" zero" if not n else ""}">{n or 0}</span>'
        f'<span class="l">{esc(label)}</span></a>' for h, label, n, on in tabs)
    return (f'<section class="desk"><div class="desk-top"><div><div class="eyebrow">Reviewer</div><h1>{esc(title)}</h1></div>'
            f'<span class="keys"><kbd>J</kbd><kbd>K</kbd> next and previous card</span></div>'
            f'<nav class="qtabs" aria-label="Review queues">{cells}</nav></section>')


RISK_BANDS = ((0, 25), (26, 50), (51, 75), (76, 100))       # green, yellow, orange, red on the reviewer's gauge


RISK_MIN, RISK_MAX = 4, 96      # a check is never a perfect 0 or 100, so the gauge never shows one


def shown_score(score: int, aggregator: bool = False) -> int:
    """The number the reviewer sees: never 0 or 100, and an aggregator (scam score 0 by design) reads 60, orange."""
    sc = int(score)
    if aggregator and sc < 15:
        return 60
    return max(RISK_MIN, min(RISK_MAX, sc))


def risk_position(score: int, status: str = "", aggregator: bool = False) -> tuple[int, float, float]:
    """Where a listing sits on the reviewer's gauge: (zone 0-3, percent along the track, how far into its zone
    0-1). The marker sits at the shown score."""
    sc = shown_score(score, aggregator)
    zone = next(i for i, (lo, hi) in enumerate(RISK_BANDS) if sc <= hi)
    lo, hi = RISK_BANDS[zone]
    return zone, float(sc), round((sc - lo) / (hi - lo), 2)


def risk_meter(score: int, status: str, aggregator: bool = False) -> str:
    zone, pos, frac = risk_position(score, status, aggregator)
    cells = "".join(f'<i class="z{i}"></i>' for i in range(4))
    return (f'<div class="risk z{zone}" style="--pos:{pos}%"><span class="end">0</span><span class="gauge" role="img" '
            f'aria-label="Scam risk {int(pos)} of 100">{cells}<b></b></span><span class="end">100</span>'
            f'<span class="rl">{int(pos)}</span></div>')


# ---------- static script ----------

APP_JS_VERSION = "1"
FX_JS_VERSION = "1"
