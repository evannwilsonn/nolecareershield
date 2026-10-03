"""Styles for events (events.py and the demo's event pages).

Appended to ui.CSS when this module is imported, like css_feed. Only the site's own variables are used, so dark mode
(and the demo's light/dark switch) come for free. The date block is the one visual signature: a garnet month band
over a big day number, used in lists, on the event page and in the feed's avatar gutter.
"""
import ui

CSS = """
/* ---------- events (date block, list rows, event page, feed cards) ---------- */
.ev-date{flex:none;display:inline-flex;flex-direction:column;align-items:center;width:52px;border-radius:10px;overflow:hidden;background:var(--surface);box-shadow:0 0 0 1px var(--line-2) inset;line-height:1;text-align:center}
.ev-date small{display:block;width:100%;background:var(--accent);color:var(--on-accent);font-size:10.5px;font-weight:700;letter-spacing:.09em;padding:4px 0 3px}
.ev-date b{display:block;font-family:var(--display);font-variation-settings:var(--dx);font-stretch:85%;font-size:23px;font-weight:700;color:var(--ink);padding:5px 0 1px}
.ev-date i{display:block;font-style:normal;font-size:10.5px;color:var(--muted);padding:0 0 5px;text-transform:uppercase;letter-spacing:.06em}
.ev-kind{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap}
.ev-kind::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--line-2)}
.ev-kind.k-info_session::before{background:var(--accent)}.ev-kind.k-career_fair::before{background:var(--gold)}
.ev-kind.k-workshop::before{background:var(--ok)}.ev-kind.k-coffee_chat::before{background:var(--info)}
.ev-filters{margin:0 0 18px}
.ev-filters .filter-row{row-gap:6px}
.ev-sec{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:22px 0 10px}
.ev-list{display:grid;gap:10px}
.ev-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px 16px;background:var(--surface);border:1px solid var(--whisper);border-radius:12px;text-decoration:none;color:inherit;transition:box-shadow .15s,border-color .15s}
.ev-row:hover{border-color:color-mix(in srgb,var(--accent-ink) 40%,transparent);box-shadow:var(--shadow)}
.ev-main{min-width:0;display:flex;flex-direction:column;gap:2px}
.ev-title{font-size:16px;font-weight:650;color:var(--ink);line-height:1.3;overflow-wrap:anywhere}
.ev-co{font-size:14px;color:var(--ink-2)}
.ev-co a{color:inherit}
.ev-meta{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.ev-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.ev-tags .chip{font-size:11.5px}
.ev-side{display:flex;flex-direction:column;align-items:flex-end;gap:6px;text-align:right}
.ev-n{font-size:12.5px;color:var(--muted);white-space:nowrap}.ev-n b{color:var(--ink);font-size:15px}
.ev-list.tight{gap:8px}.ev-list.tight .ev-row{padding:10px 12px;box-shadow:none}
.ev-empty{padding:32px;text-align:center}
.ev-rsvp{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.ev-rsvp .b[aria-pressed=true]{box-shadow:0 0 0 1px var(--ink-2) inset}
.ev-consent{flex-basis:100%;font-size:12px;color:var(--faint);line-height:1.4}
.ev-hero{display:flex;gap:18px;align-items:center;margin-bottom:14px;padding:20px 22px}
.ev-hero .ev-date{width:66px}.ev-hero .ev-date b{font-size:30px}
.ev-hero-t{min-width:0}
.ev-hero h1{font-family:var(--display);font-variation-settings:var(--dx);font-stretch:82%;font-weight:700;font-size:clamp(24px,4vw,32px);line-height:1.08;margin:6px 0 4px;overflow-wrap:anywhere}
.ev-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:start}
.ev-mainc{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;min-width:0}
.ev-aside{position:sticky;top:76px;display:grid;gap:14px}
.ev-act .ev-rsvp .b:first-child{flex:1 1 auto}
.ev-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px 18px}
.ev-fact{display:flex;gap:10px;align-items:flex-start;min-width:0}
.ev-fact .ic{color:var(--accent-ink);margin-top:2px}
.ev-fact small{display:block;font-size:11.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
.ev-fact span{font-size:14.5px;overflow-wrap:anywhere}
.ev-h{font-size:17px;margin:0 0 8px}
.ev-desc{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;margin:0 0 14px}
.ev-join{margin-top:14px;padding-top:14px;border-top:1px solid var(--whisper)}
.ev-join small{display:block;font-size:11.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--faint);margin-bottom:6px}
.ev-url{display:block;font-size:12.5px;background:var(--sunk);padding:6px 8px;border-radius:6px;overflow-wrap:anywhere}
.ev-tablewrap{overflow-x:auto;margin:0 -4px}
.ev-tablewrap .t{min-width:520px}
.ev-form fieldset.ev-fs{border:0;padding:0;margin:0 0 6px;min-width:0}
.ev-form legend{font-size:14px;font-weight:600;margin-bottom:8px;padding:0}
.ev-when{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:0 14px}
.lbl-like{display:block;font-size:14px;font-weight:600;margin-bottom:7px}
/* the feed's event card: date block in the avatar gutter, a soft gold-edged card for the body */
.fd-ev .fd-gut .ev-date{position:relative;z-index:1;width:44px;box-shadow:0 0 0 1px var(--line-2) inset,0 0 0 4px var(--canvas)}
.fd-ev .fd-gut .ev-date b{font-size:19px;padding:4px 0 0}.fd-ev .fd-gut .ev-date i{font-size:9.5px;padding-bottom:4px}
.fd-ev .fd-body{padding:12px 14px 12px;margin:10px 0;border:1px solid color-mix(in srgb,var(--gold) 55%,var(--line));border-left:3px solid var(--gold);border-radius:12px;background:color-mix(in srgb,var(--gold-tint) 45%,var(--surface))}
.fd-ev+.fd-post .fd-body{border-top:0}
.ev-card-t{display:block;font-size:16.5px;font-weight:650;color:var(--ink);text-decoration:none;margin:4px 0 2px;overflow-wrap:anywhere}
.ev-card-t:hover{text-decoration:underline}
.ev-card-m{font-size:13px;color:var(--muted);margin:0 0 10px;overflow-wrap:anywhere}
.ev-card-m .ic{display:inline-block;vertical-align:-2px;margin-right:3px;color:var(--gold-ink)}
.ev-card-a{display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap}
.ev-card-a .ev-rsvp{flex:1 1 220px}
.ev-more{font-size:13px;font-weight:600;color:var(--accent-ink);text-decoration:none;padding:6px 0}
.ev-more:hover{text-decoration:underline}
@media (max-width:860px){.ev-grid{grid-template-columns:minmax(0,1fr)}.ev-aside{position:static;order:-1}}
@media (max-width:620px){
  .ev-row{grid-template-columns:auto minmax(0,1fr);padding:12px 13px;gap:12px}
  .ev-side{grid-column:2;flex-direction:row;align-items:center;justify-content:flex-start;text-align:left;flex-wrap:wrap}
  .ev-when{grid-template-columns:1fr 1fr}.ev-when .form-field:first-child{grid-column:1/-1}
  .ev-hero{padding:16px;gap:14px}.ev-hero .ev-date{width:56px}.ev-hero .ev-date b{font-size:25px}
  .fd-ev .fd-body{padding:11px 12px}
  .ev-tablewrap{overflow:visible;margin:0}
  .ev-tablewrap .t,.ev-tablewrap .t tbody{display:block;min-width:0;width:100%}
  .ev-tablewrap .t tr:first-child{display:none}
  .ev-tablewrap .t tr{display:flex;flex-wrap:wrap;align-items:center;gap:3px 10px;padding:10px 0;border-bottom:1px solid var(--whisper)}
  .ev-tablewrap .t td{border:0;padding:0;font-size:13.5px;color:var(--muted)}
  .ev-tablewrap .t td:first-child{flex-basis:100%;color:var(--ink);font-size:14.5px}
  .ev-tablewrap .t td:last-child{margin-left:auto}
}
"""

if "/* ---------- events (date block" not in ui.CSS:
    ui.CSS += CSS
