"""Styles for the applicant table and listing controls (hiring.py). Importing this module appends CSS to ui.CSS,
the same way css_feed and css_assist do, so ui.py is untouched. Colours come from the site's variables, so dark
mode follows the rest of the site. At 760px and below the table turns into stacked cards (no sideways scrolling)."""

import ui

CSS = """
/* ---------- hiring: listing controls ---------- */
.hjob2{margin-bottom:10px}
.hjob2 .hj-main{text-decoration:none;color:inherit;min-width:0;display:block}
.hjob2 .hj-main:hover .job-title{color:var(--accent-ink)}
.hjob2 .hj-stats{display:block;text-decoration:none;color:inherit}
.hj-state{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex:none}
.hj-when{font-size:12px;color:var(--muted);white-space:nowrap}
.hjob2.st-paused,.hjob2.st-closed,.hjob2.st-expired{background:var(--sunk)}
.hjob2.st-closed .job-title,.hjob2.st-closed .job-co{color:var(--muted)}
@media(max-width:620px){.hjob2>.row{flex-direction:column;align-items:flex-start;gap:8px}.hj-state{flex-direction:row;align-items:center;flex-wrap:wrap;gap:8px}}
.lc-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;padding-top:12px;border-top:1px solid var(--whisper)}
.lc{margin:14px 0 4px;padding:14px 16px}
.lc-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
.lc .lc-row{margin-top:10px;padding-top:0;border-top:none}
.lc-exp{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--whisper);font-size:13.5px}
.lc-exp label{font-weight:600;color:var(--ink-2)}
.lc-exp select,.lc-exp input[type=date]{width:auto;min-width:0;padding:6px 10px;font-size:13.5px}
.lc-or{color:var(--muted)}
.appnote{margin-top:6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted)}

/* ---------- hiring: applicant table ---------- */
.at-filters{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px 12px;align-items:end;padding:14px 16px;margin:4px 0 14px}
.at-filters .form-field{margin:0;min-width:0}
.at-filters label{font-size:12.5px}
.at-filters select{width:100%;padding:7px 9px;font-size:13.5px}
.at-filters .at-req{grid-column:span 3;margin:0;align-items:center;font-size:13.5px}
.at-fbtn{grid-column:span 3;display:flex;gap:8px;justify-content:flex-end}
.at-bulk{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 10px;padding:10px 14px;border-radius:12px;
  background:var(--gold-tint);color:var(--gold-ink)}
.at-bulk .at-count{font-size:13.5px}
.at-bact{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13.5px}
.at-bact label{font-weight:600}
.at-bact select{width:auto;padding:6px 9px;font-size:13.5px}
.at-wrap{border-radius:14px;box-shadow:0 0 0 1px var(--whisper) inset;background:var(--surface);overflow-x:auto}
.at{width:100%;border-collapse:collapse;font-size:13.5px}
.at th{text-align:left;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:10px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
.at td{padding:10px 8px;border-bottom:1px solid var(--whisper);vertical-align:top}
.at tbody tr:last-child td{border-bottom:none}
.at tbody tr:hover{background:color-mix(in srgb,var(--gold-tint) 45%,transparent)}
.at tbody tr:target{box-shadow:inset 3px 0 0 var(--accent)}
.at .at-sel{width:28px;padding-right:0}
.at .at-sel input{width:17px;height:17px;accent-color:var(--accent);margin-top:10px}
.at .person .nm{font-size:14px}
.at .person .sub{font-size:12px}
.at .avatar{width:32px;height:32px;font-size:13px}
.at-stu{min-width:150px}
.at-lst{min-width:120px}
.at-src{display:block;margin-top:5px}.at-src .pill{font-size:11px;padding:2px 8px}
.at-job{color:var(--ink);font-weight:600;text-decoration:none}
.at-job:hover{color:var(--accent-ink);text-decoration:underline}
.at-st{display:inline-block;font-size:11px;font-weight:600;color:var(--muted);background:var(--sunk);border-radius:999px;padding:1px 7px;margin-top:3px}
.at select{width:auto;max-width:132px;padding:5px 6px;font-size:13px}
.at-pct{display:inline-block;font-weight:700;font-variant-numeric:tabular-nums;padding:2px 8px;border-radius:999px;background:var(--sand);color:var(--ink-2)}
.at-pct.hi{background:var(--ok-tint);color:var(--ok)}
.at-pct.mid{background:var(--gold-tint);color:var(--gold-ink)}
.rqs.short{margin-top:0;font-size:13px}
.rqs.short summary{font-weight:500;white-space:nowrap}
.rqs.short{position:relative}
.rqs.short ul{position:absolute;z-index:6;right:-8px;top:calc(100% + 6px);width:250px;background:var(--surface);border-radius:12px;padding:10px 12px;
  box-shadow:0 0 0 1px var(--line-2),0 12px 28px rgba(20,20,19,.16);margin:0}
.at-all{display:block;font-size:11.5px;color:var(--ok);font-weight:600;margin-top:4px;white-space:nowrap}
.at-date{display:block;white-space:nowrap}
.at-how{display:block;font-size:11.5px;color:var(--faint)}
.at-pv{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;min-width:170px}
.at-pv input{grid-column:1/-1;grid-row:2;width:100%;min-width:0;box-sizing:border-box}
.at-pv button{grid-row:1;grid-column:2}
@media(min-width:1180px){.at-wrap{overflow:visible}}
.at-pv input{padding:5px 8px;font-size:13px;min-width:0}
.at-stars{color:var(--gold-ink);letter-spacing:1px}
.at-pages{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:14px 0 6px}
.at-tip{margin-top:10px}
@media(max-width:1100px){.at-filters{grid-template-columns:repeat(3,minmax(0,1fr))}.at-filters .at-req,.at-fbtn{grid-column:span 3}
  .at-fbtn{justify-content:flex-start}}
@media(max-width:760px){
  .at-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.at-filters .at-req,.at-fbtn{grid-column:1/-1}
  .at-wrap{background:none;box-shadow:none;overflow:visible}
  .at,.at tbody,.at tr,.at td{display:block;width:auto}
  .at thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
  .at tbody tr{position:relative;background:var(--surface);border-radius:14px;box-shadow:0 0 0 1px var(--whisper) inset;padding:12px 14px 12px 44px;margin-bottom:10px}
  .at tbody tr:hover{background:var(--surface)}
  .at td{border:none;padding:4px 0;display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center}
  .at td::before{content:attr(data-l);flex:0 0 92px;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
  .at td>details{flex:1;min-width:0}.at-how{display:none}.at-lst .at-job{flex:0 1 auto}
  .at td.at-sel{position:absolute;left:14px;top:14px;padding:0;display:block}.at td.at-sel::before{display:none}.at .at-sel input{margin:0}
  .at td.at-stu{display:block;padding-bottom:8px;margin-bottom:4px;border-bottom:1px solid var(--whisper)}.at td.at-stu::before{display:none}
  .at-stu{min-width:0}
  .at td.at-priv{display:block;padding-top:8px}.at td.at-priv::before{display:block;margin-bottom:6px}
  .at-pv{min-width:0;grid-template-columns:auto minmax(0,1fr) auto}.at-pv input{grid-column:2;grid-row:1}.at-pv button{grid-column:3}
  .rqs.short ul{position:static;width:auto;box-shadow:none;padding:0;background:none;margin-top:8px}
  .at-src{display:inline-block;margin:0 0 0 6px}
  .at select{max-width:100%}
  .at-bulk{align-items:flex-start}
}
@media(max-width:420px){.at-pv{grid-template-columns:minmax(0,1fr) auto}.at-pv input{grid-column:1/-1;grid-row:1}.at-pv button{grid-column:2;grid-row:2}}
"""

if "/* ---------- hiring: applicant table" not in ui.CSS:
    ui.CSS += CSS
