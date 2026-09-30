"""Styles for the public pages in the elite look (public_ui.py): the "Enter the vault" sign-in pages and the
logged-out landing (cinematic hero restyled navy and gold, the sample report, how it works, the scam-check teaser and
the employer call to action). Appended to ui.THEME_CSS, so it renders after the theme and wins over the older
landing and auth rules without !important. demo/build.py imports it too."""

import ui

CSS = """
/* ---------- public pages: the vault (sign-in) ---------- */
.vx{position:relative;isolation:isolate;overflow:hidden;display:grid;align-items:center;
  min-height:calc(100vh - var(--hdr,61px));min-height:calc(100svh - var(--hdr,61px));
  background:radial-gradient(900px 600px at 72% 40%,#14243E 0%,#08111F 55%,#03070E 100%)}
.vx::before{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(rgba(226,190,106,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(226,190,106,.05) 1px,transparent 1px);
  background-size:56px 56px;-webkit-mask-image:radial-gradient(700px 500px at 30% 50%,#000,transparent);mask-image:radial-gradient(700px 500px at 30% 50%,#000,transparent)}
.vx::after{content:"";position:absolute;right:-10%;top:10%;width:60%;height:80%;z-index:-1;pointer-events:none;
  background:radial-gradient(closest-side,rgba(226,190,106,.07),transparent)}
main:has(>.vx:only-child)+footer{margin-top:0}
.vx-in{width:100%;max-width:1320px;margin:0 auto;padding:72px 56px 80px;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:64px;align-items:center}
.vx-l{min-width:0}
.vx-l .crest{width:72px;height:79px;filter:drop-shadow(0 0 24px rgba(226,190,106,.35))}
.vx-l .eyebrow{margin-top:26px;letter-spacing:.3em}
.vx-h{font:700 clamp(40px,4.7vw,68px)/1.03 var(--display);color:var(--ivory);letter-spacing:-.012em;margin-top:14px}
.vx-h em,.vx-title em,.px-card h2 em{font-style:italic;background:var(--foil);-webkit-background-clip:text;background-clip:text;color:transparent;padding-right:.06em}
.vx-l>p{font-size:16.5px;color:#9AA9BD;margin-top:22px;max-width:34em;line-height:1.65}
.vx-pillars{display:flex;margin-top:40px;border:1px solid var(--hair);border-radius:12px;overflow:hidden;width:max-content;max-width:100%;background:rgba(5,10,20,.35)}
.vx-pillars div{padding:14px 22px 15px;font:500 10.5px/1.3 var(--mono);letter-spacing:.17em;text-transform:uppercase;color:var(--muted);border-right:1px solid var(--hair);min-width:0}
.vx-pillars div:last-child{border-right:0}
.vx-pillars b{display:block;width:max-content;max-width:100%;font:700 26px/1.2 var(--display);letter-spacing:0;text-transform:none;margin-bottom:4px;
  background:var(--foil);-webkit-background-clip:text;background-clip:text;color:transparent}
/* the card */
.vx-card{position:relative;justify-self:end;width:100%;max-width:560px;min-width:0;text-align:left;
  background:linear-gradient(180deg,rgba(18,33,56,.92),rgba(8,17,31,.95));border:1px solid var(--hair-2);border-radius:20px;padding:48px 42px 30px;
  box-shadow:0 50px 100px -40px #000,0 0 80px -30px rgba(226,190,106,.35)}
.vx-card::before{content:"";position:absolute;top:-1px;left:30px;right:30px;height:1px;background:var(--foil);pointer-events:none}
.vx-seal{position:absolute;top:-28px;left:40px;width:56px;height:56px;border-radius:50%;display:grid;place-items:center;
  background:radial-gradient(circle at 35% 28%,#A63A55,var(--garnet) 58%,#6A2133);box-shadow:0 0 0 2px var(--gold),0 0 0 6px rgba(8,17,31,.9),0 0 26px 4px rgba(226,190,106,.38)}
.vx-kick{font:500 10.5px/1.4 var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold);margin-top:4px}
.vx-title{font:700 31px/1.15 var(--display);color:var(--ivory);margin-top:8px;letter-spacing:-.005em;text-align:left}
.vx-sub{font-size:14.5px;color:#8E9BB0;margin-top:7px;line-height:1.55}
.vx-sub b{color:var(--ivory);font-weight:600;overflow-wrap:anywhere}
.vx-sub a{color:var(--gold-2)}
.vx-body{margin-top:24px}
.vx-card .banner{margin:0 0 18px;font-size:14px;text-align:left}
.vx-card .form-field{margin-bottom:22px}
.vx-card label{display:block;font:500 10.5px/1.4 var(--mono);letter-spacing:.2em;text-transform:uppercase;color:#8391A6;margin-bottom:9px}
.vx-card .label-row{align-items:baseline}
.vx-card .label-row label{margin-bottom:9px}
.vx-card .forgot{font-size:12.5px;font-weight:500;color:var(--gold-2);text-decoration:none;margin-bottom:9px}
.vx-card .forgot:hover{text-decoration:underline}
.vx-card input[type=email],.vx-card input[type=password],.vx-card input[type=text]{padding:15px 16px;font-size:15.5px;border-radius:10px;background:#050A14;border:1px solid #22334D;color:#DCE3EC}
.vx-card input:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(226,190,106,.15);outline:none}
.vx-card .pwbox input{padding-right:72px}
.vx-card .showpw{color:#8391A6;font-weight:500;font-size:14px;right:8px}
.vx-card .showpw:hover{color:var(--gold-2)}
.vx-inp{position:relative}
.vx-inp.hinted input{padding-right:196px}
.vx-hint{position:absolute;right:16px;top:50%;transform:translateY(-50%);font:500 11px/1 var(--mono);letter-spacing:.08em;color:#7F8DA3;pointer-events:none;white-space:nowrap}
.vx-hint.ok{color:var(--ok);letter-spacing:.06em;font-size:11.5px}
.vx-card .rules{margin:-10px 0 20px;font:500 11.5px/1.7 var(--mono);letter-spacing:.02em;color:#7F8DA3}
.vx-card .rules li::before{content:"○ ";color:#4E5E76}.vx-card .rules li.ok::before{content:"✓ ";color:var(--ok)}
.vx-card .submit-btn,.vx-card .apply-btn{display:block;width:100%;text-align:center;margin-top:28px;padding:16px;font-size:15px;border-radius:10px;
  background:linear-gradient(180deg,#A63A55,#7A2638);box-shadow:0 12px 28px -12px rgba(177,60,88,.85),0 1px 0 rgba(255,255,255,.12) inset}
.vx-card .submit-btn:hover,.vx-card .apply-btn:hover{background:linear-gradient(180deg,#B8435F,#8C2F45)}
.vx-card form+.submit-btn,.vx-card .banner+.apply-btn{margin-top:6px}
.vx-card .or{margin:22px 0;font-size:12.5px;color:#4E5E76}
.vx-card .or span{padding:0 2px}
.vx-card .outline-btn,.vx-card .vx-sso{display:block;width:100%;text-align:center;padding:14px 16px;border-radius:10px;border:1px solid var(--hair-2);box-shadow:none;
  background:rgba(226,190,106,.03);color:var(--gold-2);font:500 14.5px/1.3 var(--sans);text-decoration:none;cursor:pointer}
.vx-card .outline-btn:hover,.vx-card .vx-sso:hover{border-color:var(--gold);background:rgba(226,190,106,.08);color:var(--gold-2)}
.vx-card .vx-sso+.outline-btn{margin-top:10px}
.vx-card form.vx-alt{margin:0}
.vx-card .linkbtn{color:var(--gold-2)}
.vx-card .fine{font-size:13px;color:#7F8DA3;text-align:left;margin-top:16px}
.vx-card .fine a,.vx-card .start-foot a{color:var(--gold-2);font-weight:500;text-decoration:none}
.vx-card .fine a:hover,.vx-card .start-foot a:hover{text-decoration:underline}
.vx-card .start-foot{font-size:13.5px;color:#8E9BB0;margin-top:18px;text-align:left!important}
.vx-card .inline-form{margin:0 0 18px}
.vx-fine{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin-top:24px;padding-top:18px;border-top:1px solid rgba(226,190,106,.1);
  font:500 10.5px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:#56657B}
.vx-fine span{display:inline-flex;align-items:center;gap:8px}
.vx-fine .led{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(57,217,138,.14),0 0 10px rgba(57,217,138,.8)}
@media(max-width:1100px){.vx-in{padding:72px 36px 84px;gap:44px}.vx-card{padding:48px 32px 30px}.vx-pillars div{padding:12px 16px 13px}.vx-pillars b{font-size:22px}}
@media(max-width:900px){
  .vx{min-height:0;align-items:start}
  .vx-in{grid-template-columns:minmax(0,1fr);padding:56px 20px 56px;gap:48px}
  .vx-card{justify-self:stretch;max-width:none;order:-1}
  .vx::before{-webkit-mask-image:radial-gradient(500px 600px at 50% 30%,#000,transparent);mask-image:radial-gradient(500px 600px at 50% 30%,#000,transparent)}
  .vx-l .crest{width:52px;height:57px}
  .vx-h{font-size:clamp(34px,9vw,48px)}
  .vx-l .eyebrow{letter-spacing:.16em}
}
@media(max-width:520px){
  .vx-in{padding:48px 16px 48px}
  .vx-card{padding:44px 20px 24px;border-radius:16px}
  .vx-seal{left:22px;width:50px;height:50px;top:-25px}.vx-seal svg{width:23px;height:23px}
  .vx-title{font-size:27px}
  .vx-l .eyebrow{font-size:10px;letter-spacing:.1em}
  .vx-inp.hinted input{padding-right:16px}
  .vx-hint{position:static;transform:none;display:block;margin-top:8px}
  .vx-pillars{width:100%}.vx-pillars div{flex:1 1 0;padding:12px 10px;font-size:9px;letter-spacing:.12em}.vx-pillars b{font-size:19px}
  .vx-card .rules{grid-template-columns:1fr}
}

/* ---------- landing: cinematic hero and photo chapters in navy and gold ---------- */
.cine,.chapter{background:#050A14}
.scrim{background:linear-gradient(180deg,rgba(3,7,14,.62),rgba(3,7,14,0) 24%),linear-gradient(90deg,rgba(3,7,14,.9),rgba(5,10,20,.55) 42%,rgba(8,17,31,.05) 76%),
  linear-gradient(0deg,rgba(3,7,14,.82),rgba(3,7,14,0) 48%)}
.scrim::after{content:"";position:absolute;inset:0;pointer-events:none;
  background-image:linear-gradient(rgba(226,190,106,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(226,190,106,.06) 1px,transparent 1px);background-size:56px 56px;
  -webkit-mask-image:radial-gradient(760px 520px at 18% 78%,#000,transparent);mask-image:radial-gradient(760px 520px at 18% 78%,#000,transparent)}
.cine .cap.c0{max-width:1060px}
.cine h1.display{font-size:clamp(44px,6.9vw,104px)}
.cine .cap .crest,.ch-copy>.crest{width:60px;height:66px;margin-bottom:22px;filter:drop-shadow(0 0 22px rgba(226,190,106,.4))}
.cine .eyebrow,.chapter .eyebrow{letter-spacing:.28em;color:var(--gold)}
.cine .cta a,.chapter .cta a{padding:15px 26px;border-radius:10px}
.cine .cta .secondary,.chapter .cta .secondary{background:rgba(5,10,20,.45);color:var(--gold-2);box-shadow:0 0 0 1px var(--hair-2) inset}
.cine .cta .secondary:hover,.chapter .cta .secondary:hover{background:rgba(226,190,106,.1);box-shadow:0 0 0 1px var(--gold) inset}
.cine .cta .primary:hover,.chapter .cta .primary:hover{background:linear-gradient(180deg,#B13C58,#8C2F45)}
.cine-alt{margin:18px 0 0!important;font-size:14px!important}
.cine .cap .cine-alt a{color:rgba(246,222,158,.85);text-decoration:none;font-weight:500}.cine .cap .cine-alt a:hover{color:var(--gold-2);text-decoration:underline}
.cine-rail .bar i{background:var(--foil)}
@media(max-width:700px){.scrim{background:linear-gradient(180deg,rgba(3,7,14,.6),rgba(3,7,14,0) 26%),linear-gradient(0deg,rgba(3,7,14,.94),rgba(5,10,20,.62) 50%,rgba(3,7,14,.05) 82%)}
  .cine .cap .crest,.ch-copy>.crest{width:46px;height:51px;margin-bottom:16px}}

/* ---------- landing: how it works next to the sample report ---------- */
.px-proof{position:relative;isolation:isolate;overflow:hidden;background:radial-gradient(900px 640px at 78% 45%,#122138 0%,#08111F 55%,#050A14 100%);border-bottom:1px solid var(--whisper)}
.px-proof::before{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(rgba(226,190,106,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(226,190,106,.045) 1px,transparent 1px);background-size:56px 56px;
  -webkit-mask-image:radial-gradient(700px 520px at 25% 50%,#000,transparent);mask-image:radial-gradient(700px 520px at 25% 50%,#000,transparent)}
.px-in{max-width:1220px;margin:0 auto;padding:108px 40px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,540px);gap:72px;align-items:center}
.px-copy{min-width:0}
.px-copy .eyebrow{letter-spacing:.28em}
.px-copy h2.display{font-size:clamp(40px,4.6vw,66px);color:var(--ivory);margin:14px 0 30px;line-height:1.02}
.px-steps{list-style:none;padding:0;margin:0 0 34px;display:grid;gap:0;border-top:1px solid var(--hair)}
.px-steps li{display:grid;grid-template-columns:56px minmax(0,1fr);gap:16px;padding:20px 0;border-bottom:1px solid var(--hair)}
.px-steps .n{font:700 28px/1 var(--display);background:var(--foil);-webkit-background-clip:text;background-clip:text;color:transparent;padding-top:2px}
.px-steps b{display:block;font:700 20px/1.25 var(--display);color:var(--ivory)}
.px-steps p{color:#9AA9BD;font-size:15px;margin-top:4px;max-width:44ch}
.px-copy .cta,.px-acts{display:flex;gap:10px;flex-wrap:wrap}
.px-copy .cta a{text-decoration:none;padding:14px 24px;border-radius:10px;font-weight:600;font-size:15px}
/* the report: a HUD card with corner brackets, a still radar and the detector's evidence */
.px-hud{position:relative;margin:0;min-width:0;padding:26px 26px 22px;border-radius:18px;border:1px solid var(--hair-2);
  background:linear-gradient(180deg,rgba(14,26,45,.96),rgba(6,12,22,.97));box-shadow:0 50px 100px -40px #000,0 0 90px -30px rgba(226,190,106,.3)}
.px-hud::before{content:"";position:absolute;top:-1px;left:30px;right:30px;height:1px;background:var(--foil)}
.px-hud .px-corner{position:absolute;width:16px;height:16px;border:0 solid var(--gold);opacity:.8}
.px-hud .px-c1{top:10px;left:10px;border-width:1.5px 0 0 1.5px}.px-hud .px-c2{top:10px;right:10px;border-width:1.5px 1.5px 0 0}
.px-hud .px-c3{bottom:10px;left:10px;border-width:0 0 1.5px 1.5px}.px-hud .px-c4{bottom:10px;right:10px;border-width:0 1.5px 1.5px 0}
.px-hud .px-hh{display:flex;justify-content:space-between;gap:10px;font:500 10.5px/1.3 var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.px-hud .px-hh span:first-child::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--gold);box-shadow:0 0 8px var(--gold);margin-right:9px;vertical-align:1px}
.px-hud .px-hh span:last-child{color:#7F8DA3;border:1px dashed #3B4B64;border-radius:5px;padding:2px 7px;letter-spacing:.14em}
.px-hud .px-ht{font:700 23px/1.2 var(--display);color:var(--ivory);margin-top:14px}
.px-hud .px-hs{font-size:13px;color:#7F8DA3;margin-top:3px}
.px-mid{display:grid;grid-template-columns:196px minmax(0,1fr);gap:22px;align-items:center;margin-top:18px}
.px-radar{position:relative;width:196px;height:196px}
.px-radar .px-ring{position:absolute;border-radius:50%;border:1px solid rgba(226,190,106,.26)}
.px-radar .px-r1{inset:0}.px-radar .px-r2{inset:30px}.px-radar .px-r3{inset:60px}
.px-radar .px-tick{position:absolute;inset:-7px;border-radius:50%;background:repeating-conic-gradient(from 0deg,rgba(226,190,106,.5) 0 .7deg,transparent .7deg 6deg);
  -webkit-mask:radial-gradient(circle,transparent 101px,#000 102px,#000 105px,transparent 106px);mask:radial-gradient(circle,transparent 101px,#000 102px,#000 105px,transparent 106px)}
.px-radar .px-cross{position:absolute;inset:0}
.px-radar .px-cross::before,.px-radar .px-cross::after{content:"";position:absolute;background:rgba(226,190,106,.16)}
.px-radar .px-cross::before{left:50%;top:0;bottom:0;width:1px}.px-radar .px-cross::after{top:50%;left:0;right:0;height:1px}
.px-radar .px-beam{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 30deg,transparent 0 250deg,rgba(177,60,88,.32) 320deg,rgba(246,222,158,.8) 359deg,transparent 360deg)}
@media (prefers-reduced-motion:no-preference){.px-radar .px-beam{animation:px-spin 6s linear infinite}}
@keyframes px-spin{to{transform:rotate(1turn)}}
.px-radar .px-core{position:absolute;inset:72px;border-radius:50%;background:#050A14;border:1px solid var(--gold);display:grid;place-items:center;box-shadow:0 0 22px rgba(226,190,106,.3)}
.px-radar .px-core .crest{width:28px;height:31px}
.px-blip{position:absolute;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:50%;background:var(--crimson);box-shadow:0 0 0 4px rgba(255,59,78,.18),0 0 14px var(--crimson)}
.px-blip.px-a{background:var(--amber);box-shadow:0 0 0 4px rgba(255,181,71,.18),0 0 14px var(--amber)}
.px-blip small{position:absolute;left:12px;top:-4px;font:500 9px/1.2 var(--mono);letter-spacing:.06em;color:#FF9AA4;white-space:nowrap;background:rgba(5,10,20,.75);padding:1px 4px;border-radius:3px}
.px-blip.px-a small{color:#FFCF85}
.px-threat{min-width:0;border-radius:12px;padding:16px 16px 14px;background:linear-gradient(120deg,rgba(255,59,78,.18),rgba(140,47,69,.22) 55%,rgba(8,17,31,.4));
  border:1px solid rgba(255,59,78,.5);box-shadow:inset 0 0 36px rgba(255,59,78,.1)}
.px-threat .px-tnum{display:flex;align-items:baseline;gap:10px}
.px-threat .px-tnum b{font:700 46px/1 var(--display);color:#FF5D6C;text-shadow:0 0 20px rgba(255,59,78,.55)}
.px-threat .px-tnum small{font:500 10px var(--mono);letter-spacing:.18em;color:#FF9AA4;text-transform:uppercase}
.px-threat .px-tlv{font:700 10.5px/1.4 var(--mono);letter-spacing:.2em;color:#FF6B78;text-transform:uppercase;margin-top:10px}
.px-threat .px-tcls{font:700 16.5px/1.3 var(--display);color:var(--ivory);margin-top:3px}
.px-threat .px-lvl{display:flex;gap:3px;margin-top:10px}
.px-threat .px-lvl i{flex:1;height:5px;border-radius:2px;background:rgba(255,255,255,.08)}
.px-threat .px-lvl i.on{background:var(--crimson);box-shadow:0 0 6px rgba(255,59,78,.6)}
.px-threat .px-tmeta{font:500 10.5px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:#C99AA3;margin-top:9px}
.px-threat .px-tmeta b{color:#fff;font-weight:600}
.px-hud .px-sech{display:flex;justify-content:space-between;margin-top:20px;font:500 10.5px var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.px-hud .px-sech span:last-child{color:#7F8DA3}
.px-hud .px-ev{list-style:none;padding:0;margin:9px 0 0;display:grid;gap:7px}
.px-hud .px-ev li{border-left:2px solid var(--crimson);background:#0B1628;border-radius:0 9px 9px 0;padding:10px 12px;min-width:0}
.px-hud .px-ev li.warn{border-left-color:var(--amber)}
.px-hud .px-ev b{display:block;font-size:13.5px;font-weight:600;color:#EEF2F7;padding-right:80px}
.px-hud .px-ev .px-k{float:right;font:500 10px/1.9 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:#FF7E8A}
.px-hud .px-ev li.warn .px-k{color:#FFCB7A}
.px-hud .px-ev code{display:inline-block;max-width:100%;margin-top:6px;font:500 11.5px/1.45 var(--mono);color:#FF9AA4;background:rgba(255,59,78,.1);border:1px solid rgba(255,59,78,.25);padding:2px 7px;border-radius:5px;white-space:normal;overflow-wrap:anywhere}
.px-hud .px-ev li.warn code{color:#FFCB7A;background:rgba(255,181,71,.08);border-color:rgba(255,181,71,.25)}
.px-hud figcaption{margin-top:14px;font-size:13px;color:#8E9BB0;line-height:1.5}
@media(max-width:1000px){.px-in{grid-template-columns:minmax(0,1fr);gap:48px;padding:76px 20px}.px-hud{max-width:600px}}
@media(max-width:520px){.px-in{padding:60px 16px}.px-hud{padding:22px 16px 18px}.px-mid{grid-template-columns:minmax(0,1fr);justify-items:center}
  .px-threat{width:100%}.px-hud .px-ev b{padding-right:0}.px-hud .px-ev .px-k{float:none;display:block}.px-steps li{grid-template-columns:44px minmax(0,1fr);gap:12px}}

/* ---------- landing: scam-check teaser and employer call to action ---------- */
.px-check,.px-emp{max-width:1120px;margin:0 auto;padding:40px 20px 0}
.px-emp{padding-bottom:24px}
.px-card{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px 40px;align-items:center;padding:36px 40px;border-radius:20px;border:1px solid var(--hair-2);
  background:linear-gradient(135deg,rgba(18,33,56,.95),rgba(8,17,31,.96));box-shadow:0 40px 80px -40px #000,0 0 70px -34px rgba(226,190,106,.3);overflow:hidden}
.px-card::before{content:"";position:absolute;top:-1px;left:30px;right:30px;height:1px;background:var(--foil)}
.px-card h2{font:700 clamp(28px,3vw,40px)/1.1 var(--display);color:var(--ivory);margin-top:10px}
.px-card p{color:#9AA9BD;font-size:15.5px;margin-top:10px;max-width:60ch}
.px-card .eyebrow{letter-spacing:.24em}
.px-emp .px-card{grid-template-columns:auto minmax(0,1fr) auto;background:linear-gradient(120deg,rgba(140,47,69,.28),rgba(18,33,56,.95) 45%,rgba(8,17,31,.96))}
.px-emp .px-card>.crest{width:56px;height:62px;filter:drop-shadow(0 0 18px rgba(226,190,106,.35))}
.px-emp .vx-pillars{margin-top:22px}
.px-acts{flex-direction:column;align-items:stretch;min-width:230px}
.px-btn{display:block;text-align:center;text-decoration:none;padding:14px 22px;border-radius:10px;font-weight:600;font-size:15px;color:var(--gold-2);border:1px solid var(--hair-2);background:rgba(226,190,106,.04)}
.px-btn:hover{border-color:var(--gold);background:rgba(226,190,106,.1)}
.px-btn.gold{background:linear-gradient(180deg,#A63A55,#7A2638);color:#fff;border-color:rgba(246,222,158,.45);box-shadow:0 12px 26px -12px rgba(177,60,88,.85)}
.px-btn.gold:hover{background:linear-gradient(180deg,#B8435F,#8C2F45)}
@media(max-width:900px){.px-check,.px-emp{padding:28px 16px 0}.px-emp{padding-bottom:16px}.px-card,.px-emp .px-card{grid-template-columns:minmax(0,1fr);padding:30px 22px}
  .px-acts{min-width:0}.px-emp .px-card>.crest{width:44px;height:48px}}

/* ---------- landing: latest listings, restyled ---------- */
.home-list .section-title{font-size:clamp(34px,4.2vw,56px);margin:72px 0 12px;color:var(--ivory)}
.home-list>p.muted{color:#9AA9BD}
.job.teaser .pill{background:rgba(226,190,106,.08);color:var(--gold-2);box-shadow:0 0 0 1px var(--hair) inset;font:500 10.5px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase}
.home-list>p a,.home-list .empty a,.home-list .card a{color:var(--gold-2)!important}
.home-list+.px-emp{padding-top:8px}
@media(max-width:700px){.cine .eyebrow,.chapter .eyebrow{letter-spacing:.14em;font-size:10.5px}}
.how-bento .hb.lead .big{font-size:clamp(38px,4.4vw,58px);line-height:1}
"""

if "/* ---------- public pages: the vault" not in ui.THEME_CSS:
    ui.THEME_CSS += CSS
