"""Styles for interview scheduling and message templates (scheduling.py, msg_templates.py and the demo's messages).

Appended to ui.CSS when this module is imported (messaging.py imports it), so ui.py stays untouched.
Only the site's own variables are used, so dark mode (and the demo's light/dark switch) come for free.
"""
import ui

CSS = """
/* ---------- messages: interview cards, upcoming list, templates ---------- */
.iv-card{align-self:stretch;max-width:520px;width:100%;margin:4px auto;background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--gold);border-radius:12px;padding:14px 16px;box-shadow:0 1px 0 var(--whisper)}
.iv-card.iv-ok{border-left-color:var(--ok)}
.iv-card.iv-muted{opacity:.72;padding:10px 14px}
.iv-top{display:flex;align-items:center;gap:10px}
.iv-ic{flex:none;display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:var(--gold-tint);color:var(--gold-ink)}
.iv-ok .iv-ic{background:var(--ok-tint);color:var(--ok)}
.iv-h{flex:1;min-width:0;display:flex;flex-direction:column;line-height:1.3}
.iv-h b{font-size:15px;color:var(--ink)}
.iv-sub{font-size:12.5px;color:var(--muted)}
.iv-when{margin:12px 0 0;font-family:var(--display);font-variation-settings:var(--dx);font-weight:700;font-stretch:84%;font-size:22px;line-height:1.15;color:var(--ink)}
.iv-strike{text-decoration:line-through;color:var(--muted)}
.iv-slots{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-direction:column;gap:6px}
.iv-pick{margin:0}
.iv-slot{width:100%;display:flex;align-items:center;gap:10px;flex-wrap:wrap;text-align:left;padding:10px 12px;border-radius:10px;border:1px solid var(--line-2);background:var(--canvas);color:var(--ink);font:inherit;font-size:14px}
button.iv-slot{cursor:pointer;transition:border-color .15s,background .15s}
button.iv-slot:hover,button.iv-slot:focus-visible{border-color:var(--accent-ink);background:var(--accent-tint)}
.iv-slot.past{opacity:.55}
.iv-d{font-weight:650;min-width:92px}
.iv-t{color:var(--ink-2);flex:1;min-width:0}
.iv-go{margin-left:auto;font-size:13px;font-weight:650;color:var(--accent-ink)}
button.iv-slot .iv-go{background:var(--accent);color:var(--on-accent);border-radius:7px;padding:4px 11px}
.iv-loc,.iv-msg{margin:10px 0 0;font-size:14px;color:var(--ink-2);overflow-wrap:anywhere;white-space:pre-wrap}
.iv-k{display:inline-block;font-size:11.5px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-right:4px}
.iv-loc a{color:var(--accent-ink);font-weight:600}
.iv-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start;margin-top:12px}
.iv-acts .navform{margin:0}
.iv-none{flex-basis:100%}
.iv-none>summary{list-style:none;cursor:pointer;display:inline-flex}
.iv-none>summary::-webkit-details-marker{display:none}
.iv-none form{margin-top:8px;display:flex;flex-direction:column;gap:8px}
.iv-none label{font-size:13px;margin:0}
.iv-none textarea{min-height:64px}
.iv-none button{align-self:flex-start}
.iv-sys{align-self:center;display:inline-flex;align-items:center;gap:6px;max-width:92%;font-size:12.5px;color:var(--muted);background:var(--sunk);border-radius:999px;padding:4px 12px;text-align:center}
.iv-sys .ic{flex:none;color:var(--gold-ink)}
.iv-up{margin:0 0 16px;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.iv-up h2{display:flex;align-items:center;gap:7px;margin:0 0 8px;font-size:14px;font-weight:650;letter-spacing:.02em;color:var(--ink)}
.iv-up h2 .ic{color:var(--accent-ink)}
.iv-up ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.iv-up li{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:var(--canvas)}
.iv-up-main{flex:1;min-width:0;display:flex;flex-direction:column;text-decoration:none;color:var(--ink)}
.iv-up-when{font-weight:650;font-size:14px}
.iv-up-who{font-size:12.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.iv-up-main:hover .iv-up-when{color:var(--accent-ink)}
.msg-tools{display:flex;justify-content:flex-end;margin:-6px 0 12px}
/* propose form */
.iv-form{max-width:720px}
.iv-tz{display:flex;align-items:center;gap:7px;margin:0 0 14px;font-size:13.5px;color:var(--gold-ink);background:var(--gold-tint);border-radius:9px;padding:8px 12px}
.iv-row{border:0;padding:0;margin:0 0 12px;display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,.9fr);gap:10px;align-items:end}
.iv-row legend{grid-column:1/-1;font-size:13px;font-weight:650;color:var(--muted);padding:0;margin-bottom:6px}
.iv-row label{font-size:12.5px;font-weight:600;color:var(--ink-2)}
.iv-form .lbl{display:block;font-size:14px;font-weight:600;margin-bottom:7px}
/* templates */
.tpl-bar{padding:8px 12px 0;background:var(--surface);border-top:1px solid var(--whisper)}
.tpl-bar+.composer{border-top:0}
.tpl-pick>summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--accent-ink);padding:4px 10px;border-radius:999px;box-shadow:0 0 0 1px var(--line-2) inset}
.tpl-pick>summary::-webkit-details-marker{display:none}
.tpl-pick>summary:hover,.tpl-pick[open]>summary{box-shadow:0 0 0 1px var(--accent-ink) inset;background:var(--accent-tint)}
.tpl-list{list-style:none;margin:8px 0 0;padding:4px;max-height:230px;overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.tpl-list a{display:flex;flex-direction:column;gap:1px;padding:8px 10px;border-radius:8px;text-decoration:none;color:var(--ink)}
.tpl-list a:hover,.tpl-list a:focus-visible{background:var(--sunk)}
.tpl-list b{font-size:13.5px;font-weight:650}
.tpl-list span{font-size:12.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tpl-empty{padding:8px 10px;font-size:13px;color:var(--muted)}
.tpl-manage{display:inline-block;margin:6px 2px 4px;font-size:12.5px;color:var(--muted)}
.form-field .tpl-pick{margin:0 0 8px}
.tpl-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,380px);gap:20px;align-items:start}
.tpl-cards{display:flex;flex-direction:column;gap:10px;min-width:0}
.tpl-card{background:var(--surface);border:1px solid var(--line);border-radius:12px}
.tpl-card>details>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:13px 16px}
.tpl-card>details>summary::-webkit-details-marker{display:none}
.tpl-t{font-weight:650;font-size:15px;color:var(--ink)}
.tpl-b{grid-column:1;font-size:13px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tpl-edit{grid-column:2;grid-row:1/3;align-self:center;font-size:13px;font-weight:600;color:var(--accent-ink)}
.tpl-card>details[open]>summary{border-bottom:1px solid var(--whisper)}
.tpl-card>details[open] .tpl-edit{visibility:hidden}
.tpl-card form{padding:12px 16px 0}
.tpl-card form.tpl-del{padding:0 16px 14px;margin-top:-38px;display:flex;justify-content:flex-end}
.tpl-new h2{margin:0 0 12px;font-size:17px}
.tpl-count{margin:0 0 12px}
.page-head code,.tpl-new code{font-size:.92em;background:var(--sunk);border-radius:5px;padding:1px 5px}
@media(max-width:900px){.tpl-grid{grid-template-columns:1fr}}
@media(max-width:620px){.iv-row{grid-template-columns:1fr 1fr}.iv-row>div:first-of-type{grid-column:1/-1}
  .iv-card{padding:12px}.iv-when{font-size:19px}.iv-d{min-width:0}.iv-up li{flex-wrap:wrap}.iv-up-who{white-space:normal}
  .tpl-card form.tpl-del{margin-top:0;justify-content:flex-start}}
"""

if "/* ---------- messages: interview cards" not in ui.CSS:
    ui.CSS += CSS
