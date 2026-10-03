"""Styles for the Career assistant (assistant.py). assistant.py appends CSS to ui.CSS on import, so ui.py is untouched.
Colours come from the site's variables, so dark mode follows the rest of the site."""

CSS = """
/* ---------- career assistant ---------- */
.cs{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:0;border:1px solid var(--whisper);border-radius:16px;background:var(--surface);min-height:calc(100vh - 150px)}
.cs .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cs-inline{display:inline;margin:0}
/* top bar: the chat history is a dropdown */
.cs-top{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--whisper);position:sticky;top:57px;background:var(--surface);z-index:5;border-radius:16px 0 0 0}
.cs-top-t{flex:1;min-width:0;display:flex;align-items:center;gap:7px;font-weight:650;font-size:14.5px;color:var(--ink-2)}
.cs-top-t span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cs-top-t .ic{color:var(--accent-ink);flex:none}
.cs-chats{position:relative}
.cs-chats-btn{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:7px;font-weight:650;font-size:14px;padding:7px 12px;border-radius:9px;border:1px solid var(--line-2);color:var(--ink);background:var(--surface)}
.cs-chats-btn::-webkit-details-marker{display:none}
.cs-chats-btn:hover,.cs-chats[open] .cs-chats-btn{border-color:var(--accent-ink);color:var(--accent-ink)}
.cs-menu{position:absolute;left:0;top:calc(100% + 6px);width:min(340px,86vw);background:var(--surface);border:1px solid var(--line-2);border-radius:12px;box-shadow:var(--shadow);padding:8px;z-index:20;display:flex;flex-direction:column;gap:4px}
.cs-new{display:flex;align-items:center;gap:9px;text-decoration:none;font-weight:650;font-size:14.5px;padding:8px 8px;border-radius:9px;color:var(--ink)}
.cs-new:hover{background:var(--whisper)}
.cs-hist{font-size:12px;font-weight:650;color:var(--muted);padding:8px 8px 2px;text-transform:uppercase;letter-spacing:.04em}
.cs-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:1px;overflow-y:auto;max-height:min(60vh,420px)}
.cs-list li{display:flex;align-items:center;border-radius:9px;position:relative}
.cs-list li:hover,.cs-list li.on{background:var(--sand)}
.cs-list a{flex:1;min-width:0;display:flex;justify-content:space-between;gap:8px;text-decoration:none;color:var(--ink-2);font-size:14px;padding:8px 8px;align-items:baseline}
.cs-list .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cs-list .d{font-size:11.5px;color:var(--faint);white-space:nowrap}
.cs-del{background:none;border:none;color:var(--faint);cursor:pointer;padding:6px;border-radius:6px;font:inherit;display:flex}
.cs-del:hover{color:var(--bad);background:var(--bad-tint)}
.cs-empty{font-size:13px;color:var(--faint);padding:4px 8px}
/* right context panel */
.cs-ctx{border-left:1px solid var(--whisper);background:var(--canvas);min-width:0;border-radius:0 16px 16px 0}
.cs-ctxd{position:sticky;top:57px}
.cs-ctxd>summary{display:none}
.cs-ctx-in{padding:16px 16px 20px;display:flex;flex-direction:column;gap:18px;max-height:calc(100vh - 70px);overflow-y:auto}
.cs-sec h2{display:flex;align-items:center;gap:8px;font-family:var(--display);font-variation-settings:var(--dx);font-weight:650;font-stretch:88%;font-size:17px;margin:0 0 10px;color:var(--ink)}
.cs-sec h2 .ic,.cs-sec h3 .ic{color:var(--accent-ink)}
.cs-sec h3{display:flex;align-items:center;gap:7px;font-size:13.5px;font-weight:650;margin:14px 0 6px;color:var(--ink-2)}
.cs-str{display:flex;justify-content:space-between;font-size:13.5px;color:var(--muted);margin-bottom:6px}
.cs-str b{color:var(--ink)}
.cs-hint{font-size:13px;color:var(--faint);margin:8px 0 0;line-height:1.5}
.cs-hint a,.cs-link{color:var(--info);font-weight:650}
.cs-link{display:inline-block;font-size:13.5px;margin-top:8px;text-decoration:none}
.cs-link:hover{text-decoration:underline}
.cs-mem{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
.cs-mem li{font-size:13.5px;color:var(--ink-2);background:var(--surface);border:1px solid var(--whisper);border-radius:9px;padding:7px 10px;line-height:1.4}
.cs-minis{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
.cs-mini{display:flex;align-items:flex-start;gap:6px;background:var(--surface);border:1px solid var(--whisper);border-radius:10px;padding:8px 6px 8px 10px}
.cs-mini-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.cs-mini-t a{font-weight:650;font-size:14px;color:var(--ink);text-decoration:none;overflow-wrap:anywhere}
.cs-mini-t a:hover{color:var(--accent-ink)}
.cs-mini-t span{font-size:12.5px;color:var(--muted)}
.cs-mini .cs-ic{padding:5px}
.cs-unp{margin-top:8px}
.cs-unp>summary{cursor:pointer;font-size:13px;color:var(--muted);margin-bottom:6px}
.cs-main{display:flex;flex-direction:column;min-width:0;min-height:0}
.cs-memnote{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);margin:0}
.cs-memnote .ic{color:var(--accent-ink);flex:none}
.cs-memnote a{color:var(--info);font-weight:650}
/* home */
.cs-home{margin:auto;width:100%;max-width:720px;padding:48px 20px;text-align:center}
.cs-home h1{display:flex;align-items:center;justify-content:center;gap:12px;font-family:var(--display);font-variation-settings:var(--dx);font-weight:650;font-stretch:88%;font-size:clamp(28px,4.6vw,40px);letter-spacing:-.01em;line-height:1.15}
.cs-home h1 .ic{color:var(--accent-ink);flex:none}
.cs-sub{font-size:20px;color:var(--ink-2);margin:6px 0 22px}
.cs-chips{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:22px}
.cs-chip{display:inline-flex;align-items:center;gap:8px;background:var(--surface);color:var(--ink);border:1px solid var(--line-2);border-radius:999px;padding:9px 16px;font:500 14.5px var(--sans);cursor:pointer;text-decoration:none;text-align:left;max-width:100%}
.cs-chip:hover{border-color:var(--accent-ink);color:var(--accent-ink)}
.cs-chip .ic{color:var(--accent-ink);flex:none}
.cs-chip small{color:var(--faint);font-size:12px}
.cs-chip b{font-weight:650}
.cs-home .aimode{margin-top:22px}
/* prompt box */
.cs-ask{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--line-2);border-radius:999px;padding:6px 6px 6px 20px;box-shadow:var(--shadow)}
.cs-ask:focus-within{border-color:var(--accent-ink)}
.cs-ask input{flex:1;min-width:0;border:none;background:none;box-shadow:none;outline:none;font:inherit;font-size:16px;color:var(--ink);padding:10px 0}
.cs-ask.big{padding:8px 8px 8px 24px}
.cs-ask.big input{font-size:17px}
.cs-send{flex:none;width:38px;height:38px;border-radius:50%;border:none;background:var(--accent);color:var(--on-accent);cursor:pointer;display:flex;align-items:center;justify-content:center}
.cs-send:hover{background:var(--accent-hover)}
.cs-disc{font-size:12px;color:var(--faint);text-align:center;margin:8px 0 0}
/* conversation */
.cs-scroll{flex:1;padding:24px clamp(14px,4vw,40px) 8px;display:flex;flex-direction:column;gap:18px;max-width:900px;width:100%;margin:0 auto}
.cs-me{align-self:flex-end;max-width:82%;background:var(--accent-tint);color:var(--ink);border-radius:18px 18px 4px 18px;padding:10px 16px;font-size:15px;white-space:pre-wrap;word-wrap:break-word}
.cs-bot{display:flex;flex-direction:column;gap:12px;min-width:0}
.cs-text{font-size:15.5px;line-height:1.65;word-wrap:break-word;color:var(--ink)}
.cs-md p{margin:0 0 10px}.cs-md p:last-child{margin-bottom:0}
.cs-md ul,.cs-md ol{margin:4px 0 10px;padding-left:22px;display:flex;flex-direction:column;gap:4px}
.cs-md ul:last-child,.cs-md ol:last-child{margin-bottom:0}
.cs-md a{color:var(--info);font-weight:650}
.cs-md code{font-size:.92em;background:var(--sunk);border-radius:5px;padding:1px 5px}
.cs-live::after{content:"";display:inline-block;width:7px;height:15px;margin-left:3px;vertical-align:-2px;background:var(--accent-ink);opacity:.6;animation:csblink 1s steps(2) infinite}
@keyframes csblink{50%{opacity:0}}
.cs-err{font-size:13.5px;color:var(--bad)}
.cs-notice{font-size:12.5px;color:var(--muted);background:var(--sand);border-radius:8px;padding:6px 10px;align-self:flex-start}
.cs-stop{margin-left:8px}
/* memory page */
.cs-memory{padding:22px clamp(14px,4vw,40px) 40px;max-width:760px;width:100%;margin:0 auto}
.cs-memory h1{display:flex;align-items:center;gap:10px;font-family:var(--display);font-variation-settings:var(--dx);font-weight:650;font-stretch:88%;font-size:clamp(24px,3.6vw,32px);margin:6px 0 6px}
.cs-memory h1 .ic{color:var(--accent-ink)}
.cs-sub2{color:var(--ink-2);font-size:15px;line-height:1.6;margin:0 0 16px}
.cs-memlist{list-style:none;padding:0;margin:16px 0;display:flex;flex-direction:column;gap:8px}
.cs-memrow{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid var(--line-2);border-radius:12px;padding:10px 12px 10px 14px;background:var(--surface)}
.cs-memrow .f{font-size:15px;color:var(--ink)}
.cs-memrow .d{font-size:12.5px;color:var(--faint);margin-top:2px}
.cs-memrow .d a{color:var(--info)}
.cs-addmem{display:flex;gap:8px;align-items:center}
.cs-addmem input{flex:1;min-width:0}
.cs-clear>summary{list-style:none;display:inline-flex;cursor:pointer}
.cs-clear>summary::-webkit-details-marker{display:none}
.cs-clear[open]{border:1px solid var(--line-2);border-radius:12px;padding:12px}
.cs-clear p{font-size:14px;color:var(--ink-2)}
.cs-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.cs-job{position:relative;background:var(--surface);border:1px solid var(--line-2);border-radius:16px;padding:16px 18px;display:flex;flex-direction:column;gap:3px;min-width:0;transition:border-color .15s,box-shadow .15s}
.cs-job:hover{border-color:var(--accent-ink);box-shadow:var(--shadow)}
.cs-tags{display:flex;gap:6px;margin-bottom:4px}
.cs-tag{font-size:12px;font-weight:650;padding:2px 9px;border-radius:6px}
.cs-tag.ea{background:var(--info-tint);color:var(--info)}
.cs-tag.nw{background:var(--accent-tint);color:var(--accent-ink)}
.cs-title{font-family:var(--display);font-variation-settings:var(--dx);font-weight:650;font-stretch:88%;font-size:19px;line-height:1.25;color:var(--ink);text-decoration:none;overflow-wrap:anywhere}
.cs-title::after{content:"";position:absolute;inset:0;border-radius:16px}
.cs-co,.cs-loc{font-size:14.5px;color:var(--muted)}
.cs-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:center}
.cs-more>summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:6px;color:var(--info);font-weight:650;font-size:16px;padding:6px 4px;margin-bottom:8px}
.cs-more>summary::-webkit-details-marker{display:none}
.cs-more>summary .less,.cs-more[open]>summary .more{display:none}
.cs-more[open]>summary .less{display:inline}
.cs-more[open]>summary .ic{transform:rotate(180deg)}
/* qualifications */
.cs-quals{border-top:1px solid var(--whisper);padding-top:14px}
.cs-quals h3{font-family:var(--display);font-variation-settings:var(--dx);font-weight:650;font-stretch:88%;font-size:20px;margin:0 0 8px}
.cs-quals h3 small{display:block;font:500 13px var(--sans);color:var(--faint);margin-top:2px}
.cs-quals ul{list-style:none;padding:0;margin:10px 0;display:flex;flex-wrap:wrap;gap:8px}
.cs-quals li{display:inline-flex;align-items:center;gap:8px;background:var(--sunk);border-radius:8px;padding:6px 12px 6px 8px;font-size:14px;color:var(--muted);box-shadow:0 0 0 1px var(--whisper) inset}
.cs-quals li .mk{width:20px;height:20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex:none;background:var(--faint);color:var(--surface)}
.cs-quals li.met{color:var(--ink)}
.cs-quals li.met .mk{background:var(--ink);color:var(--surface)}
.cs-quals li.unk .mk{background:none;box-shadow:0 0 0 1.5px var(--faint) inset;color:var(--faint)}
.cs-note{font-size:14px;color:var(--ink-2)}
.cs-note a{color:var(--info);font-weight:650}
/* reply actions, follow-ups */
.cs-acts{display:flex;align-items:center;gap:4px}
.cs-ic{background:none;border:none;color:var(--muted);cursor:pointer;padding:7px;border-radius:8px;display:inline-flex;list-style:none}
.cs-ic::-webkit-details-marker{display:none}
.cs-ic:hover{background:var(--whisper);color:var(--ink)}
.cs-ic.on{color:var(--accent-ink);background:var(--accent-tint)}
.cs-copy{position:relative}
.cs-copy[open]{flex-basis:100%}
.cs-copy textarea{display:block;width:min(560px,80vw);margin-top:6px;font:14px/1.5 var(--sans);background:var(--sunk);color:var(--ink);border:1px solid var(--line-2);border-radius:10px;padding:10px;resize:vertical}
.cs-acts:has(.cs-copy[open]){flex-wrap:wrap}
.cs-follow{display:flex;flex-direction:column;align-items:flex-start;gap:10px;margin-top:6px}
.cs-follow .cs-chip{background:var(--sand);border-color:transparent;border-radius:18px;padding:11px 18px;font-size:15px}
.cs-follow .cs-chip:hover{border-color:var(--accent-ink)}
.cs-bar{position:sticky;bottom:0;background:linear-gradient(180deg,transparent,var(--surface) 22%);padding:10px clamp(14px,4vw,40px) 12px;max-width:900px;width:100%;margin:0 auto}
/* thinking */
.cs-think{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:15px}
.cs-think a{font-size:12.5px;color:var(--faint);margin-left:6px}
.cs-think .dots{display:inline-flex;gap:4px}
.cs-think .dots i{width:7px;height:7px;border-radius:50%;background:var(--accent-ink);opacity:.35;animation:csdot 1.1s infinite ease-in-out}
.cs-think .dots i:nth-child(2){animation-delay:.18s}.cs-think .dots i:nth-child(3){animation-delay:.36s}
@keyframes csdot{0%,80%,100%{opacity:.25;transform:scale(.8)}40%{opacity:1;transform:scale(1)}}
@media (prefers-reduced-motion:reduce){.cs-think .dots i{animation:none;opacity:.7}.cs-live::after{animation:none}}
@media(max-width:900px){
.cs{grid-template-columns:1fr;min-height:0}
.cs-top{top:0;border-radius:16px 16px 0 0}
.cs-ctx{border-left:none;border-top:1px solid var(--whisper);border-radius:0 0 16px 16px}
.cs-ctxd{position:static}
.cs-ctxd>summary{display:flex;align-items:center;gap:8px;cursor:pointer;padding:14px 16px;font-weight:650;font-size:14.5px;color:var(--ink)}
.cs-ctxd>summary .ic{color:var(--accent-ink)}
.cs-ctx-in{max-height:none;padding-top:4px}
.cs-home{padding:28px 14px}
}
@media(max-width:620px){.cs-grid{grid-template-columns:1fr}.cs-me{max-width:92%}.cs-sub{font-size:17px}}
"""
