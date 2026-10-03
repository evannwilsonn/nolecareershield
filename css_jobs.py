"""Styles for the jobs pages (appended to ui.CSS): the job board with its filter rail, the listing page (jobboard.py),
and the demo's twin of both."""
CSS = """
/* ---------- job board ---------- */
.jb{padding-top:6px;min-width:0;
  --g:#5f9a7b;--y:#d3b04f;--o:#d98e57;--r:#c1554b}
.jb-top{display:flex;gap:12px;align-items:center;margin:14px 0 16px;flex-wrap:wrap}
.jb-search{display:flex;gap:8px;flex:1 1 320px;min-width:0}
.jb-search input{flex:1;min-width:0;border-radius:999px;padding:11px 18px;font-size:15px}
.jb-search button{background:var(--accent);color:var(--on-accent);border:none;border-radius:999px;padding:0 22px;font:600 14px var(--sans);cursor:pointer}
.jb-search button:hover{background:var(--accent-hover)}
/* Jobs / Saved / Resume optimizer: a compact segmented control */
.jb-seg{display:inline-flex;gap:2px;padding:3px;border-radius:999px;background:var(--sunk);box-shadow:0 0 0 1px var(--whisper) inset;max-width:100%;overflow-x:auto;scrollbar-width:none}
.jb-seg::-webkit-scrollbar{display:none}
.jb-seg a{padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--muted);font-weight:600;font-size:13.5px;white-space:nowrap}
.jb-seg a:hover{color:var(--ink)}
.jb-seg a.on{background:var(--surface);color:var(--accent-ink);box-shadow:0 1px 3px rgba(20,20,19,.12),0 0 0 1px var(--line-2) inset}
.jb-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;align-items:start}
.jb-grid.solo{max-width:780px}
/* filter rail (wide screens) and its one-fold twin (narrow) */
.jb-rail{display:none}
.jb-rail-h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:0 2px 8px;border-bottom:1px solid var(--line)}
.jb-rail-h h2{font:650 17px var(--display);font-variation-settings:var(--dx);font-stretch:88%;letter-spacing:-.005em;display:flex;align-items:center;gap:7px}
.jb-n{display:inline-grid;place-items:center;min-width:19px;height:19px;padding:0 5px;border-radius:999px;background:var(--accent);color:var(--on-accent);font:700 11px var(--sans)}
.jb-clear{font-size:13px;color:var(--accent-ink);font-weight:600;text-decoration:none}
.jb-clear:hover{text-decoration:underline}
.jb-sec{border-bottom:1px solid var(--line);padding:4px 0}
.jb-sec>summary{display:flex;justify-content:space-between;align-items:center;gap:8px;cursor:pointer;list-style:none;padding:9px 2px;font-size:12px;font-weight:650;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2)}
.jb-sec>summary::-webkit-details-marker{display:none}
.jb-sec>summary:hover{color:var(--accent-ink)}
.car{display:inline-block;width:6px;height:6px;border-right:1.6px solid currentColor;border-bottom:1.6px solid currentColor;transform:rotate(45deg) translateY(-2px);margin:0 3px 0 2px;flex:none;transition:transform .15s}
details[open]>summary>.car{transform:rotate(-135deg) translate(-1px,-1px)}
.jb-opts{display:grid;gap:1px;padding:0 0 8px}
.jb-opt{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:8px;text-decoration:none;color:var(--ink-2);font-size:14px;line-height:1.3}
.jb-opt:hover{background:var(--sunk);color:var(--ink)}
.jb-opt i{width:16px;height:16px;flex:none;border-radius:4px;box-shadow:0 0 0 1.5px var(--line-2) inset;background:var(--surface);display:grid;place-items:center}
.jb-opt.radio i{border-radius:50%}
.jb-opt.on{color:var(--ink);font-weight:600}
.jb-opt.on i{background:var(--accent);box-shadow:none}
.jb-opt.check.on i::after{content:"";width:8px;height:4px;border-left:2px solid var(--on-accent);border-bottom:2px solid var(--on-accent);transform:rotate(-45deg) translate(1px,-1px)}
.jb-opt.radio.on i::after{content:"";width:6px;height:6px;border-radius:50%;background:var(--on-accent)}
.jb-mf{background:var(--surface);border:1px solid var(--whisper);border-radius:12px}
.jb-mf>summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;list-style:none;padding:11px 14px;font-weight:650;font-size:14.5px}
.jb-mf>summary::-webkit-details-marker{display:none}
.jb-mf>summary span{display:flex;align-items:center;gap:7px}
.jb-mf[open]>summary{border-bottom:1px solid var(--line)}
.jb-mf-b{padding:2px 14px 10px}
.jb-mf-b .jb-sec:last-of-type{border-bottom:none}
.jb-mf-c{padding-top:8px;border-top:1px solid var(--line)}
/* results */
.jb-count{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13px;color:var(--faint);margin:2px 2px 10px;flex-wrap:wrap}
.jb-chip{display:inline-flex;align-items:center;gap:6px;background:var(--surface);color:var(--ink-2);padding:4px 11px;border-radius:999px;font-size:13px;font-weight:550;
  box-shadow:0 0 0 1px var(--line-2) inset;cursor:pointer;list-style:none;white-space:nowrap}
.jb-chip::-webkit-details-marker{display:none}
.jb-chip:hover{box-shadow:0 0 0 1px var(--accent-ink) inset}
.jb-dd{position:relative}
.jb-dd[open]>.jb-chip{box-shadow:0 0 0 1px var(--accent-ink) inset}
.jb-menu{position:absolute;z-index:15;top:calc(100% + 6px);right:0;min-width:190px;max-width:calc(100vw - 32px);background:var(--surface);
  border:1px solid var(--line-2);border-radius:12px;box-shadow:var(--shadow-deep);padding:6px;display:grid}
.jb-menu a{padding:8px 11px;border-radius:8px;text-decoration:none;font-size:14px;color:var(--ink-2)}
.jb-menu a:hover{background:var(--sunk)}
.jb-menu a.on{background:var(--accent-tint);color:var(--accent-ink);font-weight:600}
/* a result: the left edge is the scam-check verdict, in the reviewer gauge's muted colours */
.jc{--edge:var(--y);position:relative;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:14px;background:var(--surface);border:1px solid var(--whisper);border-radius:12px;
  padding:16px 14px 15px 20px;margin-bottom:10px;transition:box-shadow .2s,border-color .2s}
.jc::before,.jd::before{content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:5px;border-radius:12px 0 0 12px;background:var(--edge)}
.jc.v-clear,.jd.v-clear{--edge:var(--g)}.jc.v-flagged.z2,.jd.v-flagged.z2{--edge:var(--o)}.jc.v-flagged.z3,.jc.v-held,.jd.v-flagged.z3,.jd.v-held{--edge:var(--r)}
.jc:hover{border-color:var(--line-2);box-shadow:var(--shadow)}
.jc-logo{width:46px;height:46px;border-radius:10px;background:var(--gold-tint);color:var(--gold-ink);display:grid;place-items:center;font:700 15px var(--display);font-variation-settings:var(--dx);flex:none;box-shadow:0 0 0 1px var(--whisper) inset}
.jc-logo.lg{width:56px;height:56px;border-radius:12px;font-size:19px}
.jc-body{min-width:0}
.jc-title{font:650 17.5px/1.25 var(--display);font-variation-settings:var(--dx);font-stretch:88%;letter-spacing:-.005em;overflow-wrap:anywhere}
.jc-link{color:var(--ink);text-decoration:none}
.jc-link::after{content:"";position:absolute;inset:0;border-radius:12px}
.jc:hover .jc-link{color:var(--accent-ink)}
.jc-link:focus-visible{outline:none}
.jc-link:focus-visible::after{outline:2px solid var(--accent-ink);outline-offset:2px}
.jc-co{color:var(--ink-2);font-size:14.5px;margin-top:3px}
.jc-cat{color:var(--faint);font-size:13px}
.jc-facts{color:var(--muted);font-size:13.5px;margin-top:2px}
.jc-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:center}
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
@media(min-width:1080px){
  .jb-grid{grid-template-columns:212px minmax(0,1fr);gap:26px}
  .jb-grid.solo{grid-template-columns:minmax(0,1fr)}
  .jb-rail{display:block;position:sticky;top:76px;max-height:calc(100vh - 92px);overflow:auto;padding-right:6px;scrollbar-width:thin}
  .jb-mf{display:none}
}
@media(max-width:620px){
  .jb-top{gap:10px}
  .jb-search{flex-basis:100%}
  .jb-seg{width:100%}.jb-seg a{flex:1;text-align:center;padding:7px 10px}
  .jc{grid-template-columns:minmax(0,1fr) auto;padding:14px 10px 13px 17px;gap:10px}
  .jc>.jc-logo{display:none}
}
/* ---------- the listing page: header, description and glance on the left; a sticky column of checks on the right ---------- */
.jb-page{--g:#5f9a7b;--y:#d3b04f;--o:#d98e57;--r:#c1554b}
.jd{--edge:var(--y);display:grid;grid-template-columns:minmax(0,1fr);gap:14px;min-width:0}
.jd::before{display:none}
.jd-back{margin-top:10px}
.jd-top{padding:4px 0 16px;border-bottom:1px solid var(--line)}
.jd-head{display:flex;gap:14px;align-items:flex-start;margin-bottom:14px}
.jd-h{min-width:0}
.jd-title{font:650 clamp(23px,3vw,30px)/1.12 var(--display);font-variation-settings:var(--dx);font-stretch:84%;letter-spacing:-.012em;overflow-wrap:anywhere;margin:2px 0 0}
.jd-co{font-size:15px;color:var(--ink-2);font-weight:600}
.jd-co a{color:var(--accent-ink);text-decoration:none}
.jd-co a:hover{text-decoration:underline}
.jd-sub{color:var(--muted);font-size:13.5px;margin-top:5px}
.jd-trust{margin-top:8px}
.jd-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.jd-acts .apply-btn{padding:10px 20px}
.jd-acts .navform{margin:0}
.jd-top .banner{margin:12px 0 0}
.jd-side,.jd-body{min-width:0;display:grid;gap:12px;align-content:start}
.jd section{background:var(--surface);border:1px solid var(--whisper);border-radius:12px;padding:16px 18px;margin:0}
.jd section h3,.jd-desc h2{font:650 16px var(--display);font-variation-settings:var(--dx);font-stretch:88%;margin-bottom:8px;letter-spacing:-.003em}
.jd-desc h2{font-size:18px;margin-bottom:4px}
.jd .js{border-top:4px solid var(--edge)}
.js-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}
.js-top h3{margin:0!important}
.js .risk{margin:4px 0 12px}
.js .risk .gauge{margin:0 4px}
.js .banner{margin-bottom:0}
.jd-find{margin-top:12px}
.jm-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.jm-head h3{margin:0!important}
.jm-lvl{font-weight:750}.jm-lvl.high{color:var(--ok)}.jm-lvl.medium{color:var(--gold-ink)}.jm-lvl.low{color:var(--muted)}
.jm-pct{font:750 26px var(--display);font-variation-settings:var(--dx);font-stretch:80%;font-variant-numeric:tabular-nums}
.jm-meter{position:relative;display:grid;grid-template-columns:2fr 1fr 1fr;gap:3px;height:8px;margin:12px 4px 6px}
.jm-meter i{background:var(--sand);border-radius:2px}.jm-meter i:first-child{border-radius:999px 2px 2px 999px}.jm-meter i:nth-child(3){border-radius:2px 999px 999px 2px}
.jm-meter.low i:nth-child(1){background:var(--faint)}.jm-meter.medium i:nth-child(-n+2){background:var(--gold)}.jm-meter.high i{background:var(--ok)}
.jm-meter b{position:absolute;top:50%;left:var(--pos);width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:var(--surface);border:3px solid var(--ink);box-shadow:0 1px 4px rgba(20,20,19,.28)}
.jm-meter.high b{border-color:var(--ok)}.jm-meter.medium b{border-color:var(--gold-ink)}.jm-meter.low b{border-color:var(--muted)}
.jm-scale{display:grid;grid-template-columns:2fr 1fr 1fr;font-size:11px;color:var(--faint);margin:0 4px}
.jm-scale span:nth-child(2){padding-left:2px}.jm-scale span:nth-child(3){text-align:right}
.jm-conf{font-size:13px;color:var(--muted);margin:10px 0 12px}
/* per-job helpers: match details, tailor, stand out, note to the poster */
.jm-ai{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding-top:12px;border-top:1px solid var(--line)}
.jm-ai-b{display:flex;align-items:center;gap:8px;min-height:44px;padding:9px 12px;border-radius:10px;background:var(--surface);color:var(--ink-2);text-decoration:none;
  font:600 13.5px/1.25 var(--sans);box-shadow:0 0 0 1px var(--line-2) inset;cursor:pointer;list-style:none;transition:box-shadow .15s,background .15s}
.jm-ai-b::-webkit-details-marker{display:none}
.jm-ai-b .ic{color:var(--gold-ink);flex:none}
.jm-ai-b:hover{box-shadow:0 0 0 1px var(--accent-ink) inset;color:var(--accent-ink)}
.jm-more[open]{grid-column:1/-1}
.jm-more[open]>.jm-ai-b{background:var(--accent-tint);color:var(--accent-ink);box-shadow:0 0 0 1px var(--accent-ink) inset}
.jm-more-b{padding:4px 2px 6px}
.jm-more-b .fitparts .cat{grid-template-columns:minmax(0,1fr) 70px 38px}
.jm-found{list-style:none;padding:0;display:grid;gap:5px;font-size:13.5px}
.jm-found .ev{display:block;font-size:12.5px;color:var(--muted)}
.jq-sum{font-size:14.5px;margin-bottom:10px}
.jq-list{list-style:none;padding:0;display:grid;gap:9px}
.jq-list li{display:grid;grid-template-columns:24px minmax(0,1fr);gap:9px;font-size:14.5px;align-items:start}
.jq-list .mk{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--sand);color:var(--muted)}
.jq-list .met .mk{background:var(--ok-tint);color:var(--ok)}.jq-list .missing .mk{background:var(--warn-tint);color:var(--warn)}
.jq-list .plain .mk{background:none;color:var(--faint)}
.jq-list .rq{display:inline-block;font-style:normal;font-size:11.5px;font-weight:600;margin-left:8px;padding:1px 8px;border-radius:999px;background:var(--sunk);color:var(--muted);white-space:nowrap}
.jq-list .rq.required{background:var(--accent-tint);color:var(--accent-ink)}
.jq-note{font-size:12.5px;color:var(--muted);margin-top:12px}
.jq-note a{color:var(--accent-ink);font-weight:600}
.jg dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px 18px}
.jg dt{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);font-weight:600}
.jg dd{font-size:14.5px;margin-top:2px}
.jd-desc .detail-desc{margin:8px 0 0;max-width:70ch}
.jd-body>.card{margin:0!important}
@media(min-width:1100px){
  .jd{grid-template-columns:minmax(0,1fr) 340px;grid-template-rows:auto 1fr;grid-template-areas:"top side" "body side";gap:18px 24px}
  .jd-top{grid-area:top}.jd-body{grid-area:body}
  .jd-side{grid-area:side;position:sticky;top:var(--side-top,76px)}          /* fx.js lowers --side-top when the column is taller than the window */
}
@media(max-width:620px){
  .jd-head{gap:11px}.jc-logo.lg{width:46px;height:46px}
  .jd section{padding:14px 14px}
  .jm-ai{grid-template-columns:1fr}
}
.qa-note{margin:12px 0 0;padding:10px 14px;border-left:3px solid var(--gold,#c99a06);background:var(--sunk);border-radius:0 8px 8px 0;font-size:13.5px;line-height:1.5;color:var(--muted)}
.jp h3{margin:0 0 12px;font-size:15px}
.jp-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.jp-who{display:flex;flex-direction:column;gap:2px;flex:1;min-width:160px}
.jp-who span{font-size:13.5px;color:var(--muted)}
.jp-mail{font-size:13.5px;display:inline-flex;align-items:center;gap:5px;overflow-wrap:anywhere}
.jp-hint{margin:0;font-size:13px;color:var(--muted)}
"""
