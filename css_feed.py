"""Styles for the redesigned community feed (feed.py and the demo's P.feed).

Appended to ui.CSS when this module is imported, so the shared stylesheet in ui.py stays untouched.
Only the site's own variables are used, so dark mode (and the demo's light/dark switch) come for free.
"""
import ui

CSS = """
/* ---------- feed (Handshake-style layout: tabs, pills, composer, cards, right rail) ---------- */
.fd-tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:4px 0 18px}
.fd-tabs a{position:relative;padding:12px 14px;font-weight:600;font-size:15px;color:var(--muted);text-decoration:none}
.fd-tabs a:hover{color:var(--ink)}
.fd-tabs a[aria-current=page]{color:var(--ink)}
.fd-tabs a[aria-current=page]::after{content:"";position:absolute;left:8px;right:8px;bottom:-1px;height:2px;border-radius:2px;background:var(--accent)}
.fd-grid{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:22px;align-items:start}
.fd-main{min-width:0;max-width:640px;width:100%;margin:0 auto}
.fd-rail{display:flex;flex-direction:column;gap:14px;position:sticky;top:76px}
.fd-pills{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.fd-pill{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink-2);font-size:14px;font-weight:500;text-decoration:none}
.fd-pill:hover{background:var(--sunk)}
.fd-pill[aria-current=true]{background:var(--sunk);border-color:var(--line-2);color:var(--ink);font-weight:600}
.fd-comp{background:var(--surface);border:1px solid var(--whisper);border-radius:14px;margin-bottom:14px}
.fd-comp>summary{list-style:none;display:flex;align-items:center;gap:12px;padding:12px 14px;cursor:pointer;color:var(--muted);font-size:15px}
.fd-comp>summary::-webkit-details-marker{display:none}
.fd-comp>summary:hover{color:var(--ink)}
.fd-comp[open]>summary{border-bottom:1px solid var(--whisper);color:var(--ink-2)}
.fd-comp .composer-card{border:0;margin:0;border-radius:0 0 14px 14px;background:none}
.fd-post{padding:14px 16px 8px}
.fd-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.fd-meta{display:flex;align-items:center;gap:6px;flex:none}
.fd-time{font-size:13px;color:var(--faint);white-space:nowrap}
.fd-save{margin:0}
.fd-save button{background:none;border:0;padding:6px;border-radius:8px;color:var(--muted);cursor:pointer;display:inline-flex}
.fd-save button:hover{background:var(--whisper);color:var(--ink)}
.fd-save button[aria-pressed=true]{color:var(--accent-ink)}
.fd-save svg{display:block}
.fd-tag{font-size:11px;padding:2px 8px}
.fd-card{background:var(--surface);border:1px solid var(--whisper);border-radius:14px;padding:14px 16px}
.fd-card h3{font-size:15px;font-weight:650;margin:0 0 10px}
.fd-person{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 0;border-top:1px solid var(--whisper)}
.fd-person:first-of-type{border-top:0}
.fd-person .person .avatar{width:34px;height:34px;font-size:14px}
.fd-person .navform{margin:0}
.fd-why{font-size:12px;color:var(--faint);margin-top:2px}
.fd-topics{display:flex;flex-wrap:wrap;gap:6px}
.fd-topics a{font-size:13px;padding:4px 10px;border-radius:999px;background:var(--sunk);color:var(--ink-2);text-decoration:none;box-shadow:0 0 0 1px var(--whisper) inset}
.fd-topics a:hover{color:var(--ink)}
.fd-topics small{color:var(--faint);margin-left:4px}
.fd-rules{margin:0;padding-left:18px;font-size:13.5px;color:var(--muted);line-height:1.55}
.fd-empty{text-align:center;padding:56px 20px;background:var(--surface);border:1px dashed var(--line-2);border-radius:14px;color:var(--muted)}
.fd-empty svg{color:var(--faint);margin-bottom:10px}
.fd-empty h2{font-size:18px;color:var(--ink);margin:0 0 6px}
.fd-empty p{margin:0 auto 14px;max-width:34ch;font-size:14.5px}
.fd-note{font-size:13.5px;color:var(--muted);margin:-4px 0 12px}
@media (max-width:900px){.fd-grid{grid-template-columns:minmax(0,1fr)}.fd-rail{display:none}.fd-main{max-width:none}}
@media (max-width:520px){.fd-tabs a{padding:11px 10px;font-size:14px}.fd-post{padding:12px 12px 6px}.fd-pill{padding:6px 12px;font-size:13.5px}}
"""

if "/* ---------- feed (Handshake-style layout" not in ui.CSS:
    ui.CSS += CSS
