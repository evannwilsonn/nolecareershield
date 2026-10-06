"""
"Is this message a scam?" for students.

Paste a text, email, LinkedIn/Handshake DM or in-app message and get one of four verdicts,
with the evidence behind it and what to do next:

    0 ok       No known scam signs      (still verify the employer yourself)
    1 caution  Be careful               (something is off; verify before replying)
    2 warn     Likely a scam            (several strong signals; don't send anything)
    3 bad      Scam. Stop here.         (a pattern that only scams use)

How the verdict is made, so it is consistent:
  1. The rule-based scam detector scores the text (same rules and bands as job listings).
  2. The sender address and every link are checked: FSU look-alike domains, personal email
     claiming to be a school or company, link shorteners, chat-app links, raw IP links.
  3. Optional AI second opinion (signed-in users, when configured). It can only ADD caution:
     the rules are a floor the model can never lower. Same text in, same rule verdict out.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

import ai
import security
import store
import ui
import web
from scam_detector.rules import FREE_MAIL
from scam_detector.scorer import score_posting
from scam_detector import ml
import learning
import defense
import metrics

router = APIRouter()

LEVELS = [
    ("ok", "No known scam signs", "Nothing here matches a known scam pattern. That isn't a guarantee: confirm the employer through their own website or the FSU Career Center before sharing personal details."),
    ("caution", "Be careful", "A few things are off. Verify the sender through an official channel you find yourself before you reply or click anything."),
    ("warn", "Likely a scam", "Several strong scam signals. Don't reply with personal information, don't click links, and don't send or accept money."),
    ("bad", "Scam. Stop here.", "This matches patterns that only scams use. Don't respond, don't click links, and never send money, gift cards, or bank details."),
]
BAND_LEVEL = {"clear": 0, "caution": 1, "review": 2, "block": 3}

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "rb.gy", "cutt.ly", "shorturl.at", "is.gd", "ow.ly", "buff.ly", "tiny.cc",
              "rebrand.ly", "s.id", "t.ly", "lnkd.in", "shorturl.com", "bl.ink", "short.io"}
CHAT_LINKS = {"wa.me", "chat.whatsapp.com", "t.me", "telegram.me", "signal.me", "m.me", "discord.gg"}
FORM_HOSTS = {"forms.gle", "docs.google.com", "forms.office.com", "jotform.com", "typeform.com"}
CLAIMS_SCHOOL = re.compile(r"\b(?:professor|prof\.|dr\.|department|dept\.?|university|career (?:center|services)|"
                           r"fsu|florida state|financial aid|registrar|dean|faculty|student employment)\b", re.IGNORECASE)
CLAIMS_COMPANY = re.compile(r"\b(?:hr|human resources|recruit(?:er|ing|ment)|talent acquisition|hiring manager|"
                            r"onboarding)\b", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.IGNORECASE)


def _finding(rule_id, severity, weight, title, why, evidence=()):
    return {"rule_id": rule_id, "severity": severity, "weight": weight, "title": title, "why": why,
            "matched": [e for e in evidence if e][:3]}


def _is_fsu(domain: str) -> bool:
    d = domain.lower().rstrip(".")
    return d == "fsu.edu" or d.endswith(".fsu.edu")


def _looks_like_fsu(domain: str) -> bool:
    d = domain.lower().rstrip(".")
    if _is_fsu(d):
        return False
    flat = re.sub(r"[^a-z0-9]", "", d)
    return "fsu" in flat or "floridastate" in flat or "seminole" in flat


def sender_findings(sender: str, text: str) -> list[dict]:
    out = []
    sender = (sender or "").strip()
    domains = {m.group(1).lower() for m in _EMAIL.finditer(sender + " " + text)}
    sender_domain = ""
    m = _EMAIL.search(sender)
    if m:
        sender_domain = m.group(1).lower()
    for d in sorted(domains):
        if _looks_like_fsu(d):
            out.append(_finding("fsu_lookalike", "critical", 40, "An address pretends to be FSU",
                                f"{d} is not an FSU address. Real FSU email ends in exactly @fsu.edu (or a department "
                                f"subdomain like @cs.fsu.edu). Look-alike domains are a classic phishing move.", ["@" + d]))
    if sender_domain in FREE_MAIL:
        claim = CLAIMS_SCHOOL.search(text + " " + sender) or CLAIMS_COMPANY.search(text + " " + sender)
        if claim:
            out.append(_finding("personal_sender", "warning", 18, "Official-sounding message from a personal account",
                                f"It claims to be a {claim.group(0).lower()} but was sent from {sender_domain}. "
                                "Universities and real companies write from their own domain.", ["@" + sender_domain]))
    if sender and re.search(r"\b(?:fsu|florida state|career center)\b", sender, re.IGNORECASE) and sender_domain and not _is_fsu(sender_domain):
        out.append(_finding("display_spoof", "warning", 20, "The sender name says FSU but the address doesn't",
                            f"The name shown mentions FSU, but the address is at {sender_domain}.", [sender[:80]]))
    return out


def link_findings(text: str) -> list[dict]:
    out = []
    seen = set()
    for raw in _URL.findall(text or ""):
        url = raw if raw.lower().startswith("http") else "http://" + raw
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            continue
        host = host[4:] if host.startswith("www.") else host
        if not host or host in seen:
            continue
        seen.add(host)
        if host in SHORTENERS:
            out.append(_finding("short_link", "warning", 14, "A shortened link hides where it goes",
                                f"{host} links hide the real destination. Don't open it; ask for the company's own site instead.", [raw[:80]]))
        elif host in CHAT_LINKS:
            out.append(_finding("chat_link", "warning", 18, "Pushes you to a chat app",
                                "Moving a 'job' to WhatsApp, Telegram or Signal is how scammers avoid the platforms that screen them.", [raw[:80]]))
        elif re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            out.append(_finding("ip_link", "critical", 34, "A link to a bare IP address",
                                "Real employers don't send links to raw number addresses.", [raw[:80]]))
        elif _looks_like_fsu(host):
            out.append(_finding("fsu_lookalike_link", "critical", 40, "A link pretends to be FSU",
                                f"{host} is not an FSU website. FSU sites end in fsu.edu.", [raw[:80]]))
        elif host in FORM_HOSTS or host.endswith(".jotform.com"):
            out.append(_finding("form_link", "note", 8, "Asks you to fill in an outside form",
                                "Forms are fine for events, but a 'job' that starts with a form asking for your details is a common data-harvesting step.", [raw[:80]]))
    return out


def _ai_opinion(text: str, sender: str) -> dict | None:
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["safe", "suspicious", "scam"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "red_flags": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
                "flag": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["flag", "evidence"]}},
            "green_flags": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["verdict", "confidence", "red_flags", "summary"],
    }
    system = ("You are a job-scam analyst helping a Florida State University student decide whether a message about a job, "
              "internship, research position, or gig is a scam. Known student scam patterns: fake professors or departments "
              "offering 'research assistant' or 'personal assistant' jobs; check-cashing or equipment-check schemes; reshipping; "
              "gift cards; crypto; 'you've been pre-selected'; flat weekly pay for vague part-time work; requests to move to "
              "personal email, text, WhatsApp or Telegram; requests for bank details, SSN or ID before an interview; upfront fees; "
              "app-review or 'task' jobs. Legitimate recruiters use their company domain, name a real role, and never ask for "
              "money. Judge only from the message. Quote the exact words that are your evidence. Keep the summary to two sentences.")
    content = (ai.tag("message", f"From: {sender or '(not given)'}\n\n{text}", 8000) +
               "\n\nIs this message a scam? Report red flags with the exact evidence.")
    try:
        return ai.structured(system, content, "scam_opinion", schema, max_tokens=900, tier="fast")
    except ai.AIUnavailable:
        return None


def is_novel(r: dict) -> bool:
    """The AI is confident it's a scam but the rules were quiet: probably a pattern the detector doesn't know yet."""
    o = r.get("ai") or {}
    return o.get("verdict") == "scam" and float(o.get("confidence") or 0) >= 0.7 and r.get("band") in ("clear", "caution")


def check(text: str, sender: str = "", *, use_ai: bool = False, platform_employer: dict | None = None) -> dict:
    text = (text or "").strip()[:8000]
    sender = (sender or "").strip()[:200]
    result = score_posting(title="", description=text + ("\n" + sender if sender else ""), company="",
                           run_network=False)
    findings = list(result.findings) + sender_findings(sender, text) + link_findings(text)
    # De-duplicate by rule id, keep the strongest.
    best: dict[str, dict] = {}
    for f in findings:
        if f["rule_id"] not in best or f["weight"] > best[f["rule_id"]]["weight"]:
            best[f["rule_id"]] = f
    findings = sorted(best.values(), key=lambda f: ({"critical": 0, "warning": 1, "note": 2}[f["severity"]], -f["weight"]))
    score = min(100, sum(f["weight"] for f in findings))
    critical = any(f["severity"] == "critical" for f in findings)
    band = "block" if critical or score >= 65 else "review" if score >= 35 else "caution" if score >= 15 else "clear"
    level = BAND_LEVEL[band]
    lead_gen = result.lead_gen or {}
    if lead_gen.get("flag") and level < 1:
        level = 1

    opinion = None
    if use_ai and ai.enabled():
        opinion = _ai_opinion(text, sender)
        if opinion:
            conf = float(opinion.get("confidence") or 0)
            if opinion.get("verdict") == "scam" and conf >= 0.7:
                level = max(level, 2)
            elif opinion.get("verdict") in ("scam", "suspicious") and conf >= 0.5:
                level = max(level, 1)
            # A "safe" opinion never lowers the rules' level.

    key, title, advice = LEVELS[level]
    return {"level": level, "key": key, "title": title, "advice": advice, "score": score, "band": band,
            "findings": findings, "lead_gen": lead_gen, "ai": opinion, "platform_employer": platform_employer,
            "ruleset": result.ruleset_version, "checked_at": time.time(),
            "comp": result.enrichment.get("compensation"), "digest": text + "\n" + sender}


LISTING_LEVELS = [
    ("ok", "No known scam signs", "Nothing in this listing matches a known scam pattern. That isn't a guarantee: find the same job on the employer's own careers page before you apply."),
    ("caution", "Be careful", "A few things in this listing are off. Confirm it on the employer's own website before you apply or share anything."),
    ("warn", "Likely a scam", "Several strong scam signals. Don't apply through this listing and don't send personal or bank details."),
    ("bad", "Scam. Stop here.", "This listing matches patterns that only scams use. Don't apply, reply or send anything."),
]
LISTING_STEPS = {
    0: ["Find the same job on the employer's own careers page and apply there.",
        "Never pay for training, equipment or a background check. Real jobs don't charge you.",
        "Don't give your SSN or bank details until you have a real offer."],
    1: ["Look for the same listing on the company's own website before you apply.",
        "Search the company name with the word \"scam\" and read what others found.",
        "Don't put your SSN, bank details or a photo of your ID in an application."],
    2: ["Don't apply through this listing or its link.",
        "Look the company up yourself. If the job isn't on their own site, skip it.",
        "If you found it on Handshake, LinkedIn or Indeed, report the listing there."],
    3: ["Don't apply, reply or send anything.",
        "If you already sent money or bank details, or deposited a check they sent, call your bank now.",
        "Report the listing where you found it, and report fraud at reportfraud.ftc.gov."],
}
LEADGEN_STEP = "This looks like an aggregator or lead-generation ad. Find the employer's own posting and apply there instead of giving this site your details."


def check_listing(title: str, description: str, company: str = "", url: str = "", contact: str = "") -> dict:
    """A job posting someone found elsewhere, scored exactly like a listing submitted to the board. The apply link is
    checked as text (tracking redirects, signup walls, shorteners); it is never opened."""
    title, company, url, contact = (title or "").strip()[:200], (company or "").strip()[:200], (url or "").strip()[:2000], (contact or "").strip()[:200]
    description = (description or "").strip()[:8000]
    result = score_posting(title, description + ("\n" + contact if contact else ""), company, run_network=False, url_chain=[url] if url else None)
    extra = [f for f in link_findings(description + " " + url) if f["rule_id"] not in {x["rule_id"] for x in result.findings}]
    findings = sorted(list(result.findings) + extra, key=lambda f: ({"critical": 0, "warning": 1, "note": 2}[f["severity"]], -f["weight"]))
    score = min(100, result.score + sum(f["weight"] for f in extra))
    critical = any(f["severity"] == "critical" for f in findings)
    band = "block" if critical or score >= 65 else "review" if score >= 35 else "caution" if score >= 15 else "clear"
    level = BAND_LEVEL[band]
    lead_gen = result.lead_gen or {}
    if lead_gen.get("flag") and level < 1:
        level = 1
    second = ml.second_look(title, description, company, url, result.findings, result.score) if band in ("clear", "caution") else None
    if second:                                  # the learned model can raise "no signs" to "be careful", never more
        findings.append(second)
        level = max(level, 1)
    key, ttl, advice = LISTING_LEVELS[level]
    steps = ([LEADGEN_STEP] if lead_gen.get("flag") else []) + LISTING_STEPS[level]
    return {"kind": "listing", "level": level, "key": key, "title": ttl, "advice": advice, "score": score, "band": band,
            "findings": findings, "lead_gen": lead_gen, "ai": None, "platform_employer": None, "steps": steps,
            "ruleset": result.ruleset_version, "checked_at": time.time(),
            "subject": title, "company": company, "url": url, "comp": result.enrichment.get("compensation"),
            "digest": "\n".join((title, company, description, url, contact))}


NEXT_STEPS = {
    0: ["Look the company up yourself (not through links in the message) and confirm the job is on their careers page.",
        "Keep the conversation on NoleCareerShield, Handshake or the company's own email.",
        "Never pay for training, equipment or a background check. Real jobs don't charge you."],
    1: ["Don't click links or open attachments yet.",
        "Find the organization's official contact on your own (their website, the FSU directory) and ask if the message is real.",
        "Don't share your student ID, date of birth, SSN or bank details.",
        "Check again here if they reply with anything new."],
    2: ["Don't reply with personal information, and don't click the links.",
        "If it claims to be from FSU, forward it to FSU's IT security team and delete it.",
        "Block the sender. If it came through NoleCareerShield, press Report so reviewers can remove them."],
    3: ["Stop replying. Don't send money, gift cards, crypto, or bank details, and don't deposit any check they send.",
        "If you already shared banking details or deposited a check, call your bank now.",
        "Report it: forward FSU look-alikes to FSU's IT security team, and report fraud at reportfraud.ftc.gov.",
        "If it came through NoleCareerShield, press Report so reviewers can remove the account."],
}


def full_view(user: dict | None) -> bool:
    """The full evidence (every signal, the exact words it caught, link checks) is for FSU students and approved employers.
    Everyone else gets the verdict and plain reasons: enough to spot a scam, not enough to tune one until it passes."""
    if not user:
        return False
    if user["role"] == "student":
        return True
    with store.db() as conn:
        return store.employer_approved(conn, user["id"])


PUBLIC_REASONS = 3


def render_result(r: dict, full: bool = True) -> str:
    """The verdict in the Security Report HUD (guardian.check_report), then the AI opinion and what to do next. Visitors get
    the verdict and up to three plain reasons (no matched words); FSU students and approved employers get everything."""
    import guardian
    out = guardian.check_report(r, full)
    if full:
        out += marked_text_html(r)
    if not full:
        shown = [f for f in r["findings"] if f["severity"] != "note"][:PUBLIC_REASONS] or r["findings"][:PUBLIC_REASONS]
        more = len(r["findings"]) - len(shown)
        extra = f"{more} more signal{'s' if more != 1 else ''}, " if more > 0 else ""
        out += ('<div class="banner info" style="margin-top:12px">FSU students see ' + extra + 'the exact words each signal caught and the '
                'link and sender checks, and can check messages straight from their inbox. <a href="/login">Log in with your @fsu.edu email</a></div>')
    op = ""
    if full and r.get("ai"):
        o = r["ai"]
        flags = "".join(f'<li><b>{ui.esc(x.get("flag", ""))}</b><span class="ev">“{ui.esc(x.get("evidence", ""))}”</span></li>'
                        for x in (o.get("red_flags") or [])[:6])
        greens = "".join(f'<span class="pill ok">{ui.esc(g)}</span> ' for g in (o.get("green_flags") or [])[:4])
        op = (f'<h3 class="sec">AI second opinion <small>{ui.esc(o.get("verdict", "")).title()} · '
              f'{round(100 * float(o.get("confidence") or 0))}% confident</small></h3>'
              f'<div class="card"><p>{ui.esc(o.get("summary", ""))}</p>{f"<ul class=ai-flags>{flags}</ul>" if flags else ""}'
              f'{f"<p style=margin-top:10px>{greens}</p>" if greens else ""}'
              '<p class="small faint" style="margin-top:10px">The AI can make a verdict stricter, never softer. The verdict above always includes the rule check.</p></div>')
    steps = "".join(f"<li>{ui.esc(s)}</li>" for s in r.get("steps") or NEXT_STEPS[r["level"]])
    return f"""{out}{op}<h3 class="sec">What to do next</h3><ol class="next">{steps}</ol>"""


def _school_form(done: str = "") -> str:
    if done:
        return f'<div class="card" style="margin-top:22px"><b>Thanks.</b> <span class="muted">We\'ll count {ui.esc(done)}.</span></div>'
    return f"""<form method="post" action="/check/school" class="card" style="margin-top:22px"><input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<b>Want NoleCareerShield at your school?</b><p class="small muted" style="margin:4px 0 10px">Tell us which one. We only keep the school name, nothing about you.</p>
<div class="row" style="flex-wrap:nowrap"><label for="c-school" class="hp">Your school</label><input id="c-school" name="school" maxlength="80" required placeholder="e.g. University of Florida" style="flex:1;min-width:0">
<button class="b sm" type="submit">Send</button></div></form>"""


def _form(text: str = "", sender: str = "", ai_on: bool = False) -> str:
    user = ui.viewer()
    ai_box = ""
    if user and ai.enabled():
        ai_box = (f'<label class="toggle"><input type="checkbox" name="ai" value="1"{" checked" if ai_on else ""}>'
                  '<span><b>Add an AI second opinion.</b> Sends the message to Claude (Anthropic) for a written analysis. '
                  'It can only make the verdict stricter.</span></label>')
    return f"""<form method="post" action="/check" class="card" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<div class="form-field"><label for="c-text">The message</label>
<p class="hint">Paste the whole thing: text, email, LinkedIn or Handshake DM. It isn't saved unless you send it to reviewers, except a small random share of results we call safe, which a reviewer double-checks (no name; emails and phone numbers masked).</p>
<textarea id="c-text" name="text" required maxlength="8000" data-count placeholder="Hi! I'm Dr. Smith from the Psychology Department. I'm looking for a personal assistant, $400 weekly...">{ui.esc(text)}</textarea></div>
<div class="form-field"><label for="c-sender">Who sent it (optional)</label>
<p class="hint">The email address or name it came from. It helps spot fake FSU and company addresses.</p>
<input id="c-sender" name="sender" maxlength="200" value="{ui.esc(sender)}" placeholder="e.g. careers.fsu.edu@gmail.com"></div>
<div class="form-field"><label for="c-file">Attachment (optional)</label>
<p class="hint">An offer letter PDF, a photo of a check they sent, or a screenshot with a QR code. We read it once and don't keep it.</p>
<input id="c-file" name="file" type="file" accept=".pdf,image/png,image/jpeg,image/webp"></div>
{ai_box}<button class="submit-btn" type="submit">Check this message</button></form>"""


def _kind_tabs(kind: str) -> str:
    return ('<div class="seg" role="tablist" style="margin-bottom:16px">'
            f'<a href="/check"{" class=on aria-current=page" if kind == "listing" else ""}>A job listing</a>'
            f'<a href="/check?kind=message"{" class=on aria-current=page" if kind == "message" else ""}>A message</a>'
            f'<a href="/check?kind=thread"{" class=on aria-current=page" if kind == "thread" else ""}>A conversation</a></div>')


def _page(inner: str, status: int = 200, kind: str = "message") -> HTMLResponse:
    if kind == "thread":
        head = ui.page_head("Is this conversation a scam?",
                            "Paste the whole thread. Job scams follow a script over several messages; we show which step you're at and what usually comes next.",
                            num="Scam check")
    elif kind == "listing":
        head = ui.page_head("Is this job listing a scam?",
                            "Found a job on Handshake, LinkedIn, Indeed, Instagram or a flyer? Paste it and get the same scam check every listing on NoleCareerShield goes through.",
                            num="Scam check")
    else:
        head = ui.page_head("Is this message a scam?",
                            "Paste any message about a job, internship or gig. You'll get a clear verdict, the evidence behind it, and what to do next.",
                            num="Scam check")
    return web.page(head + _kind_tabs(kind) + season_html() + inner, "Scam check", active="/check", js=True, status=status)


def _listing_form(v: dict | None = None) -> str:
    v = v or {}
    val = lambda k: ui.esc(v.get(k, ""))
    return f"""<form method="post" action="/check/listing" class="card">
<input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<div class="grid2"><div class="form-field"><label for="l-title">Job title</label><input id="l-title" name="title" required maxlength="200" value="{val('title')}" placeholder="Remote Administrative Assistant"></div>
<div class="form-field"><label for="l-company">Company (optional)</label><input id="l-company" name="company" maxlength="200" value="{val('company')}" placeholder="As the listing names it"></div></div>
<div class="form-field"><label for="l-desc">The listing</label><p class="hint">Paste the whole description: duties, pay, requirements and how to apply.</p>
<textarea id="l-desc" name="description" required maxlength="8000" data-count placeholder="We are hiring part-time remote assistants, $500 weekly. No experience needed...">{val('description')}</textarea></div>
<div class="grid2"><div class="form-field"><label for="l-url">Apply link (optional)</label><p class="hint">We read the link, we don't open it.</p><input id="l-url" name="url" maxlength="2000" value="{val('url')}" placeholder="https://..."></div>
<div class="form-field"><label for="l-contact">Contact email (optional)</label><p class="hint">The address the listing says to write to.</p><input id="l-contact" name="contact" maxlength="200" value="{val('contact')}" placeholder="hr@company.com"></div></div>
<button class="submit-btn" type="submit">Check this listing</button></form>"""


@router.get("/check", response_class=HTMLResponse)
def check_form(request: Request, m: int = 0, kind: str = "listing"):
    security.enforce_rate_limit(request, security.general_limiter, "check_page")
    if kind == "thread":
        return _page(_thread_form(), kind="thread")
    if kind != "message" and not m:
        return _page(_listing_form(), kind="listing")          # a job listing is the default tab
    user = web.current_user(request)
    if m and user:
        # Check a message you received on NoleCareerShield.
        with store.db() as conn:
            msg = store.row(conn, """SELECT m.*, c.student_id, c.employer_id FROM messages m
                                     JOIN conversations c ON c.id = m.conversation_id WHERE m.id = ?""", (m,))
            if msg and user["id"] in (msg["student_id"], msg["employer_id"]) and msg["sender_id"] != user["id"] and msg["status"] == "delivered":
                emp = store.employer_profile(conn, msg["sender_id"]) if msg["sender_id"] == msg["employer_id"] else None
                security.enforce_key_limit(security.check_limiter, f"u{user['id']}", "scam checks")
                r = check(msg["body"], "", platform_employer=emp)            # someone on the site: always the full view
                quoted = (f'<div class="card" style="margin-top:6px"><div class="eyebrow">The message you\'re checking</div>'
                          f'<p style="white-space:pre-wrap;margin-top:6px">{ui.esc(msg["body"][:1500])}</p>'
                          f'<a class="small" href="/messages/{int(msg["conversation_id"])}">← Back to the conversation</a></div>')
                return _page(quoted + render_result(r) + '<h3 class="sec">Check another message</h3>' + _form())
    return _page(_form())


def analyze_upload_safely(data: bytes, filename: str, content_type: str) -> dict:
    """artifacts.analyze_upload() in a separate process with a time limit (a crafted PDF can take minutes)."""
    import sandbox
    from scam_detector import artifacts
    try:
        return sandbox.run(artifacts.analyze_upload, data, filename, content_type)
    except sandbox.ParseBusy:
        note = "We're reading a lot of files right now, so this one wasn't checked. Try again in a minute, or paste the text."
    except sandbox.ParseTimeout:
        note = "That file took too long to read, so it wasn't checked. Paste the text of the message instead."
    except Exception:                          # noqa: BLE001
        note = "We couldn't read that file. Paste the text of the message instead."
    return {"kind": "unsupported", "text": "", "findings": [], "meta": {}, "notes": [note], "urls": []}


@router.post("/check", response_class=HTMLResponse)
def check_submit(request: Request, text: str = Form(""), sender: str = Form(""), csrf: str = Form(""), ai_: str = Form("", alias="ai"),
                       file: UploadFile | None = File(None)):
    security.enforce_rate_limit(request, security.check_limiter, "check")
    user = web.current_user(request)
    if not user:
        security.enforce_rate_limit(request, security.public_check_limiter, "check_public")
    if not security.verify_csrf(csrf, "form"):
        return _page(ui.banner("warning", "That page had been open too long. Your text is still here; press Check again.") + _form(text[:8000], sender[:200]), 400)
    text = security._CONTROL_CHARS_RE.sub("", text or "").strip()
    art, art_note = None, ""
    if file is not None and file.filename:
        from scam_detector import artifacts
        data = file.file.read(8 * 1024 * 1024 + 1)
        art = analyze_upload_safely(data, file.filename, file.content_type or "")
        art_note = "".join(ui.banner("info", n) for n in art.get("notes", []))
        if art.get("text") and len(text) < 15:
            text = art["text"][:8000]
    if len(text) < 15:
        return _page(ui.banner("warning", "Paste the message you want checked (at least a sentence).") + _form(text, sender), 400)
    if len(text) > 8000 or len(sender) > 200:
        return _page(ui.banner("warning", "That's longer than 8,000 characters. Paste the main part of the message.") + _form(text[:8000], sender[:200]), 400)
    full = full_view(user)
    use_ai = bool(ai_) and full and ai.enabled()
    if use_ai:
        with store.db() as conn:
            if not store.ai_take(conn, user["id"], ai.daily_limit()):
                use_ai = False
    r = check(text, sender, use_ai=use_ai)
    novel = is_novel(r)
    if novel:
        defense.bump("ai_only_scam")
    enrich(r, text=text + ("\n" + art["text"][:8000] if art and art.get("text") and art["text"][:200] not in text else ""), sender=sender,
           extra=(art or {}).get("findings") or [], url=" ".join((art or {}).get("urls") or []))
    metrics.maybe_sample(r, kind="message", text=text, sender=sender)
    lead = ('<div class="banner warning" style="margin:0 0 10px"><b>This may be a new kind of scam.</b> The AI flagged it, but none of our '
            'rules caught it. Sending it to our reviewers is how the detector learns to catch the next one.</div>' if novel else "")
    report = f"""<details class="card" style="margin-top:22px"{" open" if novel else ""}><summary style="cursor:pointer;font-weight:600">Send this to our reviewers</summary>
{lead}<p class="small muted" style="margin:8px 0 12px">Helps the detector learn. We save the message text and your answer, never your name. Remove personal details first if you can.</p>
<form method="post" action="/check/submit"><input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<input type="hidden" name="text" value="{ui.esc(text)}"><input type="hidden" name="sender" value="{ui.esc(sender)}"><input type="hidden" name="band" value="{ui.esc(r['band'])}">
<input type="hidden" name="kind" value="message"><input type="hidden" name="source" value="{'ai_novel' if novel else 'student'}">
<div class="row"><button class="b sm" name="label" value="scam">It was a scam</button><button class="b sm sec" name="label" value="unsure">Not sure</button>
<button class="b sm ghost" name="label" value="legit">It was real</button></div></form></details>"""
    extra = "" if user else _school_form()
    return _page(art_note + render_result(r, full) + asks_html(r) + report_html(r) + report + extra + '<h3 class="sec">Check another message</h3>' + _form(text, sender, use_ai))


@router.post("/check/thread", response_class=HTMLResponse)
def check_thread(request: Request, text: str = Form(""), me: str = Form(""), csrf: str = Form("")):
    security.enforce_rate_limit(request, security.check_limiter, "check")
    user = web.current_user(request)
    if not user:
        security.enforce_rate_limit(request, security.public_check_limiter, "check_public")
    text = security._CONTROL_CHARS_RE.sub("", text or "").strip()
    me = security._CONTROL_CHARS_RE.sub("", me or "").strip()[:120]
    if not security.verify_csrf(csrf, "form"):
        return _page(ui.banner("warning", "That page had been open too long. Your text is still here; press Check again.") + _thread_form(text[:20000], me), 400, kind="thread")
    if len(text) < 40:
        return _page(ui.banner("warning", "Paste the conversation (at least a couple of messages).") + _thread_form(text, me), 400, kind="thread")
    if len(text) > 20000:
        return _page(ui.banner("warning", "That's longer than 20,000 characters. Paste the most recent part of the conversation.") + _thread_form(text[:20000], me), 400, kind="thread")
    from scam_detector.conversation import analyze_thread
    a = analyze_thread(text, me=me or None)
    theirs = "\n".join(t["text"] for t in a.get("turns", []) if t.get("speaker") != "me") or text
    r = check(theirs[:8000], "")
    enrich(r, text=theirs, extra=a.get("findings") or [])
    metrics.maybe_sample(r, kind="message", text=theirs[:8000])
    full = full_view(user)
    return _page(render_result(r, full) + thread_html(a) + asks_html(r) + report_html(r)
                 + '<h3 class="sec">Check another conversation</h3>' + _thread_form(text, me), kind="thread")


@router.post("/check/school", response_class=HTMLResponse)
def school_request(request: Request, school: str = Form(""), csrf: str = Form("")):
    security.enforce_rate_limit(request, security.school_limiter, "school")
    name = re.sub(r"\s+", " ", security._CONTROL_CHARS_RE.sub("", school or "")).strip()[:80]
    if not security.verify_csrf(csrf, "form") or len(name) < 3 or not re.search(r"[A-Za-z]{2}", name) or re.search(r"[<>{}]|https?:|www\.|@", name):
        return _page(ui.banner("warning", "Type your school's name, like University of Florida.") + _school_form() + _form(), 400)
    with store.db() as conn:
        conn.execute("INSERT INTO school_requests (school, created_at) VALUES (?, ?)", (name, time.time()))
    return _page(_school_form(done=name) + '<h3 class="sec">Check another message</h3>' + _form())


@router.post("/check/listing", response_class=HTMLResponse)
def check_listing_submit(request: Request, title: str = Form(""), company: str = Form(""), description: str = Form(""), url: str = Form(""),
                         contact: str = Form(""), csrf: str = Form("")):
    security.enforce_rate_limit(request, security.check_limiter, "check")
    user = web.current_user(request)
    if not user:
        security.enforce_rate_limit(request, security.public_check_limiter, "check_public")       # shared with message checks
    v = {k: security._CONTROL_CHARS_RE.sub("", x or "").strip() for k, x in
         (("title", title), ("company", company), ("description", description), ("url", url), ("contact", contact))}
    bad = lambda msg: _page(ui.banner("warning", msg) + _listing_form(v), 400, kind="listing")
    if not security.verify_csrf(csrf, "form"):
        return bad("That page had been open too long. Your listing is still here; press Check again.")
    if not v["title"] or len(v["description"]) < 40:
        return bad("Add the job title and paste the listing (at least a couple of sentences).")
    if len(v["title"]) > 200 or len(v["company"]) > 200 or len(v["description"]) > 8000 or len(v["url"]) > 2000 or len(v["contact"]) > 200:
        return bad("Something there is too long. Paste the main part of the listing.")
    if v["url"] and not re.match(r"^(?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#:][^\s<>\"']*)?$", v["url"]):
        return bad("The apply link doesn't look like a web address. Leave it empty if there isn't one.")
    if v["url"] and not v["url"].lower().startswith(("http://", "https://")):
        v["url"] = "https://" + v["url"]
    r = check_listing(v["title"], v["description"], v["company"], v["url"], v["contact"])
    enrich(r, text=v["description"] + ("\n" + v["contact"] if v["contact"] else ""), title=v["title"], company=v["company"], url=v["url"], listing=True)
    metrics.maybe_sample(r, kind="listing", text=v["description"], title=v["title"], company=v["company"], url=v["url"], sender=v["contact"])
    full = full_view(user)
    report = f"""<details class="card" style="margin-top:22px"><summary style="cursor:pointer;font-weight:600">Send this to our reviewers</summary>
<p class="small muted" style="margin:8px 0 12px">Helps the detector learn. We save the listing and your answer, never your name.</p>
<form method="post" action="/check/submit"><input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<input type="hidden" name="text" value="{ui.esc(v['description'][:8000])}"><input type="hidden" name="sender" value="{ui.esc(v['contact'][:200])}"><input type="hidden" name="band" value="{ui.esc(r['band'])}">
<input type="hidden" name="kind" value="listing"><input type="hidden" name="title" value="{ui.esc(v['title'][:200])}"><input type="hidden" name="company" value="{ui.esc(v['company'][:200])}"><input type="hidden" name="url" value="{ui.esc(v['url'][:2000])}">
<div class="row"><button class="b sm" name="label" value="scam">It was a scam</button><button class="b sm sec" name="label" value="unsure">Not sure</button>
<button class="b sm ghost" name="label" value="legit">It was real</button></div></form></details>"""
    extra = "" if user else _school_form()
    return _page(render_result(r, full) + asks_html(r) + report_html(r) + report + extra + '<h3 class="sec">Check another listing</h3>' + _listing_form(v), kind="listing")


@router.post("/check/submit", response_class=HTMLResponse)
def check_contribute(request: Request, text: str = Form(""), sender: str = Form(""), band: str = Form(""),
                     label: str = Form(""), csrf: str = Form(""), kind: str = Form("message"), title: str = Form(""),
                     company: str = Form(""), url: str = Form(""), source: str = Form("student")):
    security.enforce_rate_limit(request, security.check_limiter, "check_submit")
    if not security.verify_csrf(csrf, "form") or label not in ("scam", "unsure", "legit") or not (15 <= len(text) <= 8000):
        return _page(ui.banner("warning", "That didn't go through. Please try again.") + _form(), 400)
    clean = lambda x, n: security._CONTROL_CHARS_RE.sub("", x or "").strip()[:n]
    user = web.current_user(request)
    with store.db() as conn:
        learning.add_submission(conn, body=clean(text, 8000), sender=clean(sender, 200), band=band if band in BAND_LEVEL else "",
                                user_label=label, user_id=user["id"] if user else None,
                                kind="listing" if kind == "listing" else "message", title=clean(title, 200), company=clean(company, 200),
                                url=clean(url, 2000), source="ai_novel" if source == "ai_novel" else "student")
    return _page(ui.banner("verified", "Thanks. A reviewer will look at it, and it helps the detector catch the next one.") + _form())


# ---------- beyond wording: identifiers, clones, outside intel, asks, conversations, attachments (defense.py) ----------

REPORT_LINKS = [
    ("Report fraud to the FTC", "https://reportfraud.ftc.gov/"),
    ("Lost money? File with the FBI's IC3", "https://www.ic3.gov/"),
    ("Scam text? Forward it to 7726 (SPAM)", "https://www.ctia.org/news/report-spam-text-messages"),
    ("Found it on Handshake? Use its Report button", "https://support.joinhandshake.com/hc/en-us/articles/360036464793"),
]


def enrich(r: dict, *, text: str, sender: str = "", title: str = "", company: str = "", url: str = "",
           listing: bool = False, extra: list | None = None) -> dict:
    """Add the findings that don't depend on wording, and the student-facing asks. The verdict can only get stricter."""
    from scam_detector.asks import extract_asks, MONEY_ASKS
    found = defense.extra_findings(text, sender=sender, title=title, company=company, url=url) + list(extra or [])
    r["asks"] = extract_asks("\n".join(x for x in (title, text) if x))
    _rescore(r, found, listing)
    r["text_shown"] = text[:8000]
    r["cleared"] = cleared(text, r)
    money = [a for a in r["asks"] if a["ask"] in MONEY_ASKS]
    if money and r["band"] in ("clear", "caution"):
        _rescore(r, [{"rule_id": "money_ask", "severity": "warning", "weight": 25, "title": "It asks you for money or financial details",
                      "why": f"It asks you to {money[0]['label'].lower()}. Real employers pay you; they don't ask you to pay, "
                             "move money or hand over bank or ID details before a real offer.",
                      "matched": [a["evidence"][:90] for a in money[:3]]}], listing)
        defense.bump("ask_only_scam")
    if any(f["rule_id"] == "known_scam_identifier" for f in r["findings"]):
        defense.bump("known_identifier")
    if listing:
        defense.bump("listing_checks")
        m = ml.load()
        if m:
            p = m.predict(title, text, company, url, r["findings"], r["score"])
            if p.get("uncertain"):
                defense.bump("model_uncertain")
    return r


def cleared(text: str, r: dict) -> list[dict]:
    """Wording that looked like a scam tactic but was ruled out by its context ("we will never ask for a fee", "SSN for payroll
    upon hire"). Rules that still fired elsewhere in the text are left out, so a green line never contradicts a red one."""
    from scam_detector.rules import cleared_matches
    from scam_detector.asks import cleared_asks
    fired = {f["rule_id"] for f in r.get("findings") or []} | {"ask:" + a["ask"] for a in r.get("asks") or []}
    evidence = [e.lower() for f in r.get("findings") or [] for e in f.get("matched") or [] if len(e) >= 4]
    evidence += [a["evidence"].lower() for a in r.get("asks") or [] if len(a.get("evidence") or "") >= 4]
    text = text[:8000]                       # the panel shows the first 8,000 characters; only explain what's shown
    out, seen = [], set()
    for c in cleared_matches(text) + cleared_asks(text):
        key = c["clause"].lower()
        if c["rule_id"] in fired or key in seen or any(e in key or key in e for e in evidence):
            continue
        seen.add(key)
        out.append(c)
    return out[:6]


def _words_rx(phrase: str) -> re.Pattern | None:
    words = re.findall(r"[\w$@.'/%-]+", phrase or "")
    if not words or len(" ".join(words)) < 3:
        return None
    return re.compile(r"[\s\W]{0,3}".join(re.escape(w) for w in words), re.IGNORECASE)


def marked_text_html(r: dict) -> str:
    """The pasted text with what we found marked: red for critical signals, amber for warnings, green for wording that was
    ruled out by its context. Every mark is escaped text plus a fixed class, so nothing from the paste is rendered as HTML."""
    text = r.get("text_shown") or ""
    if not text.strip():
        return ""
    spans: list[tuple[int, int, str]] = []

    def add(phrase: str, cls: str) -> None:
        rx = _words_rx(phrase)
        if not rx:
            return
        for m in rx.finditer(text):
            a, b = m.span()
            if not any(a < y and x < b for x, y, _ in spans):
                spans.append((a, b, cls))

    for f in r.get("findings") or []:
        cls = "mk-red" if f.get("severity") == "critical" else "mk-amb"
        for e in f.get("matched") or []:
            add(e, cls)
    for a in r.get("asks") or []:
        add(a.get("evidence", ""), "mk-red" if a.get("money") else "mk-amb")
    placed = []
    for c in r.get("cleared") or []:
        before = len(spans)
        add(c["clause"], "mk-grn")
        if len(spans) > before:
            placed.append(c)                 # only explain green marks that are actually on the page
    if not spans:
        return ""
    spans.sort()
    parts, at = [], 0
    for a, b, cls in spans:
        parts.append(ui.esc(text[at:a]))
        parts.append(f'<mark class="{cls}">{ui.esc(text[a:b])}</mark>')
        at = b
    parts.append(ui.esc(text[at:]))
    greens = "".join(f'<li><mark class="mk-grn">“{ui.esc(c["clause"][:160])}”</mark><span><b>Not counted:</b> {ui.esc(c["title"])}. '
                     f'{ui.esc(c["why"])}</span></li>' for c in placed)
    used = {cls for _, _, cls in spans}
    legend = '<p class="mk-legend">' + "".join(f'<span class="{c}">{t}</span>' for c, t in (
        ("mk-red", "Scam signal"), ("mk-amb", "Warning"), ("mk-grn", "Ruled out by context")) if c in used) + "</p>"
    why = (f'<ul class="mk-cleared">{greens}</ul><p class="small faint">Green explains why a phrase didn\'t count against the message. It '
           'doesn\'t mean the message is safe: scammers copy reassuring lines too.</p>') if greens else ""
    return (f'<h3 class="sec">How we read it</h3><div class="card mk-card">{legend}<div class="mk-text">{"".join(parts)}</div>{why}</div>')


def _rescore(r: dict, extra: list, listing: bool) -> None:
    if not extra:
        return
    best = {f["rule_id"]: f for f in r["findings"]}
    for f in extra:
        if f["rule_id"] not in best or f["weight"] > best[f["rule_id"]]["weight"]:
            best[f["rule_id"]] = f
    findings = sorted(best.values(), key=lambda f: ({"critical": 0, "warning": 1, "note": 2}[f["severity"]], -f["weight"]))
    score = min(100, sum(f["weight"] for f in findings))
    critical = any(f["severity"] == "critical" for f in findings)
    band = "block" if critical or score >= 65 else "review" if score >= 35 else "caution" if score >= 15 else "clear"
    if BAND_LEVEL[band] < BAND_LEVEL.get(r["band"], 0):
        band = r["band"]
    level = max(r["level"], BAND_LEVEL[band])
    key, title, advice = (LISTING_LEVELS if listing else LEVELS)[level]
    r.update({"findings": findings, "score": max(score, r["score"]), "band": band, "level": level, "key": key, "title": title, "advice": advice})
    if listing:
        r["steps"] = ([LEADGEN_STEP] if (r.get("lead_gen") or {}).get("flag") else []) + LISTING_STEPS[level]


def asks_html(r: dict) -> str:
    asks = r.get("asks") or []
    if not asks:
        return ""
    items = "".join(f'<li><b>{ui.esc(a["label"])}</b><span class="ev">“{ui.esc(a["evidence"][:120])}”</span></li>' for a in asks[:8])
    return f'<h3 class="sec">What they\'re asking you to do</h3><ul class="reasons card">{items}</ul>'


def report_html(r: dict) -> str:
    if r.get("level", 0) < 2:
        return ""
    links = "".join(f'<li><a href="{u}" rel="noopener" target="_blank">{ui.esc(t)}</a></li>' for t, u in REPORT_LINKS)
    return f'<h3 class="sec">Report it</h3><ul class="card small">{links}</ul>'


def season_html() -> str:
    try:
        with store.db() as conn:
            w = defense.active_windows(conn)
    except Exception:                                   # noqa: BLE001
        return ""
    return (f'<div class="banner info" style="margin-bottom:14px"><b>Scam season: {ui.esc(w[0]["name"])}.</b> {ui.esc(w[0]["note"])}</div>' if w else "")


def _thread_form(text: str = "", me: str = "") -> str:
    return f"""<form method="post" action="/check/thread" class="card">
<input type="hidden" name="csrf" value="{security.make_csrf('form')}">
<div class="form-field"><label for="t-text">The whole conversation</label>
<p class="hint">Paste every message in order: an email chain, a text or WhatsApp export, LinkedIn or Handshake DMs. Scams follow a script over several messages, so the whole thread shows where you are in it and what usually comes next. It isn't saved unless you send it to reviewers, except a small random share of results we call safe, which a reviewer double-checks (no name; emails and phone numbers masked).</p>
<textarea id="t-text" name="text" required maxlength="20000" data-count style="min-height:260px" placeholder="Recruiter: Hi! You've been selected for a remote assistant role...&#10;Me: Thanks, what are the next steps?&#10;Recruiter: Please text our hiring manager on Telegram...">{ui.esc(text)}</textarea></div>
<div class="form-field"><label for="t-me">Your name or email in the thread (optional)</label>
<input id="t-me" name="me" maxlength="120" value="{ui.esc(me)}" placeholder="So we can tell your messages from theirs"></div>
<button class="submit-btn" type="submit">Check this conversation</button></form>"""


_STAGE_NAMES = {"hook": "The pitch", "legitimacy": "Looking legit", "channel_switch": "Moved you off the platform",
                "onboarding": "Onboarding", "data_grab": "Asked for bank or ID details", "ask": "Asked for money",
                "pressure": "Pressure"}


def thread_html(a: dict) -> str:
    rows = ""
    for t in a.get("turns", []):
        if t.get("speaker") != "them":
            continue
        chips = "".join(f'<span class="pill {"bad" if s in ("ask", "data_grab", "pressure") else "warn" if s in ("channel_switch", "onboarding") else ""}">'
                        f'{ui.esc(_STAGE_NAMES.get(s, s))}</span>' for s in t.get("stages", []))
        rows += f'<li><div class="row">{chips}</div><span class="ev" style="white-space:pre-wrap">{ui.esc(t["text"][:400])}</span></li>'
    head = ""
    if a.get("warning"):
        head += f'<div class="banner {"warning" if a.get("risk") != "low" else "info"}"><b>{ui.esc(a["warning"])}</b></div>'
    if a.get("next_step"):
        head += f'<p class="card" style="margin-top:10px"><b>What usually comes next:</b> {ui.esc(a["next_step"])}</p>'
    return head + (f'<h3 class="sec">The conversation, step by step</h3><ol class="reasons card">{rows}</ol>' if rows else "")
