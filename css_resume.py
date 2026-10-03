"""Styles for the Resume studio redesign (optimizer landing, ATS report, suggestion cards, tailor flow).

ui.py appends CSS to its stylesheet. Everything here uses the site's own variables (ui.CSS :root), so dark mode
follows for free. Class names all start with rs-.
"""

CSS = """
/* ---------- Resume studio: optimizer ---------- */
.rs-tabs{margin-bottom:22px}
.rs-h1{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:clamp(26px,3.2vw,36px);line-height:1.1;letter-spacing:-.01em;margin:0 0 12px;color:var(--ink)}
.rs-lede{font-size:16px;color:var(--muted);max-width:52ch;margin:0 0 18px}
.rs-checks{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rs-checks li{display:grid;grid-template-columns:26px minmax(0,1fr);gap:10px;align-items:start;font-size:16px;color:var(--ink)}
.rs-checks .tick{width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--canvas);display:grid;place-items:center}
.rs-checks .tick svg{width:14px;height:14px}
.rs-add{padding:28px 26px 22px;box-shadow:var(--shadow);border-radius:16px}
.rs-add h2{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:28px;text-align:center;margin:0 0 6px}
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
.rs-score h2{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:22px;margin:0}
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
.rs-job h2{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:22px;margin:2px 0 2px}
.rs-cover{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:16px}
.rs-cover h4{font-size:13px;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}
.rs-note{font-size:13px;color:var(--muted);margin:10px 0 0}

/* ---------- steps: 1 Choose resume, 2 Scan, 3 Review changes ---------- */
.rs-steps{list-style:none;margin:0 0 22px;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;counter-reset:none}
.rs-steps li{position:relative;border-top:3px solid var(--line-2);padding:10px 2px 0;font-size:14px;color:var(--faint);font-weight:600}
.rs-steps li>a,.rs-steps li>span{display:flex}
.rs-steps li a{display:flex;align-items:center;gap:10px;color:inherit;text-decoration:none}
.rs-steps li:not(:has(a)){display:flex;align-items:center;gap:10px}
.rs-steps .n{flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:700;background:var(--sunk);color:var(--muted);border:1px solid var(--line-2)}
.rs-steps .n svg{width:14px;height:14px}
.rs-steps li.on{border-top-color:var(--accent-ink);color:var(--ink)}
.rs-steps li.on .n{background:var(--accent-ink);color:var(--canvas);border-color:var(--accent-ink)}
.rs-steps li.done{border-top-color:color-mix(in srgb,var(--accent-ink) 45%,var(--line-2));color:var(--muted)}
.rs-steps li.done .n{background:var(--accent-tint);color:var(--accent-ink);border-color:transparent}
.rs-steps li a:hover .t{text-decoration:underline}
.rs-start{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:36px;align-items:start;padding:4px 0 26px}

/* ---------- step 2: the resume line by line, notes in the margin ---------- */
.rs-next{display:block;width:100%;margin-top:14px;text-align:center}
.rs-sheet .rs-lines{margin-top:10px;background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:14px 0}
.rs-ln{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:0 18px;align-items:start;padding:0 16px}
.rs-ln.sp{min-height:10px}
.rs-txt{font-size:14px;line-height:1.5;padding:3px 8px;border-radius:6px;color:var(--ink-2);overflow-wrap:anywhere}
.rs-ln.lh .rs-txt{font-weight:700;letter-spacing:.06em;text-transform:uppercase;font-size:12.5px;color:var(--ink);padding-top:8px}
.rs-ln.ln .rs-txt{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:20px;color:var(--ink)}
.rs-ln.lb .rs-txt{padding-left:18px;text-indent:-10px}
.rs-ln.hl .rs-txt{background:var(--gold-tint);box-shadow:inset 3px 0 0 var(--gold,#c9a227);color:var(--ink)}
.rs-margin{border-left:1px dashed var(--line-2);padding:0 0 0 14px;min-height:100%}
.rs-margin .rs-card{margin:4px 0 10px;box-shadow:var(--shadow)}
.rs-margin:empty{border-left-color:transparent}
.rs-sect{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:3px}
.rs-anchor{display:block;position:relative;top:-80px;height:0}

/* ---------- the new resume: preview + panel ---------- */
.rs-jtabs{margin:6px 0 18px}
.rs-gen-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px}
.rs-t1{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:clamp(24px,3vw,32px);line-height:1.12;margin:0 0 4px;color:var(--ink)}
.rs-gen{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px;align-items:start}
.rs-gen.one{grid-template-columns:minmax(0,1fr) 360px}
.rs-paper{background:var(--sunk);border:1px solid var(--whisper);border-radius:14px;padding:22px}
.rs-legend{font-size:12.5px;color:var(--faint);margin:12px 4px 0}
.rs-legend .rs-chg{background:#fff4c7;color:#3d3d3a;padding:0 4px;border-radius:3px}
.rs-panel{display:grid;gap:14px;position:sticky;top:76px}
.rs-panel h3{margin:0 0 8px;font-size:16px}
.rs-panel h3 small{font-weight:500;color:var(--faint);font-size:12.5px;margin-left:6px}
.rs-mm{display:flex;align-items:center;gap:14px;margin:8px 0 10px}
.rs-mm div{display:grid}
.rs-mm .lbl{font-size:12px;color:var(--muted)}
.rs-mm b{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-size:34px;line-height:1;font-variant-numeric:tabular-nums;color:var(--muted)}
.rs-mm .new b{color:var(--ok,#2f7a4a)}
.rs-mm .arr{font-size:22px;color:var(--faint)}
.rs-match .meter{margin:6px 0}
.rs-dl{display:grid;gap:10px}
.rs-dl h3{margin:0}
.rs-dlrow{display:flex;gap:8px;flex-wrap:wrap}
.rs-dl .rs-save{margin:0}.rs-dl .rs-save .b,.rs-dl>.b{width:100%;justify-content:center;text-align:center}
.rs-changes ol{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.rs-ch{border:1px solid var(--whisper);border-radius:10px;padding:10px 12px;background:var(--canvas)}
.rs-ch.off{opacity:.72}
.rs-ch.off .rs-diff .now{text-decoration:line-through;text-decoration-color:var(--faint)}
.rs-cht{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.rs-cht b{font-size:14px;line-height:1.35}
.rs-cht .pill{margin-left:0;flex:none}
.rs-ch .why{font-size:12.5px;color:var(--muted);margin:4px 0 0}
.rs-ch .rs-diff div{font-size:13px}
.rs-ch .rs-actions{margin-top:8px}
.rs-kept{display:inline-flex;align-items:center;gap:4px;font-size:12.5px;font-weight:600;color:var(--ok,#2f7a4a)}
.rs-kept.off{color:var(--faint)}
.rs-gaps .reasons li{font-size:13.5px}
.rs-need{max-width:640px}
.rs-need h2{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:84%;font-weight:650;font-size:24px;margin:0 0 6px}
.rs-aibox p{margin:0 0 8px}
.rs-tpick .b{margin-top:2px}
.rs-draft textarea.resume{min-height:520px}
.rs-notecard textarea{min-height:260px;width:100%;margin:6px 0 10px}
.rs-notecard label{font-weight:600}
.rs-cn{white-space:pre-wrap;font-size:14px;background:var(--canvas);border:1px solid var(--whisper);border-radius:10px;padding:12px 14px;margin:0 0 10px}
.rs-tips{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rs-tipc{display:grid;grid-template-columns:34px minmax(0,1fr);gap:12px;background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:16px 18px}
.rs-tipc .n{width:30px;height:30px;border-radius:50%;background:var(--accent-tint);color:var(--accent-ink);display:grid;place-items:center;font-weight:700}
.rs-tipc b{font-size:15.5px}
.rs-tipc p{margin:4px 0 0;color:var(--muted);font-size:14px}

/* The resume itself: always a white page, in light and dark, like the PDF. */
.rs-doc{--d-ink:#1b1b1a;--d-muted:#4a4a46;--d-rule:#b9b6ac;background:#fff;color:var(--d-ink);max-width:816px;margin:0 auto;padding:48px 54px 56px;
  border-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,.08),0 8px 28px rgba(0,0,0,.12);font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;font-size:13.5px;line-height:1.42}
.rs-dhd{text-align:center;margin-bottom:6px}
.rs-doc h1{font-size:27px;font-weight:700;margin:0 0 4px;letter-spacing:.01em;color:var(--d-ink);font-family:inherit}
.rs-dc{margin:0;color:var(--d-muted);font-size:12.5px;display:flex;flex-wrap:wrap;justify-content:center;gap:0 2px}
.rs-dc i{font-style:normal;color:#9a978f}
.rs-doc section{margin-top:14px}
.rs-doc h2{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--d-rule);padding-bottom:3px;margin:0 0 6px;color:var(--d-ink);font-family:inherit}
.rs-doc p{margin:0 0 3px}
.rs-dsk b{font-weight:700}
.rs-de{margin:0 0 8px}
.rs-dh{display:flex;justify-content:space-between;gap:14px;align-items:baseline}
.rs-dh span{flex:none;color:var(--d-muted);font-size:12.5px;white-space:nowrap}
.rs-dsub{color:var(--d-muted)}
.rs-doc ul{margin:3px 0 0 18px;padding:0}
.rs-doc li{margin:0 0 2px;padding-left:2px}
.rs-doc li.rs-chg{background:#fff4c7;border-radius:3px;box-shadow:-4px 0 0 #fff4c7,4px 0 0 #fff4c7}

@media (max-width:1000px){.rs-gen,.rs-gen.one{grid-template-columns:minmax(0,1fr)}.rs-panel{position:static}}
@media (max-width:700px){.rs-ln{grid-template-columns:minmax(0,1fr)}.rs-margin{border-left:0;padding:0 0 0 12px}
  .rs-paper{padding:8px;border-radius:10px}.rs-doc{padding:24px 18px 28px;font-size:13px}.rs-dh{flex-wrap:wrap}.rs-steps .t{font-size:12.5px}
  .rs-start{grid-template-columns:minmax(0,1fr);gap:20px}}

/* Ctrl+P on a page with a resume prints just the resume. */
@media print{
  @page{size:letter;margin:.5in}
  body:has(.rs-doc){background:#fff!important}
  body:has(.rs-doc) *:not(.rs-doc,.rs-doc *,:has(.rs-doc)){display:none!important}
  body:has(.rs-doc) :has(.rs-doc){display:block!important;margin:0!important;padding:0!important;border:0!important;background:none!important;box-shadow:none!important;max-width:none!important;width:auto!important;position:static!important}
  .rs-doc{box-shadow:none!important;border-radius:0;padding:0!important;max-width:none;font-size:10.5pt}
  .rs-doc li.rs-chg{background:none;box-shadow:none}
}

@media (max-width:900px){
  .rs-report{grid-template-columns:minmax(0,1fr)}
  .rs-side{position:static}
  .rs-tools,.rs-stand,.rs-cover{grid-template-columns:minmax(0,1fr)}
  .rs-pick{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:520px){.rs-add{padding:22px 16px 18px}.rs-job{grid-template-columns:minmax(0,1fr)}}
"""
