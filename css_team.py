"""Styles for team accounts (teams.py): the /team page, the company page's Team card and the sender line on
company messages. Appended to ui.CSS when teams.py is imported, like css_hiring and css_msg, so ui.py stays
untouched. Only the site's variables are used, so dark mode follows the rest of the site."""

import ui

CSS = """
/* ---------- team accounts ---------- */
.tm-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}
.tm-main,.tm-side{display:grid;gap:14px;min-width:0}
.tm-list .phead,.tm-card .phead{display:flex;justify-content:space-between;align-items:baseline}
.tm-rows{list-style:none;margin:6px 0 0;padding:0}
.tm-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;grid-template-areas:"av who badge" "av acts acts";gap:4px 12px;align-items:center;padding:12px 0;border-top:1px solid var(--whisper)}
.tm-row:first-child{border-top:0}
.tm-row>.avatar{grid-area:av;align-self:start}
.tm-who{grid-area:who;display:flex;flex-direction:column;min-width:0}
.tm-who b{font-weight:600}
.tm-who span{overflow-wrap:anywhere;font-size:13.5px;color:var(--muted)}
.tm-who .faint{color:var(--faint)}
.tm-badge{grid-area:badge}
.tm-acts{grid-area:acts;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.tm-acts:empty{display:none}
.tm-role{display:flex;gap:6px;align-items:center;margin:0}
.tm-role select{padding:5px 8px;font-size:13.5px}
.tm-xfer summary{list-style:none;cursor:pointer}
.tm-xfer summary::-webkit-details-marker{display:none}
.tm-xfer form{margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;max-width:360px}
.tm-invite h2,.tm-me h2,.tm-leave h2{font-size:17px;margin:0 0 6px}
.tm-invite>p,.tm-me>p,.tm-leave>p{margin-bottom:12px}
.tm-invite .hint{font-size:12.5px;color:var(--faint);margin-top:6px}
.tm-people{list-style:none;margin:6px 0 10px;padding:0;display:grid;gap:10px}
.tm-pick{list-style:none;padding:0;display:grid;gap:8px;max-width:520px}
.tm-join{max-width:620px}
.bad-t{color:var(--bad)}
.bubble .sender{display:block;font-size:11.5px;font-weight:600;opacity:.78;margin-bottom:3px;letter-spacing:.01em}
@media(max-width:900px){.tm-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:520px){.tm-row{grid-template-columns:auto minmax(0,1fr);grid-template-areas:"av who" "av badge" "acts acts"}
  .tm-acts{padding-top:4px}}
"""

if "/* ---------- team accounts" not in ui.CSS:
    ui.CSS += CSS
