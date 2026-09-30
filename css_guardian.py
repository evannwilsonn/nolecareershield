"""Styles for the Guardian (guardian.py): The Gallery (student home), the Security Report HUD, the pure-CSS scan that plays
before it, and the scam check's result in the same HUD. Appended to ui.THEME_CSS (which the page renders after ui.CSS), so
these rules come last and win over the older page styles without !important. demo/build.py imports it too.

The scan needs no script: the radar sweep, module bars, log lines and the percent counter are keyframes with delays, and
the report fades in over the scan after about 2.7 seconds. Reduced motion skips the scan and shows the report at once."""

import ui

CSS = """
/* ---------- guardian: the gallery ---------- */
.gal{position:relative;padding:6px 0 30px}
.gal::before{content:"";position:absolute;inset:-40px -40px 0;background-image:linear-gradient(rgba(226,190,106,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(226,190,106,.035) 1px,transparent 1px);background-size:48px 48px;pointer-events:none;-webkit-mask-image:linear-gradient(180deg,#000 30%,transparent);mask-image:linear-gradient(180deg,#000 30%,transparent)}
.gal>*{position:relative}
.gal-top .eyebrow{letter-spacing:.24em}
.gal-top h1{font:700 42px/1.12 var(--display);color:var(--ivory);margin:8px 0 0;letter-spacing:-.3px}
.gal-top h1 em{font-style:italic;background:var(--foil);-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.06em}
.gal-top .sub{color:var(--muted);font-size:14.5px;margin:8px 0 0;max-width:68ch}
.gal-bar{display:flex;gap:10px;margin-top:24px;align-items:center;flex-wrap:wrap}
.gal-search{flex:1 1 380px;display:flex;align-items:center;gap:10px;background:var(--navy-2);border:1px solid var(--hair);border-radius:10px;padding:0 6px 0 16px;color:var(--muted);min-width:0}
.gal-search:focus-within{border-color:var(--gold);box-shadow:0 0 0 3px rgba(226,190,106,.15)}
.gal-search .ic{flex:none;color:var(--muted)}
.gal-search input{flex:1;min-width:0;background:none;border:0;box-shadow:none;color:var(--ivory);font:400 14px var(--sans);padding:12px 0;outline:none}
.gal-search input::placeholder{color:var(--muted)}
.gal-search button{flex:none;background:none;border:0;color:var(--gold-2);font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;padding:9px 10px;cursor:pointer;border-radius:7px}
.gal-search button:hover{background:rgba(226,190,106,.08)}
.gal-chips{display:flex;gap:10px;flex-wrap:wrap}
.gchip{padding:10px 14px;border:1px solid rgba(255,255,255,.08);border-radius:10px;font-size:13px;background:var(--navy-2);color:#AEB9C9;text-decoration:none;white-space:nowrap}
.gchip:hover{border-color:var(--hair-2);color:var(--gold-2)}
.gchip.on{background:var(--foil);color:#1B1406;border-color:transparent;font-weight:600}
.gal .statrow{margin:22px 0 0}
.gal-att{display:flex;align-items:center;gap:8px 18px;flex-wrap:wrap;margin-top:12px;padding:10px 14px;border:1px solid var(--hair);border-left:2px solid var(--gold);border-radius:10px;background:linear-gradient(90deg,rgba(226,190,106,.07),rgba(12,23,41,.6) 60%)}
.gal-att .h{font:500 10.5px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold)}
.gal-att a{display:inline-flex;align-items:center;gap:8px;color:var(--ink);font-size:13.5px;text-decoration:none}
.gal-att a:hover{color:var(--gold-2)}
.gal-att a i{width:7px;height:7px;border-radius:50%;background:#7F8DA3;flex:none}
.gal-att a.g i{background:var(--gold);box-shadow:0 0 8px rgba(226,190,106,.8)}.gal-att a.o i{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.gal-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.gal-grid>.card{margin:0}
.gcard{display:flex;flex-direction:column;padding:20px}
.gcard:hover{border-color:rgba(226,190,106,.34)}
.gcard .hd{display:flex;align-items:center;gap:12px;min-width:0}
.g-logo{width:42px;height:42px;border-radius:10px;display:grid;place-items:center;flex:none;font:700 15px var(--display);color:var(--gold-2);border:1px solid rgba(226,190,106,.3);background:#132A4A}
.g-logo.t0{background:#5B1E2D}.g-logo.t1{background:#132A4A}.g-logo.t2{background:#1D3A33}.g-logo.t3{background:#4A3813}
.g-who{min-width:0}.g-who .co{font-size:13px;color:#AEB9C9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.g-who .ver,.g-who .unv{margin-top:3px}
.gcard h3{font:700 19px/1.22 var(--display);color:var(--ivory);margin:15px 0 0}
.g-link{color:inherit;text-decoration:none}
.g-link::after{content:"";position:absolute;inset:0;border-radius:14px;z-index:0}
.g-link:focus-visible{outline:none}.g-link:focus-visible::after{box-shadow:0 0 0 2px var(--gold)}
.gcard .meta{font-size:12.5px;color:var(--muted);margin-top:7px}
.gcard .tags{margin-top:12px}
.gcard .foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:auto;padding-top:14px;border-top:1px solid rgba(226,190,106,.12)}
.gcard .tags+.foot,.gcard .meta+.foot{margin-top:16px}
.gcard .pay{font:700 18px var(--display);color:var(--ivory);white-space:nowrap}
.gcard .pay small{font:400 11.5px var(--sans);color:var(--muted)}
.gcard .scanchip,.gcard .ver{position:relative;z-index:1}
.gal-more{margin:18px 0 0;text-align:right}
.gal-more a{font:500 11px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold-2);text-decoration:none}
.gal-more a:hover{color:var(--gold)}
.gal-empty{margin-top:22px;text-align:center;padding:40px 24px}
.gal-empty h2{font:700 24px var(--display);color:var(--ivory);margin:14px 0 6px}
.gal-empty p{color:var(--muted);max-width:52ch;margin:0 auto}
.gal-empty .row{justify-content:center;margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}
@media(max-width:1180px){.gal-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.gal-top h1{font-size:31px}.gal-grid{grid-template-columns:minmax(0,1fr)}.gal-bar{gap:8px}
  .gal-chips{flex-wrap:nowrap;overflow-x:auto;width:100%;scrollbar-width:none;padding-bottom:2px}.gal-chips::-webkit-scrollbar{display:none}
  .gchip{padding:8px 12px}.gal-search{flex-basis:100%}.gal .statrow>div,.gal .statrow>a{flex:1 1 140px}}

/* ---------- guardian: the HUD ---------- */
.gd-page{max-width:760px;margin:0 auto;padding-bottom:30px}
.gd-page>.back{margin-top:10px}
.gd-page>.banner{margin:4px 0 12px}
.gd-stage{display:grid;position:relative;margin-top:8px}
.gd-stage>*{grid-area:1/1;min-width:0}
.gd-check{margin-bottom:6px}
.gd-hud,.gd-scan{position:relative;background:linear-gradient(180deg,#0A1424,#060C17);border:1px solid var(--hair-2);border-radius:16px;padding:24px 26px;overflow:hidden;
  box-shadow:0 0 0 1px rgba(0,0,0,.6),0 50px 100px -30px #000,0 0 60px -20px rgba(226,190,106,.25);color:var(--txt)}
.gd-hud::before,.gd-scan::before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(255,255,255,.018) 0 1px,transparent 1px 3px);pointer-events:none}
.gd-hud>*,.gd-scan>*{position:relative}
.gd-c{position:absolute!important;width:16px;height:16px;border:0 solid var(--gold);opacity:.9;pointer-events:none}
.gd-c.c1{top:10px;left:10px;border-width:1.5px 0 0 1.5px}.gd-c.c2{top:10px;right:10px;border-width:1.5px 1.5px 0 0}
.gd-c.c3{bottom:10px;left:10px;border-width:0 0 1.5px 1.5px}.gd-c.c4{bottom:10px;right:10px;border-width:0 1.5px 1.5px 0}
.gd-hh{display:flex;justify-content:space-between;align-items:center;gap:12px;font:500 10.5px var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.gd-hh>span:last-child,.gd-x{color:var(--muted)}
.gd-x{text-decoration:none;white-space:nowrap}.gd-x:hover{color:var(--gold-2)}
.gd-led{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--gold);box-shadow:0 0 8px var(--gold);margin-right:10px;vertical-align:1px}
.gd-ht{font:700 24px/1.2 var(--display);color:var(--ivory);margin:12px 0 0;letter-spacing:0}
.gd-hs{font-size:12.5px;color:var(--muted);margin-top:4px}
.gd-threat{--t:255,59,78;--tl:#FF9AA4;--tn:#FF5D6C;margin-top:16px;border-radius:12px;padding:18px 20px;display:grid;grid-template-columns:130px minmax(0,1fr);gap:20px;align-items:center;
  background:linear-gradient(120deg,rgba(var(--t),.2),rgba(140,47,69,.18) 50%,rgba(8,17,31,.4));border:1px solid rgba(var(--t),.55);box-shadow:inset 0 0 40px rgba(var(--t),.12)}
.gd-threat.lv2{--t:255,150,60;--tl:#FFC894;--tn:#FFA25A}
.gd-threat.lv1{--t:226,190,106;--tl:#F6DE9E;--tn:#F1D48C}
.gd-threat.lv0{--t:57,217,138;--tl:#9BF0C4;--tn:#5BE3A0}
.gd-threat.lv0,.gd-threat.lv1{background:linear-gradient(120deg,rgba(var(--t),.14),rgba(12,23,41,.5) 55%,rgba(8,17,31,.4))}
.gd-tnum{text-align:center;border-right:1px solid rgba(var(--t),.35);padding-right:6px}
.gd-tnum b{display:block;font:700 62px/1 var(--display);color:var(--tn);text-shadow:0 0 22px rgba(var(--t),.6);font-variant-numeric:lining-nums tabular-nums}
.gd-tnum small{display:block;font:500 10px var(--mono);letter-spacing:.2em;color:var(--tl);margin-top:6px;text-transform:uppercase}
.gd-tlv{font:700 12px var(--mono);letter-spacing:.28em;color:var(--tn);text-transform:uppercase}
.gd-tcls{font:700 19px/1.25 var(--display);color:var(--ivory);margin-top:4px}
.gd-lvl{display:flex;gap:3px;margin-top:10px}.gd-lvl i{flex:1;height:5px;border-radius:2px;background:rgba(255,255,255,.08)}
.gd-lvl i.on{background:rgb(var(--t));box-shadow:0 0 6px rgba(var(--t),.6)}
.gd-tmeta{display:flex;gap:6px 16px;flex-wrap:wrap;margin-top:10px;font:500 10.5px var(--mono);letter-spacing:.1em;color:var(--tl);text-transform:uppercase;opacity:.9}
.gd-tmeta b{color:#fff;font-weight:600}
.gd-sech{margin-top:18px;display:flex;justify-content:space-between;gap:10px;font:500 10.5px var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.gd-sech span+span{color:var(--muted)}
.gd-matrix{margin-top:9px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.gd-mx{border-radius:9px;padding:10px 11px;background:#0B1628;border:1px solid rgba(255,255,255,.06);min-width:0}
.gd-mx .n{font:500 9.5px var(--mono);letter-spacing:.13em;text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
.gd-mx .v{font-size:12.5px;line-height:1.35;color:#E6ECF4;margin-top:6px;font-weight:600;overflow-wrap:anywhere}
.gd-mx .v small{font:500 10px var(--mono);opacity:.8}
.gd-mx .dt{width:7px;height:7px;border-radius:50%;flex:none}
.gd-mx.r{border-color:rgba(255,59,78,.45);background:rgba(255,59,78,.07)}.gd-mx.r .v{color:#FF8C97}.gd-mx.r .dt{background:var(--crimson);box-shadow:0 0 8px var(--crimson)}
.gd-mx.w{border-color:rgba(255,181,71,.4);background:rgba(255,181,71,.06)}.gd-mx.w .v{color:#FFCB7A}.gd-mx.w .dt{background:var(--amber);box-shadow:0 0 8px var(--amber)}
.gd-mx.o .v{color:#7EE8B3}.gd-mx.o .dt{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.gd-hud ul.reasons{margin:9px 0 0;padding:0;list-style:none;display:grid;gap:7px}
.gd-hud ul.reasons>li{background:none;border:0;padding:0;margin:0;border-radius:0}
.gd-e{border-left:2px solid var(--crimson);background:#0B1628;border-radius:0 9px 9px 0;padding:10px 12px}
.gd-e.w{border-left-color:var(--amber)}.gd-e.o{border-left-color:var(--ok)}
.gd-e b{font-size:13.5px;color:#EEF2F7;font-weight:600;display:block;padding-right:84px}
.gd-e .k{float:right;font:500 10px var(--mono);letter-spacing:.12em;color:#FF7E8A;margin-left:10px}
.gd-e.w .k{color:#FFCB7A}.gd-e.o .k{color:#7EE8B3}
.gd-found{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.gd-e code{display:inline-block;font:400 11px/1.5 var(--mono);color:#FF9AA4;background:rgba(255,59,78,.1);border:1px solid rgba(255,59,78,.25);padding:2px 7px;border-radius:5px;overflow-wrap:anywhere;max-width:100%}
.gd-e.w code{color:#FFCB7A;background:rgba(255,181,71,.08);border-color:rgba(255,181,71,.25)}
.gd-e p{font-size:12.5px;color:var(--muted);margin:6px 0 0;line-height:1.5}
.gd-e p:empty{display:none}
.gd-rf{margin-top:22px}
.gd-hash{font:400 10px var(--mono);color:#56647A;letter-spacing:.08em;text-transform:uppercase;display:flex;justify-content:space-between;gap:6px 14px;flex-wrap:wrap;margin-bottom:10px}
.gd-acts{display:flex;gap:10px}
.gd-acts>*{flex:1;display:flex;margin:0}
.gd-btn{flex:1;display:block;text-align:center;padding:13px;border-radius:10px;font:600 13.5px var(--sans);text-decoration:none;cursor:pointer;background:none}
.gd-btn.g{background:linear-gradient(180deg,#A2364F,#7A2638);color:#fff;border:1px solid rgba(246,222,158,.45);box-shadow:0 8px 20px -8px rgba(177,60,88,.7)}
.gd-btn.g:hover{background:linear-gradient(180deg,#B13C58,#8C2F45)}
.gd-btn.o{border:1px solid var(--hair-2);color:var(--gold-2)}.gd-btn.o:hover{background:rgba(226,190,106,.08);border-color:var(--gold)}
.gd-verdict{margin-top:12px;padding:12px 14px;border-radius:10px;background:#0B1628;border:1px solid rgba(255,255,255,.06)}
.gd-verdict .eyebrow{display:block;font-size:10px;margin-bottom:4px}
.gd-verdict b{font:700 17px var(--display);color:var(--ivory)}
.gd-verdict p{font-size:13px;color:var(--muted);margin:4px 0 0}
.gd-plat{font-size:13px;color:var(--muted);margin:8px 0 0}
.js-report{margin-top:12px;width:100%}

/* ---------- guardian: the scan (only rendered when it plays) ---------- */
.gd-scan{z-index:2}
.gd-radar{width:300px;height:300px;position:relative;margin:22px auto 0}
.gd-radar .gd-ring{position:absolute;border-radius:50%;border:1px solid rgba(226,190,106,.28)}
.gd-radar .r0{inset:0}.gd-radar .r1{inset:15%}.gd-radar .r2{inset:30%}
.gd-radar .gd-tick{position:absolute;inset:-10px;border-radius:50%;background:repeating-conic-gradient(from 0deg,rgba(226,190,106,.55) 0 .6deg,transparent .6deg 6deg);
  -webkit-mask:radial-gradient(circle,transparent calc(50% - 4px),#000 calc(50% - 3px),#000 calc(50% + 2px),transparent calc(50% + 3px));mask:radial-gradient(circle,transparent calc(50% - 4px),#000 calc(50% - 3px),#000 calc(50% + 2px),transparent calc(50% + 3px))}
.gd-radar .gd-cross{position:absolute;inset:0}
.gd-radar .gd-cross::before,.gd-radar .gd-cross::after{content:"";position:absolute;background:rgba(226,190,106,.18)}
.gd-radar .gd-cross::before{left:50%;top:0;bottom:0;width:1px}.gd-radar .gd-cross::after{top:50%;left:0;right:0;height:1px}
.gd-radar .gd-beam{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 30deg,transparent 0 250deg,rgba(177,60,88,.35) 320deg,rgba(246,222,158,.85) 359deg,transparent 360deg)}
.gd-blip{position:absolute;width:9px;height:9px;margin:-4.5px 0 0 -4.5px;border-radius:50%;background:var(--crimson);box-shadow:0 0 0 5px rgba(255,59,78,.18),0 0 18px var(--crimson);z-index:1}
.gd-blip.w{background:var(--amber);box-shadow:0 0 0 5px rgba(255,181,71,.18),0 0 18px var(--amber)}
.gd-blip small{position:absolute;left:14px;top:-3px;font:500 9.5px var(--mono);color:#FF9AA4;white-space:nowrap;letter-spacing:.08em}
.gd-blip.w small{color:#FFCF85}
.gd-radar .gd-core{position:absolute;inset:38%;border-radius:50%;background:#050A14;border:1px solid var(--gold);display:grid;place-items:center;box-shadow:0 0 24px rgba(226,190,106,.3);z-index:1}
.gd-radar .gd-core .crest{width:44%;height:auto}
@property --gdp{syntax:"<integer>";inherits:false;initial-value:100}
.gd-pct{text-align:center;font:500 11px var(--mono);letter-spacing:.2em;color:var(--muted);margin-top:14px;text-transform:uppercase}
.gd-pct b{display:block;font:700 30px var(--display);color:var(--gold-2);letter-spacing:0;counter-reset:gdp var(--gdp)}
.gd-pct b::before{content:counter(gdp) "%"}
.gd-mods{margin-top:16px;display:grid;gap:8px}
.gd-mod{display:grid;grid-template-columns:150px minmax(0,1fr) 70px;gap:12px;align-items:center;font:500 11px var(--mono);letter-spacing:.08em;color:#A8B4C5;text-transform:uppercase}
.gd-mod .pb{height:5px;background:#16243A;border-radius:3px;overflow:hidden}.gd-mod .pb i{display:block;height:100%;background:var(--foil);transform-origin:left}
.gd-mod .s{text-align:right;color:var(--ok)}.gd-mod .s.r{color:var(--crimson)}.gd-mod .s.w{color:var(--gold)}
.gd-log{margin-top:14px;border:1px solid rgba(226,190,106,.14);border-radius:10px;background:#040810;padding:12px 14px;font:400 11px/1.75 var(--mono);color:#6D7D95;overflow-wrap:anywhere}
.gd-log b{color:#C6D1E0;font-weight:500}.gd-log .r{color:#FF7E8A}.gd-log .w{color:#FFCB7A}.gd-log .g{color:var(--gold)}.gd-log .o{color:var(--ok)}
.gd-cur{font-style:normal}
.gd-stage.anim .gd-scan{animation:gd-out .45s ease 2.55s forwards,gd-gone .01s linear 3.05s forwards}
.gd-stage.anim .gd-report{animation:gd-in .6s cubic-bezier(.2,.7,.2,1) 2.7s both}
.gd-stage.anim .gd-beam{animation:gd-spin 1.6s linear infinite}
.gd-stage.anim .gd-blip{animation:gd-pop .45s cubic-bezier(.2,1.6,.4,1) var(--d,0s) both}
.gd-stage.anim .gd-pct b{animation:gd-count 2.3s cubic-bezier(.3,.1,.4,1) both}
.gd-stage.anim .gd-mod .pb i{animation:gd-bar calc(.6s + var(--i) * .15s) cubic-bezier(.3,.6,.3,1) calc(var(--i) * .08s) both}
.gd-stage.anim .gd-mod .s{animation:gd-fade .2s linear calc(.6s + var(--i) * .23s) both}
.gd-stage.anim .gd-log>div{animation:gd-fade .25s linear calc(.25s + var(--i) * .36s) both}
.gd-stage.anim .gd-cur{animation:gd-blink .8s steps(1) infinite}
@keyframes gd-out{to{opacity:0;transform:scale(.985)}}
@keyframes gd-gone{to{visibility:hidden;max-height:0;padding:0;border-width:0}}
@keyframes gd-in{from{opacity:0;visibility:hidden;transform:translateY(10px)}to{opacity:1;visibility:visible;transform:none}}
@keyframes gd-spin{to{transform:rotate(1turn)}}
@keyframes gd-pop{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:none}}
@keyframes gd-count{from{--gdp:0}to{--gdp:100}}
@keyframes gd-bar{from{transform:scaleX(0)}to{transform:none}}
@keyframes gd-fade{from{opacity:0}to{opacity:1}}
@keyframes gd-blink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.gd-stage.anim .gd-scan{display:none}.gd-stage.anim .gd-report{animation:none}}
@media(max-width:620px){.gd-hud,.gd-scan{padding:20px 16px;border-radius:14px}.gd-ht{font-size:21px}
  .gd-threat{grid-template-columns:minmax(0,1fr);gap:12px;padding:16px}.gd-tnum{border-right:0;border-bottom:1px solid rgba(var(--t),.35);padding:0 0 10px;display:flex;align-items:baseline;gap:12px;justify-content:flex-start}
  .gd-tnum b{font-size:50px}.gd-tnum small{margin:0}
  .gd-matrix{grid-template-columns:repeat(2,minmax(0,1fr))}
  .gd-acts{flex-direction:column}
  .gd-radar{width:232px;height:232px}.gd-blip small{font-size:8.5px}
  .gd-mod{grid-template-columns:118px minmax(0,1fr) 58px;gap:8px;font-size:10px}
  .gd-hh{letter-spacing:.14em;font-size:10px}}
"""

if "/* ---------- guardian: the gallery" not in ui.THEME_CSS:
    ui.THEME_CSS += CSS
