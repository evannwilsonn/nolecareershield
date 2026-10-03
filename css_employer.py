"""Styles for the employer dashboard and the company page's Page stats card (employer_dash.py).
Appended to ui.CSS when this module is imported, so the shared stylesheet in ui.py stays untouched.
Colours come from the site's variables, so dark mode follows the rest of the site."""

import ui

CSS = """
/* ---------- employer dashboard (employer_dash.py) ---------- */
.ed-hello{display:flex;align-items:flex-end;justify-content:space-between;gap:16px 24px;flex-wrap:wrap;padding:6px 0 18px;margin:0 0 18px;border-bottom:1px solid var(--line)}
.ed-hi{min-width:0}
.ed-hi h1{font-family:var(--display);font-variation-settings:var(--dx);font-weight:800;font-stretch:72%;text-transform:uppercase;font-size:clamp(28px,3.4vw,42px);line-height:.95;margin:8px 0 6px;letter-spacing:-.005em;overflow-wrap:anywhere}
.ed-hi h1 em{font-style:normal;color:var(--accent-ink)}
.ed-hi p{color:var(--muted);font-size:14.5px;margin:0}
.ed-quick{display:flex;gap:8px;flex-wrap:wrap}
.ed-quick .b{display:inline-flex;align-items:center;gap:6px}
.ed-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:14px;align-items:start}
.ed-grid>.card{margin:0}
.ed-list,.ed-events{grid-column:1/-1}
.ed-grid .phead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
.ed-grid .phead h2{font-size:17px;margin:0}
.ed-badge{background:var(--accent);color:var(--on-accent);font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;font-variant-numeric:tabular-nums}
.ed-all{color:var(--accent-ink);font-weight:600;text-decoration:none}
.ed-all:hover{text-decoration:underline}
.ed-acts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.ed-act a{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;
  background:var(--sunk);box-shadow:0 0 0 1px var(--whisper) inset;color:var(--ink);text-decoration:none;font-size:14.5px;line-height:1.35;transition:box-shadow .15s,background .15s}
.ed-act a:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;background:var(--surface)}
.ed-ic{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:var(--surface);color:var(--muted);box-shadow:0 0 0 1px var(--whisper) inset}
.ed-act.hot .ed-ic{background:var(--accent-tint);color:var(--accent-ink)}
.ed-act.warn .ed-ic{background:var(--gold-tint);color:var(--gold-ink)}
.ed-act.hot a{border-left:3px solid var(--accent)}
.ed-act.warn a{border-left:3px solid var(--gold)}
.ed-t{min-width:0;overflow-wrap:anywhere}
.ed-go{font-size:13px;font-weight:600;color:var(--accent-ink);white-space:nowrap}
.ed-clear{display:flex;align-items:center;gap:8px;color:var(--muted);margin:0;padding:12px;border-radius:10px;background:var(--sunk)}
.ed-clear .ic{color:var(--ok, #2e7d4f)}
.ed-pipe .pipe{margin:0 0 10px}
.ed-pipe .pstep{flex:1 1 30%}
.ed-rows{display:flex;flex-direction:column}
.ed-row{display:grid;grid-template-columns:minmax(0,2.3fr) repeat(4,minmax(64px,.7fr)) minmax(0,1.2fr);align-items:center;gap:10px 14px;padding:12px 2px;border-top:1px solid var(--line)}
.ed-row:first-child{border-top:0;padding-top:4px}
.ed-ti{display:flex;align-items:center;gap:6px 8px;flex-wrap:wrap;min-width:0}
.ed-name{font-weight:650;color:var(--ink);text-decoration:none;overflow-wrap:anywhere;margin-right:2px}
.ed-name:hover{color:var(--accent-ink);text-decoration:underline}
.ed-m{display:flex;flex-direction:column;min-width:0}
.ed-m b{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:80%;font-weight:650;font-size:22px;line-height:1.05;font-variant-numeric:tabular-nums}
.ed-m span{font-size:11.5px;color:var(--muted);font-weight:600}
.ed-ac{text-align:right}
.ed-pv{font-size:13px;font-weight:600;color:var(--accent-ink);text-decoration:none;white-space:nowrap}
.ed-pv:hover{text-decoration:underline}
.ed-ev{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.ed-ev li{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:8px 10px;border-radius:8px;background:var(--sunk)}
.ed-ev span{color:var(--muted);font-size:13px}
@media(max-width:900px){.ed-grid{grid-template-columns:minmax(0,1fr)}
  .ed-row{grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 10px}
  .ed-ti,.ed-ac{grid-column:1/-1}.ed-ac{text-align:left}}
@media(max-width:620px){.ed-hello{padding-top:0}.ed-quick{width:100%}.ed-quick .b{flex:1 1 auto;justify-content:center}
  .ed-act a{grid-template-columns:auto minmax(0,1fr);gap:10px}.ed-go{grid-column:2}.ed-m b{font-size:19px}}

/* ---------- company page: Page stats (owner only) ---------- */
.pgrid.co .pside{position:static}
.ps .phead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap}
.ps-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.ps-c{background:var(--sunk);border-radius:12px;box-shadow:0 0 0 1px var(--whisper) inset;padding:12px 14px;display:flex;flex-direction:column;min-width:0}
.ps-c b{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:80%;font-weight:650;font-size:30px;line-height:1.05;color:var(--accent-ink);font-variant-numeric:tabular-nums}
.ps-c span{font-size:13px;font-weight:600}
.ps-c em{font-style:normal;font-size:12px;color:var(--muted);margin-top:2px}
.ps-h{font-size:14px;margin:16px 0 8px}
.ps-maj{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.ps-maj li{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,2fr) auto;align-items:center;gap:10px;font-size:13.5px}
.ps-m{overflow-wrap:anywhere}
.ps-bar{height:8px;border-radius:99px;background:var(--sunk);box-shadow:0 0 0 1px var(--whisper) inset;overflow:hidden}
.ps-bar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--gold));border-radius:inherit}
.ps-v{color:var(--muted);font-size:12.5px;white-space:nowrap}
@media(max-width:620px){.ps-grid{grid-template-columns:minmax(0,1fr)}.ps-maj li{grid-template-columns:minmax(0,1fr) auto}.ps-bar{grid-column:1/-1;grid-row:2}}
"""

if "/* ---------- employer dashboard (employer_dash.py)" not in ui.CSS:
    ui.CSS += CSS
