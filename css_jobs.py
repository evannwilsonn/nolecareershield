"""Styles for the jobs pages (appended to ui.CSS): the two-pane job board (jobboard.py) and the demo's twin of it."""
CSS = """
/* ---------- job board ---------- */
.jb{padding-top:6px;min-width:0}
.jb-one{max-width:820px}
.jb-tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:14px 0 14px;overflow-x:auto;scrollbar-width:none}
.jb-tabs::-webkit-scrollbar{display:none}
.jb-tabs a{padding:10px 14px;text-decoration:none;color:var(--muted);font-weight:600;font-size:14.5px;white-space:nowrap;border-bottom:2px solid transparent;margin-bottom:-1px}
.jb-tabs a:hover{color:var(--ink)}
.jb-tabs a.on{color:var(--accent-ink);border-bottom-color:var(--accent-ink)}
.jb-controls{margin-bottom:14px}
.jb-search{display:flex;gap:8px;margin-bottom:10px}
.jb-search input{flex:1;min-width:0;border-radius:999px;padding:11px 18px;font-size:15px}
.jb-search button{background:var(--accent);color:var(--on-accent);border:none;border-radius:999px;padding:0 22px;font:600 14px var(--sans);cursor:pointer}
.jb-search button:hover{background:var(--accent-hover)}
.jb-chips{display:flex;flex-wrap:wrap;gap:7px;align-items:center;position:relative}
.jb-chip{display:inline-flex;align-items:center;gap:6px;background:var(--surface);color:var(--ink-2);padding:6px 13px;border-radius:999px;font-size:13.5px;font-weight:550;text-decoration:none;
  box-shadow:0 0 0 1px var(--line-2) inset;cursor:pointer;list-style:none;white-space:nowrap}
.jb-chip::-webkit-details-marker{display:none}
.jb-chip:hover{box-shadow:0 0 0 1px var(--accent-ink) inset}
.jb-chip.on{background:var(--accent-tint);color:var(--accent-ink);box-shadow:0 0 0 1px var(--accent-ink) inset}
.jb-chip .car{width:6px;height:6px;border-right:1.6px solid currentColor;border-bottom:1.6px solid currentColor;transform:rotate(45deg) translateY(-2px);margin-left:2px}
.jb-dd{position:relative}
.jb-dd[open]>.jb-chip{box-shadow:0 0 0 1px var(--accent-ink) inset}
.jb-menu{position:absolute;z-index:15;top:calc(100% + 6px);left:0;min-width:210px;max-width:min(320px,calc(100vw - 32px));max-height:min(60vh,380px);overflow:auto;background:var(--surface);
  border:1px solid var(--line-2);border-radius:12px;box-shadow:var(--shadow-deep);padding:6px;display:grid}
.jb-dd.wide .jb-menu{min-width:250px;left:auto;right:0}
.jb-menu a{padding:8px 11px;border-radius:8px;text-decoration:none;font-size:14px;color:var(--ink-2)}
.jb-menu a:hover{background:var(--sunk)}
.jb-menu a.on{background:var(--accent-tint);color:var(--accent-ink);font-weight:600}
.jb-clear{font-size:13.5px;color:var(--accent-ink);font-weight:600;text-decoration:none;padding:6px 6px}
.jb-count{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13px;color:var(--faint);margin:2px 2px 10px;flex-wrap:wrap}
.jb-dd.sort .jb-chip{font-size:13px;padding:4px 11px}
.jb-dd.sort .jb-menu{left:auto;right:0}
.jb-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:start}
.jb-pane{display:none}
.jc{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:14px 14px 13px;margin-bottom:10px;transition:box-shadow .2s,border-color .2s}
.jc:hover{border-color:var(--line-2);box-shadow:var(--shadow)}
.jc.sel{border-color:var(--accent-ink);box-shadow:0 0 0 1px var(--accent-ink) inset}
.jc-logo{width:44px;height:44px;border-radius:10px;background:var(--gold-tint);color:var(--gold-ink);display:grid;place-items:center;font:700 15px var(--display);flex:none;box-shadow:0 0 0 1px var(--whisper) inset}
.jc-logo.lg{width:56px;height:56px;border-radius:12px;font-size:19px}
.jc-body{min-width:0}
.jc-title{font:650 16.5px/1.25 var(--display);font-stretch:88%;letter-spacing:-.005em;overflow-wrap:anywhere}
.jc-link{color:var(--ink);text-decoration:none}
.jc-link::after{content:"";position:absolute;inset:0;border-radius:12px}
.jc-link:focus-visible{outline:none}
.jc-link:focus-visible::after{outline:2px solid var(--accent-ink);outline-offset:2px}
.jc-m{display:inline}.jc-d{display:none}
.jc-co{color:var(--ink-2);font-size:14px;margin-top:2px}
.jc-facts{color:var(--muted);font-size:13px;margin-top:2px}
.jc-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px;align-items:center}
.jc-tags .rev-score{font-size:11.5px;padding:2px 9px}
.jc-match{font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;background:var(--sunk);color:var(--muted);box-shadow:0 0 0 1px var(--whisper) inset;font-variant-numeric:tabular-nums}
.jc-match.high{background:var(--ok-tint);color:var(--ok);box-shadow:none}
.jc-match.medium{background:var(--gold-tint);color:var(--gold-ink);box-shadow:none}
.jc-tag{font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--sunk);color:var(--muted)}
.jc-tag.q{background:var(--accent-tint);color:var(--accent-ink)}
.jc-tag.n{background:var(--info-tint);color:var(--info)}
.jc-sv{position:relative;z-index:2;align-self:start}
.sv-i,.sv-l{background:none;border:none;color:var(--muted);cursor:pointer;font:600 14px var(--sans);display:inline-flex;align-items:center;gap:6px}
.sv-i{padding:6px;border-radius:8px}
.sv-i:hover,.sv-l:hover{color:var(--accent-ink)}
.sv-i.on,.sv-l.on{color:var(--accent-ink)}
.sv-l{padding:10px 14px;border-radius:8px;box-shadow:0 0 0 1px var(--line-2) inset}
.sv-l.on{background:var(--accent-tint);box-shadow:0 0 0 1px var(--accent-ink) inset}
/* detail */
.jd{min-width:0}
.jd-back{margin-top:10px}
.jd-head{display:flex;gap:14px;align-items:flex-start;margin-bottom:14px}
.jd-h{min-width:0}
.jd-title{font:650 clamp(21px,3vw,27px)/1.15 var(--display);font-stretch:84%;letter-spacing:-.01em;overflow-wrap:anywhere}
.jd-co{font-size:15.5px;margin-top:3px;color:var(--ink-2)}
.jd-co a{color:var(--accent-ink);font-weight:600;text-decoration:none}
.jd-co a:hover{text-decoration:underline}
.jd-sub{color:var(--muted);font-size:13.5px;margin-top:3px}
.jd-trust{margin-top:8px}
.jd-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px}
.jd-acts .apply-btn{padding:10px 20px}
.jd-acts .navform{margin:0}
.jd-empty{padding:40px 16px;color:var(--muted);text-align:center;background:var(--surface);border:1px dashed var(--line-2);border-radius:12px}
.jd section{background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:16px 18px;margin-bottom:12px}
.jd section h3{font:650 16px var(--display);font-stretch:88%;margin-bottom:8px;letter-spacing:-.003em}
.js-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px}
.js-top h3{margin:0!important}
.js .risk{margin:4px 0 12px}
.js .banner{margin-bottom:0}
.jd-find{margin-top:12px}
.jm-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.jm-head h3{margin:0!important}
.jm-lvl{font-weight:750}.jm-lvl.high{color:var(--ok)}.jm-lvl.medium{color:var(--gold-ink)}.jm-lvl.low{color:var(--muted)}
.jm-pct{font:750 26px var(--display);font-stretch:80%;font-variant-numeric:tabular-nums}
.jm-meter{position:relative;display:grid;grid-template-columns:2fr 1fr 1fr;gap:3px;height:8px;margin:12px 4px 6px}
.jm-meter i{background:var(--sand);border-radius:2px}.jm-meter i:first-child{border-radius:999px 2px 2px 999px}.jm-meter i:nth-child(3){border-radius:2px 999px 999px 2px}
.jm-meter.low i:nth-child(1){background:var(--faint)}.jm-meter.medium i:nth-child(-n+2){background:var(--gold)}.jm-meter.high i{background:var(--ok)}
.jm-meter b{position:absolute;top:50%;left:var(--pos);width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:var(--surface);border:3px solid var(--ink);box-shadow:0 1px 4px rgba(20,20,19,.28)}
.jm-meter.high b{border-color:var(--ok)}.jm-meter.medium b{border-color:var(--gold-ink)}.jm-meter.low b{border-color:var(--muted)}
.jm-scale{display:grid;grid-template-columns:2fr 1fr 1fr;font-size:11px;color:var(--faint);margin:0 4px}
.jm-scale span:nth-child(2){padding-left:2px}.jm-scale span:nth-child(3){text-align:right}
.jm-conf{font-size:13px;color:var(--muted);margin:10px 0 4px}
.jm-more{margin-top:8px}
.jm-more summary{cursor:pointer;color:var(--accent-ink);font-weight:600;font-size:14px;padding:4px 0}
.jm-found{list-style:none;padding:0;display:grid;gap:5px;font-size:13.5px}
.jm-found .ev{display:block;font-size:12.5px;color:var(--muted)}
.jm-acts{margin-top:12px}
.jq-sum{font-size:14.5px;margin-bottom:10px}
.jq-list{list-style:none;padding:0;display:grid;gap:9px}
.jq-list li{display:grid;grid-template-columns:24px minmax(0,1fr);gap:9px;font-size:14.5px;align-items:start}
.jq-list .mk{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--sand);color:var(--muted)}
.jq-list .met .mk{background:var(--ok-tint);color:var(--ok)}.jq-list .missing .mk{background:var(--warn-tint);color:var(--warn)}
.jq-list .plain .mk{background:none;color:var(--faint)}
.rq{font-style:normal;font-size:11.5px;font-weight:600;margin-left:8px;padding:1px 8px;border-radius:999px;background:var(--sunk);color:var(--muted);white-space:nowrap}
.rq.required{background:var(--accent-tint);color:var(--accent-ink)}
.jq-note{font-size:12.5px;color:var(--muted);margin-top:12px}
.jq-note a{color:var(--accent-ink);font-weight:600}
.jg dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px 18px}
.jg dt{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);font-weight:600}
.jg dd{font-size:14.5px;margin-top:2px}
.jd-desc .detail-desc{margin:0;max-width:none}
@media(min-width:961px){
  .jb-grid{grid-template-columns:minmax(300px,390px) minmax(0,1fr);gap:20px}
  .jb-list{max-height:max(520px,calc(100vh - 300px));overflow:auto;padding:2px 6px 2px 2px;margin:-2px -6px -2px -2px;scrollbar-width:thin}
  .jb-pane{display:block;max-height:max(520px,calc(100vh - 300px));overflow:auto;padding:2px 4px 2px 2px;scrollbar-width:thin}
  .jc-m{display:none}.jc-d{display:inline}
}
@media(max-width:700px){
  .jb-chips{position:static}.jb-controls{position:relative}
  .jb-dd{position:static}
  .jb-menu{left:0;right:0;max-width:none;top:auto;margin-top:6px}
  .jb-dd.sort{position:relative}.jb-dd.sort .jb-menu{position:absolute;left:auto;right:0;max-width:calc(100vw - 32px)}
  .jd-head{gap:11px}.jc-logo.lg{width:46px;height:46px}
}
"""
