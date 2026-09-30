"""Styles for the community feed (feed.py and the demo's P.feed).

Appended to ui.CSS when this module is imported, so the shared stylesheet in ui.py stays untouched.
Only the site's own variables are used, so dark mode (and the demo's light/dark switch) come for free.
"""
import ui

CSS = """
/* ---------- feed (timeline layout: slim header with a Showing menu, gutter avatars, Your circle column) ---------- */
.fd-grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:44px;align-items:start}
.fd-main{min-width:0;max-width:660px;width:100%;margin:0 auto}
.fd-top{position:relative;margin:24px 0 0;padding-bottom:14px;border-bottom:1px solid var(--line)}
.fd-bar{display:flex;align-items:center;gap:14px;min-height:40px;padding-right:150px;flex-wrap:wrap}
.fd-bar h1{font-family:var(--display);font-weight:700;font-stretch:80%;font-size:30px;line-height:1;letter-spacing:-.005em;margin:0;color:var(--ink)}
.fd-views{display:flex;gap:4px;width:100%;max-width:100%;min-width:0;align-self:stretch;margin-top:14px;overflow-x:auto;scrollbar-width:none;border-bottom:0}
.fd-views::-webkit-scrollbar{display:none}
.fd-views a{flex:none;display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:999px;font-size:14px;font-weight:550;color:var(--muted);text-decoration:none;white-space:nowrap}
.fd-views a:hover{color:var(--ink);background:var(--sunk)}
.fd-views a[aria-current]{color:var(--accent-ink);background:var(--accent-tint);box-shadow:0 0 0 1px color-mix(in srgb,var(--accent-ink) 35%,transparent) inset}
.fd-show{position:relative}
.fd-show>summary,.fd-comp>summary{list-style:none;cursor:pointer}
.fd-show>summary::-webkit-details-marker,.fd-comp>summary::-webkit-details-marker{display:none}
.fd-show>summary{display:inline-flex;align-items:center;gap:6px;padding:6px 10px 6px 12px;border-radius:8px;background:var(--surface);box-shadow:0 0 0 1px var(--line-2) inset;font-size:14px;color:var(--muted);white-space:nowrap}
.fd-show>summary b{color:var(--ink);font-weight:650}
.fd-show>summary:hover{box-shadow:0 0 0 1px var(--accent-ink) inset}
.fd-show>summary .ic{transition:transform .2s var(--ease)}
.fd-show[open]>summary .ic{transform:rotate(180deg)}
.fd-menu{position:absolute;left:0;top:calc(100% + 6px);z-index:40;width:264px;max-width:calc(100vw - 32px);background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow-deep);padding:6px}
.fd-menu a{display:flex;gap:8px;align-items:flex-start;padding:8px 10px;border-radius:8px;text-decoration:none;color:var(--ink)}
.fd-menu a:hover{background:var(--sunk)}
.fd-menu a[aria-current]{background:var(--accent-tint)}
.fd-menu a[aria-current] b{color:var(--accent-ink)}
.fd-menu b{display:block;font-weight:600;font-size:14px;line-height:1.3}
.fd-menu small{display:block;font-size:12.5px;color:var(--muted);line-height:1.35}
.fd-chk{width:16px;flex:none;color:var(--accent-ink);padding-top:1px}
.fd-comp>summary.fd-write{position:absolute;top:4px;right:0}
.fd-w-o{display:inline-flex;align-items:center;gap:6px}
.fd-w-c{display:none}
.fd-comp[open]>summary .fd-w-o{display:none}
.fd-comp[open]>summary .fd-w-c{display:inline}
.fd-comp[open]>summary.fd-write{background:var(--sand);color:var(--ink)}
.fd-form{margin-top:14px;padding:14px;border-radius:12px;background:var(--surface);box-shadow:0 0 0 1px var(--line) inset}
.fd-form-top{display:flex;gap:12px;align-items:flex-start}
.fd-form-top{flex-wrap:wrap}
.fd-form-top textarea{flex:1;min-width:0;min-height:90px}
.fd-form-top .counter{flex-basis:100%;text-align:right;margin-top:-4px}
.fd-form-row{margin-top:10px;padding-left:50px;gap:8px;flex-wrap:wrap}
.fd-form-row select{width:auto}
.fd-form-row input{flex:1;min-width:0}
.fd-top>.banner{margin:12px 0 0}
.fd-topic,.fd-note{font-size:13.5px;color:var(--muted);margin:10px 0 0}
.fd-topic a{color:var(--accent-ink);font-weight:600;text-decoration:none;margin-left:6px}
.fd-list{margin-top:2px}
.fd-post{display:grid;grid-template-columns:40px minmax(0,1fr);column-gap:14px}
.fd-gut{position:relative;display:flex;justify-content:center;align-items:flex-start;padding-top:16px}
.fd-gut::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;margin-left:-.5px;background:var(--line-2)}
.fd-post:first-child .fd-gut::before{top:30px}
.fd-post:last-child .fd-gut::before{bottom:auto;height:30px}
.fd-post:only-child .fd-gut::before{display:none}
.fd-gut .avatar{position:relative;z-index:1;width:40px;height:40px;font-size:15px;text-decoration:none;box-shadow:0 0 0 4px var(--canvas)}
.fd-body{min-width:0;padding:16px 0 13px;border-top:1px solid var(--whisper)}
.fd-post:first-child .fd-body{border-top:0}
.fd-line{display:flex;align-items:center;gap:10px;min-width:0;min-height:22px}
.fd-who{flex:1;min-width:0;display:flex;align-items:baseline;gap:6px;white-space:nowrap}
.fd-nm{flex:0 0 auto;max-width:62%;min-width:0;overflow:hidden;text-overflow:ellipsis;font-weight:650;font-size:14.5px;color:var(--ink);text-decoration:none}
.fd-nm:hover{text-decoration:underline}
.fd-emp{flex:none;font-size:11px;font-weight:650;color:var(--accent-ink);letter-spacing:.02em}
.fd-sub{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:13px;color:var(--muted)}
.fd-time{flex:none;font-size:13px;color:var(--faint)}
.fd-kind{flex:none;display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap}
.fd-kind::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--line-2)}
.fd-kind.k-q::before{background:var(--info)}.fd-kind.k-opp::before{background:var(--accent)}.fd-kind.k-event::before{background:var(--gold)}
.fd-kind.k-win::before{background:var(--ok)}.fd-kind.k-adv::before{background:var(--gold-ink)}
.fd-line .pill{flex:none;font-size:11px;padding:2px 8px}
.fd-save{margin:0 -6px 0 0;flex:none}
.fd-save button{background:none;border:0;padding:5px;border-radius:8px;color:var(--faint);cursor:pointer;display:inline-flex}
.fd-save button:hover{background:var(--whisper);color:var(--ink)}
.fd-save button[aria-pressed=true]{color:var(--accent-ink)}
.fd-save svg{display:block}
.fd-text{white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px;line-height:1.6;margin:3px 0 7px;color:var(--ink)}
.fd-post .lnk{display:flex;flex-wrap:wrap;align-items:center;gap:2px 6px;font-size:13px;word-break:break-all;margin:0 0 7px}
.fd-post .lnk .ic{flex:none;color:var(--faint)}
.fd-flag{max-width:none;margin:6px 0 8px}
.fd-acts{display:flex;gap:4px 16px;flex-wrap:wrap;align-items:center}
.fd-acts form{margin:0}
.fd-acts button,.fd-acts a{background:none;border:0;padding:2px 0;font:500 12.5px var(--sans);color:var(--faint);cursor:pointer;text-decoration:none}
.fd-acts button:hover,.fd-acts a:hover{color:var(--ink);text-decoration:underline}
.fd-acts .on{color:var(--accent-ink);font-weight:650}
.fd-post .comments{margin-top:10px}
.fd-one .fd-list{max-width:660px}
.fd-empty{text-align:center;padding:52px 20px;color:var(--muted)}
.fd-empty svg{color:var(--faint);margin-bottom:10px}
.fd-empty h2{font-size:18px;color:var(--ink);margin:0 0 6px}
.fd-empty p{margin:0 auto 14px;max-width:34ch;font-size:14.5px}
.fd-rail{min-width:0;margin-top:24px;padding-left:28px;border-left:1px solid var(--whisper)}
.fd-rail-h{font-family:var(--display);font-stretch:84%;font-size:13px;font-weight:650;letter-spacing:.1em;text-transform:uppercase;color:var(--accent-ink);margin:6px 0 4px}
.fd-sec{padding:14px 0;border-top:1px solid var(--whisper)}
.fd-rail-h+.fd-sec{border-top:0;padding-top:8px}
.fd-sec h3{display:flex;align-items:baseline;gap:6px;font-size:14px;font-weight:650;margin:0 0 6px}
.fd-count{font-size:12px;font-weight:500;color:var(--faint)}
.fd-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 0}
.fd-mini{display:flex;align-items:center;gap:10px;min-width:0;text-decoration:none;color:var(--ink)}
.fd-mini .avatar{width:30px;height:30px;font-size:12.5px}
.fd-mini-t{display:flex;flex-direction:column;min-width:0;line-height:1.25}
.fd-mini-t b,.fd-mini-t small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fd-mini-t b{font-size:13.5px;font-weight:600}
.fd-mini-t small{font-size:12px;color:var(--muted)}
.fd-mini:hover b{text-decoration:underline}
.fd-row .navform{flex:none}
.fd-row .b.sm{padding:4px 9px;font-size:12px}
.fd-row .b.sm:not(.sec):not(.ghost){background:transparent;color:var(--accent-ink);box-shadow:0 0 0 1px var(--line-2) inset}
.fd-row .b.sm:not(.sec):not(.ghost):hover{box-shadow:0 0 0 1px var(--accent-ink) inset;background:var(--accent-tint)}
.fd-more{display:inline-block;margin-top:6px;font-size:12.5px;font-weight:600;color:var(--accent-ink);text-decoration:none}
.fd-more:hover{text-decoration:underline}
.fd-sub-h{font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--faint);margin:8px 0 1px}
.fd-sub-h:first-child{margin-top:0}
.fd-quiet{font-size:13px;color:var(--muted);margin:0}
.fd-stats{display:flex;justify-content:space-between;gap:10px;margin-bottom:8px}
.fd-stats small{white-space:nowrap}
.fd-stats b{display:block;font-family:var(--display);font-stretch:84%;font-size:24px;line-height:1.1;color:var(--ink)}
.fd-stats small{font-size:11.5px;color:var(--muted)}
.fd-topics{display:flex;flex-wrap:wrap;gap:4px 14px}
.fd-topics a{font-size:13px;color:var(--ink-2);text-decoration:none}
.fd-topics a:hover{color:var(--accent-ink)}
.fd-topics small{color:var(--faint);margin-left:3px}
.fd-rules{margin:0;padding-left:16px;font-size:12.5px;color:var(--muted);line-height:1.5}
@media (max-width:900px){.fd-grid{grid-template-columns:minmax(0,1fr);gap:0}.fd-main{max-width:none}
  .fd-rail{margin-top:26px;padding:10px 0 0;border-left:0;border-top:1px solid var(--line)}}
@media (max-width:520px){.fd-top{margin-top:18px}.fd-bar{padding-right:0;flex-direction:column;align-items:flex-start;gap:12px}
  .fd-bar h1{font-size:28px}.fd-comp>summary.fd-write{top:0}
  .fd-form-top .avatar{display:none}.fd-form-row{padding-left:0}
  .fd-post{grid-template-columns:34px minmax(0,1fr);column-gap:10px}.fd-gut .avatar{width:34px;height:34px;font-size:13px}
  .fd-post:first-child .fd-gut::before{top:26px}.fd-post:last-child .fd-gut::before{height:26px}
  .fd-kind{font-size:11.5px}.fd-sub{font-size:12.5px}.fd-nm{max-width:45%}.fd-line{gap:8px}}
"""

if "/* ---------- feed (timeline layout" not in ui.CSS:
    ui.CSS += CSS
