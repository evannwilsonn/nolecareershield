"""Markup for the public pages in the elite look: the "Enter the vault" sign-in pages and the logged-out landing
blocks (sample report, how it works, scam-check teaser, employer call to action). Styles are in css_public.py.

Everything here is shared with the demo: demo/build.py renders these blocks with the demo's links, and
demo/app.js has a twin of vault_card() (vaultCard) that wraps the demo's own forms. Every claim is one the site can
back up: a person reviews every listing and employer, students need a confirmed @fsu.edu address, nobody pays to
apply, and the sample report is the real detector's output on a made-up listing."""

from __future__ import annotations

import css_public  # noqa: F401  (appends the public-page styles after ui.THEME_CSS)
import ui
from ui import esc

# ---------- the sign-in pages ----------

SEALS = {
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "mail": '<rect x="3.5" y="6" width="17" height="12.5" rx="2"/><path d="m4.5 7.5 7.5 6 7.5-6"/>',
    "key": '<circle cx="8.5" cy="12" r="3.8"/><path d="M12.3 12H20.5M17.5 12v3M20 12v2.2"/>',
    "check": '<path d="m6 12.5 4 4 8-9"/>',
    "alert": '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.2M12 16.8v.2"/>',
}


def seal(icon: str = "lock") -> str:
    """The garnet seal with a gold ring that sits on the card's top edge."""
    return (f'<div class="vx-seal" aria-hidden="true"><svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#F6DE9E" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" focusable="false">{SEALS.get(icon, SEALS["lock"])}</svg></div>')


PILLARS = {
    "student": (("100%", "Human-reviewed"), ("0", "Pay-to-apply"), ("@fsu.edu", "Members only")),
    "employer": (("100%", "Human-reviewed"), ("@fsu.edu", "Confirmed students"), ("0-100", "Trust score")),
}
_EYEBROW = {"student": "// Florida State University · private access", "employer": "// Employer access · verified organizations"}
_LEDE = {
    "student": ("A private job board for Florida State students. Every employer is verified, every listing is scanned for "
                "scam signals, and a person approves it before it ever reaches you."),
    "employer": ("Hire Florida State students on a board they trust. Every student is a confirmed @fsu.edu account, and every "
                 "employer and listing is reviewed by a person before students see it."),
}


def pillars(role: str = "student") -> str:
    cells = "".join(f"<div><b>{esc(n)}</b>{esc(label)}</div>" for n, label in PILLARS[role])
    return f'<div class="vx-pillars">{cells}</div>'


def vault_aside(role: str = "student") -> str:
    """The left column: gold crest, mono eyebrow, the headline, a truthful lede and the pillars box."""
    role = "employer" if role == "employer" else "student"
    return (f'<div class="vx-l">{ui.crest(72, key="vx-" + role)}<div class="eyebrow">{esc(_EYEBROW[role])}</div>'
            f'<h1 class="vx-h">The inner circle<br>for <em>FSU</em> careers.</h1><p>{esc(_LEDE[role])}</p>{pillars(role)}</div>')


def fine_print(items: list[str]) -> str:
    """The row under the card. Only claims the site can back up go here (see app._vault_fine)."""
    if not items:
        return ""
    spans = "".join(f"<span>{'<i class=led></i>' if i == 0 else ''}{esc(t)}</span>" for i, t in enumerate(items))
    return f'<div class="vx-fine">{spans}</div>'


def vault_card(title: str, body: str, *, kicker: str = "", sub: str = "", icon: str = "lock", fine: str = "") -> str:
    """The sign-in card. `title` and `sub` are HTML (callers escape); `body` holds the form."""
    k = f'<div class="vx-kick">{esc(kicker)}</div>' if kicker else ""
    s = f'<p class="vx-sub">{sub}</p>' if sub else ""
    return f'<div class="vx-card">{seal(icon)}{k}<h2 class="vx-title">{title}</h2>{s}<div class="vx-body">{body}</div>{fine}</div>'


def vault(card: str, role: str = "student") -> str:
    """The whole page section: void-to-navy background with the faint gold grid, the aside and the card."""
    return f'<section class="vx" aria-label="Sign in"><div class="vx-in">{vault_aside(role)}{card}</div></section>'


def email_field(value: str = "", *, label: str = "Email", hint: str = "", verified: bool = False, fid: str = "f-email",
                placeholder: str = "", autofocus: bool = False) -> str:
    """An email field with a hint at its right edge. `verified` shows the green check: only for a value the server has
    already checked is an @fsu.edu address (for example on the re-render after a wrong password)."""
    tip = ('<span class="vx-hint ok" id="{0}-hint">✓ FSU.EDU VERIFIED</span>' if verified
           else '<span class="vx-hint" id="{0}-hint">{1}</span>' if hint else "").format(fid, esc(hint))
    desc = f' aria-describedby="{fid}-hint"' if tip else ""
    ph = f' placeholder="{esc(placeholder)}"' if placeholder else ""
    return (f'<div class="form-field"><label for="{fid}">{esc(label)}</label><div class="vx-inp{" hinted" if tip else ""}">'
            f'<input id="{fid}" type="email" name="email" required maxlength="254" autocomplete="username"{ph} '
            f'value="{esc(value)}"{desc}{" autofocus" if autofocus else ""}>{tip}</div></div>')


# ---------- the logged-out landing ----------

LINKS = {**ui.SITE_LINKS, "employers": 'href="/employers"'}

_LEVEL = {"block": "Threat level · critical", "review": "Threat level · high", "caution": "Threat level · caution", "clear": "No threat found"}


def sample_report() -> str:
    """The scan report as a still illustration, clearly a sample: the real detector's output (ui.scan_findings, the
    same code as the public scam check) on the made-up listing in ui.SCAN_SAMPLE. Nothing in it is written by hand."""
    s, r = ui.SCAN_SAMPLE, ui.scan_findings()
    fs = r["findings"]
    phrase = lambda f: r["text"][f["spans"][0][0]:f["spans"][0][1]] if f["spans"] else ""
    crit = [f for f in fs if f["severity"] == "critical"]
    ev = "".join(f'<li class="{"crit" if f["severity"] == "critical" else "warn"}"><span class="px-k">{"Critical" if f["severity"] == "critical" else "Warning"}</span>'
                 f'<b>{esc(f["title"])}</b><code>"{esc(phrase(f))}"</code></li>' for f in (crit + [f for f in fs if f not in crit])[:3])
    # Radar blips: the shortest phrases the detector caught (two critical, one warning), where they fit on the scope.
    by_len = sorted((f for f in fs if phrase(f)), key=lambda f: len(phrase(f)))
    short = ([f for f in by_len if f["severity"] == "critical"][:2] + [f for f in by_len if f["severity"] != "critical"][:1]
             + by_len)[:3]
    spots = (("16%", "30%"), ("28%", "72%"), ("56%", "16%"))    # labels run right, so they stay on the scope
    blips = "".join(f'<span class="px-blip{"" if f["severity"] == "critical" else " px-a"}" style="left:{x};top:{y}"><small>{esc(phrase(f).upper())}</small></span>'
                    for f, (x, y) in zip(short, spots))
    lit = max(1, min(10, round(r["score"] / 10)))
    lvl = "".join(f'<i{" class=on" if i < lit else ""}></i>' for i in range(10))
    n = len(fs)
    return f"""<figure class="px-hud" aria-label="Sample report: what the scam check found in a made-up listing">
<i class="px-corner px-c1"></i><i class="px-corner px-c2"></i><i class="px-corner px-c3"></i><i class="px-corner px-c4"></i>
<div class="px-hh"><span>Sample report</span><span>Made-up listing</span></div>
<div class="px-ht">{esc(s["title"])}</div><div class="px-hs">{esc(s["company"])} · read by the real scam check</div>
<div class="px-mid"><div class="px-radar" aria-hidden="true"><div class="px-tick"></div><div class="px-ring px-r1"></div><div class="px-ring px-r2"></div><div class="px-ring px-r3"></div>
<div class="px-cross"></div><div class="px-beam"></div>{blips}<div class="px-core">{ui.crest(34, key="hud")}</div></div>
<div class="px-threat"><div class="px-tnum"><b>{r["score"]}</b><small>Risk / 100</small></div>
<div class="px-tlv">▲ {esc(_LEVEL.get(r["band"], "Threat level"))}</div><div class="px-tcls">{esc(r["title"])}</div>
<div class="px-lvl" aria-hidden="true">{lvl}</div><div class="px-tmeta">Matched <b>{n} signal{"s" if n != 1 else ""}</b></div></div></div>
<div class="px-sech"><span>Evidence</span><span>Exact matches</span></div><ul class="px-ev">{ev}</ul>
<figcaption>{esc(r["advice"])}</figcaption></figure>"""


def proof(links: dict | None = None) -> str:
    """How it works (scan, then a person, then the verified gallery) next to the sample report."""
    L = {**LINKS, **(links or {})}
    steps = (("01", "Scan", f"Every listing is read for {ui.RULE_COUNT} scam patterns: fake checks, gift-card pay, look-alike school emails and more."),
             ("02", "Human review", "Then a professional approves it. Nothing reaches the board on a score alone."),
             ("03", "Verified gallery", "Only then is it shown, to signed-in FSU students, from employers a person has reviewed."))
    lis = "".join(f'<li><span class="n">{n}</span><div><b>{esc(t)}</b><p>{esc(p)}</p></div></li>' for n, t, p in steps)
    return f"""<section class="px-proof" aria-labelledby="px-proof-h"><div class="px-in">
<div class="px-copy"><div class="eyebrow">// How a listing reaches you</div>
<h2 class="display" id="px-proof-h">Scanned. Reviewed.<br><em>Then</em> it's yours.</h2>
<ol class="px-steps">{lis}</ol>
<div class="cta"><a class="primary" {L["join"]}>Enter the vault</a><a class="secondary" {L["check"]}>Try the scam check</a></div></div>
{sample_report()}</div></section>"""


def check_teaser(links: dict | None = None) -> str:
    """The public scam check, in one card: anyone can use it, no account."""
    L = {**LINKS, **(links or {})}
    return f"""<section class="px-check" aria-labelledby="px-check-h"><div class="px-card">
<div><div class="eyebrow">// Free scam check · no account</div><h2 id="px-check-h">Got an offer that feels <em>off?</em></h2>
<p>Paste a job listing or a message you got anywhere. Visitors get the verdict and the main reasons, up to 10 checks a day. FSU students see every signal and the exact words it caught.</p></div>
<div class="px-acts"><a class="px-btn gold" {L["check"]}>Check a listing</a><a class="px-btn" {L["check_msg"]}>Check a message</a></div></div></section>"""


def employer_cta(links: dict | None = None) -> str:
    """The employer call to action at the foot of the student landing."""
    L = {**LINKS, **(links or {})}
    return f"""<section class="px-emp" aria-labelledby="px-emp-h"><div class="px-card">{ui.crest(44, key="emp-cta")}
<div><div class="eyebrow">// Employer access · verified organizations</div><h2 id="px-emp-h">Hiring FSU students? <em>Get verified.</em></h2>
<p>A person reviews your organization before you can post or message. Then every listing is scanned and approved, and shown with your trust score.</p></div>
<div class="px-acts"><a class="px-btn gold" {L["employers"]}>For employers</a><a class="px-btn" {L["emp_signup"]}>Create an employer account</a></div></div></section>"""


def employer_vault(links: dict | None = None) -> str:
    """The closing band on /employers, in the vault style."""
    L = {**LINKS, **(links or {})}
    return f"""<section class="px-emp vaultish" aria-labelledby="px-ev-h"><div class="px-card">{ui.crest(44, key="emp-vault")}
<div><div class="eyebrow">// Employer access · verified organizations</div><h2 id="px-ev-h">Enter the <em>employer</em> vault.</h2>
<p>Create an account with your work email. A person checks your organization, usually within a business day, and your ranked matches are ready as soon as a listing goes live.</p>{pillars("employer")}</div>
<div class="px-acts"><a class="px-btn gold" {L["emp_signup"]}>Create an employer account</a><a class="px-btn" {L["emp_login"]}>Employer log in</a></div></div></section>"""
