"""Styles for the Resume studio redesign (optimizer landing, ATS report, suggestion cards, tailor flow).

ui.py appends CSS to its stylesheet. Everything here uses the site's own variables (ui.CSS :root), so dark mode
follows for free. Class names all start with rs-.
"""

CSS = """
/* ---------- Resume studio: optimizer ---------- */
.rs-tabs{margin-bottom:22px}
.rs-hero{position:relative;isolation:isolate;display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);gap:44px;align-items:center;padding:14px 0 30px}
.rs-hero::before{content:"";position:absolute;inset:-20px -40px;z-index:-1;pointer-events:none;
  background:radial-gradient(520px circle at 85% 40%,var(--gold-tint),transparent 65%),radial-gradient(460px circle at 10% 10%,var(--accent-tint),transparent 60%);opacity:.75}
.rs-badge{width:54px;height:54px;border-radius:16px;background:var(--accent-tint);color:var(--accent-ink);display:grid;place-items:center;margin-bottom:18px}
.rs-badge svg{width:28px;height:28px}
.rs-h1{font-family:var(--display);font-stretch:84%;font-weight:650;font-size:clamp(32px,4.6vw,52px);line-height:1.05;letter-spacing:-.01em;margin:0 0 18px;color:var(--ink)}
.rs-lede{font-size:16px;color:var(--muted);max-width:52ch;margin:0 0 18px}
.rs-checks{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rs-checks li{display:grid;grid-template-columns:26px minmax(0,1fr);gap:10px;align-items:start;font-size:16px;color:var(--ink)}
.rs-checks .tick{width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--canvas);display:grid;place-items:center}
.rs-checks .tick svg{width:14px;height:14px}
.rs-add{padding:28px 26px 22px;box-shadow:var(--shadow);border-radius:16px}
.rs-add h2{font-family:var(--display);font-stretch:84%;font-weight:650;font-size:28px;text-align:center;margin:0 0 6px}
.rs-add .sub{text-align:center;color:var(--muted);font-size:15px;margin:0 0 18px}
.rs-add select{width:100%}
.rs-pickmeta{font-size:12.5px;color:var(--faint);margin:6px 2px 0}
.rs-go{display:block;width:100%;margin-top:14px;padding:15px 20px;font-size:16px;border-radius:10px}
.rs-add .or{margin:16px 0}
.rs-up{border:1px solid var(--line-2);border-radius:10px;background:var(--surface)}
.rs-up summary{list-style:none;cursor:pointer;text-align:center;padding:13px 16px;font-weight:600;font-size:15px;color:var(--ink);display:flex;gap:8px;align-items:center;justify-content:center}
.rs-up summary::-webkit-details-marker{display:none}
.rs-up summary:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;border-radius:10px}
.rs-up[open] summary{border-bottom:1px solid var(--line)}
.rs-up .inner{padding:14px 16px 16px;text-align:left}
.rs-fine{font-size:12px;color:var(--faint);text-align:center;margin:14px 0 0;line-height:1.5}
.rs-fine a{color:var(--accent-ink)}
.rs-tools{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:6px}
.rs-tool{display:block;text-decoration:none;color:inherit;padding:18px 18px 16px}
.rs-tool:hover{box-shadow:0 0 0 1px var(--accent-ink) inset}
.rs-tool .ic{color:var(--accent-ink)}
.rs-tool b{display:block;font-size:15px;margin:8px 0 4px}
.rs-tool span{font-size:13.5px;color:var(--muted)}

/* ---------- report ---------- */
.rs-back{display:inline-block;font-size:14px;color:var(--accent-ink);text-decoration:none;margin-bottom:12px;font-weight:600}
.rs-report{display:grid;grid-template-columns:300px minmax(0,1fr);gap:22px;align-items:start}
.rs-side{position:sticky;top:76px;display:grid;gap:14px}
.rs-score{text-align:center}
.rs-score .ring{width:132px;height:132px;margin:2px auto 12px}
.rs-score .ring b{width:106px;height:106px;font-size:38px}
.rs-score .ring b,.rs-job .ring b{display:flex;align-items:center;justify-content:center;gap:0}
.rs-score .ring b small,.rs-job .ring b small{margin-top:.35em;font-size:16px;font-weight:600;margin-left:1px}
.rs-score h2{font-family:var(--display);font-stretch:84%;font-weight:650;font-size:22px;margin:0}
.rs-score p{font-size:13px;color:var(--muted);margin:4px 0 0}
.rs-nav{display:grid;gap:4px;margin-top:16px;text-align:left}
.rs-nav a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;align-items:center;padding:8px 10px;border-radius:8px;text-decoration:none;color:var(--ink);font-size:14px;font-weight:600}
.rs-nav a:hover{background:var(--sunk)}
.rs-nav a .meter{grid-column:1 / -1}
.rs-nav a .pc{font-variant-numeric:tabular-nums;color:var(--muted);font-weight:600}
.rs-nav a .open{font-weight:500;font-size:12px;color:var(--faint);grid-column:1 / -1}
.rs-main>section{margin-bottom:26px}
.rs-sech{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 4px}
.rs-sech h3{margin:0;font-size:18px}
.rs-sech .pill{margin-left:0}
.rs-clear{border:1px dashed var(--line-2);border-radius:12px;padding:14px 16px;color:var(--muted);font-size:14px;background:var(--surface)}
.rs-card{border:1px solid var(--whisper);background:var(--surface);border-radius:12px;padding:14px 16px;margin-top:10px}
.rs-card.tip{background:var(--canvas)}
.rs-card h4{margin:0;font-size:15px;font-weight:600;line-height:1.35}
.rs-card .why{font-size:13px;color:var(--muted);margin-top:4px}
.rs-diff{margin-top:10px;display:grid;gap:6px}
.rs-diff div{font-size:14px;padding:8px 10px;border-radius:8px;line-height:1.45}
.rs-diff .was{background:var(--bad-tint);color:var(--ink-2);text-decoration:line-through;text-decoration-color:var(--faint)}
.rs-diff .now{background:var(--ok-tint);color:var(--ink)}
.rs-diff .lbl{display:block;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-decoration:none;margin-bottom:2px}
.rs-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
.rs-actions form{display:inline;margin:0}
.rs-actions .small{color:var(--faint)}
.rs-approve{display:flex;gap:10px;align-items:flex-start;border-radius:10px;padding:11px 14px;background:var(--accent-tint);color:var(--accent-ink);font-size:14px;margin:0 0 18px}
.rs-approve svg{flex:none;margin-top:2px}
.rs-dis{font-size:13px;color:var(--faint);margin-top:8px}
.rs-dis a{color:var(--accent-ink)}
.rs-stand{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
.rs-stand .rs-card{margin-top:0}
.rs-stand .ic{color:var(--accent-ink)}
.rs-pick{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end}

/* ---------- tailor to a job ---------- */
.rs-job{display:grid;grid-template-columns:auto minmax(0,1fr);gap:18px;align-items:center}
.rs-job .ring{width:104px;height:104px}.rs-job .ring b{width:82px;height:82px;font-size:30px}
.rs-job h2{font-family:var(--display);font-stretch:84%;font-weight:650;font-size:22px;margin:2px 0 2px}
.rs-cover{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:16px}
.rs-cover h4{font-size:13px;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}
.rs-note{font-size:13px;color:var(--muted);margin:10px 0 0}

@media (max-width:900px){
  .rs-hero{grid-template-columns:minmax(0,1fr);gap:26px}
  .rs-report{grid-template-columns:minmax(0,1fr)}
  .rs-side{position:static}
  .rs-tools,.rs-stand,.rs-cover{grid-template-columns:minmax(0,1fr)}
  .rs-pick{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:520px){.rs-add{padding:22px 16px 18px}.rs-job{grid-template-columns:minmax(0,1fr)}}
"""
