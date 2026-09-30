"""The Guardian: the student home ("The Gallery"), each listing's Security Report with its scan HUD, and the HUD layout the
public scam check (/check) reuses.

  * /                     for students: The Gallery. A few live listings picked for this student (fit %, one per employer
                          first, verified employers and recent postings preferred), true stats, and a "Needs your attention"
                          strip that only shows when something needs them.
  * /job/ID/report        the Security Report: the threat bar, a detection matrix of the scanner modules that ran on this
                          listing, and the evidence (each finding with the words it matched). Students (live listings),
                          the employer that owns the listing, and reviewers. A student's first visit (or ?scan=1) plays the
                          scan: a pure-CSS radar and log that hands over to the report after about 2.5 seconds. No script
                          is needed, and reduced motion shows the report at once.
  * POST /job/ID/hide     "Hide from my gallery" (and /unhide).

Nothing on these pages is made up: the modules, statuses, values and log lines all come from the listing's stored scanner
output (jobs.findings_json), the local compensation check the scanner runs, and the employer's review status.
Tables: report_views (which reports a student has opened) and gallery_hidden (listings a student hid), both in store.SCHEMA,
purged with their listing and deleted with the account, and in the student's data export.
demo/app.js has twins of the markup (gdModules, gdReport, gdScan, gallery)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import css_guardian  # noqa: F401  (appends the gallery and HUD styles to ui.THEME_CSS)
import security
import store
import ui
import web
from ui import esc
from scam_detector import rules as _rules
from scam_detector.enrichment.compensation import check_compensation

router = APIRouter()

# ---------- the scanner's modules ----------
# Each finding the detector can produce belongs to one module. Language is the catch-all for text rules not named below.
MODULES = [
    # key, tile name, long name (scan list), rule ids, value when it ran and found nothing
    ("language", "Language", "Language patterns", set(), "No scam phrasing"),
    ("payment", "Payment", "Payment requests",
     {"advance_fee", "money_mule", "irreversible_pay", "fake_check_funds", "startup_cost", "pay_to_work", "crypto_atm",
      "reship_home", "mule_combo", "task_scam", "app_boost_task", "mystery_shopping"}, "No payment asks"),
    ("contact", "Contact", "Contact channel",
     {"off_platform", "text_interview", "personal_channel", "brand_recruiter_text", "unsolicited_contact", "chat_link"},
     "No off-platform push"),
    ("pay", "Pay", "Pay anomaly", {"pay_anomaly", "implied_hourly", "weekly_stipend", "too_good", "income_claim"}, "No pay anomaly"),
    ("identity", "Identity", "Identity & email",
     {"personal_email", "personal_sender", "fsu_lookalike", "display_spoof", "banking_pii", "pii_upfront", "new_domain",
      "unregistered_domain", "no_mail"}, "No ID or bank asks"),
    ("link", "Link", "Link forensics", {"short_link", "ip_link", "fsu_lookalike_link", "form_link", "lead_gen"}, "Apply link clean"),
    ("model", "Model", "Learned model", {"model_second_look"}, ""),
]
_OF = {rid: key for key, _, _, ids, _ in MODULES for rid in ids}
LEVELS = ["SECURE", "LOW", "ELEVATED", "CRITICAL"]          # from the scorer's bands: clear, caution, review, block
BAND_LEVEL = {"clear": 0, "caution": 1, "review": 2, "block": 3}
SEV = {"critical": "CRITICAL", "warning": "WARNING", "note": "NOTE"}
SEV_ORDER = {"critical": 0, "warning": 1, "note": 2}


def module_of(rule_id: str) -> str:
    return _OF.get(rule_id or "", "language")


def pay_value(comp: dict | None) -> str:
    """The Pay tile's value from the scanner's compensation check (scam_detector/enrichment/compensation.py)."""
    c = comp or {}
    if c.get("ratio_to_median"):
        return f'{c["ratio_to_median"]:.1f}× national median'
    return {"no_pay_found": "No pay figure stated", "title_unmapped": "No pay benchmark for role"}.get(c.get("status", ""), "")


def modules(findings: list[dict], *, link_ran: bool, comp: dict | None = None, employer: str | None = None) -> list[dict]:
    """The modules that ran, each {key, name, long, st: o|w|r, value, hits}. `employer` adds the Employer tile for a
    listing on the board: approved | pending | none."""
    out = []
    for key, name, long, _, clear in MODULES:
        hits = [f for f in findings if module_of(f.get("rule_id", "")) == key]
        if key == "link" and not (link_ran or hits):
            continue
        if key == "model" and not hits:
            continue                                   # the model only shows when it spoke up
        if hits:
            hits.sort(key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), -int(f.get("weight") or 0)))
            st = "r" if any(f.get("severity") == "critical" for f in hits) else "w"
            value = hits[0].get("title", "")
            if key == "pay" and (comp or {}).get("status") == "flagged":
                value = pay_value(comp)
        else:
            st, value = "o", (pay_value(comp) or clear) if key == "pay" else clear
        out.append({"key": key, "name": name, "long": long, "st": st, "value": value, "hits": hits})
    if employer is not None:
        st, value = {"approved": ("o", "Verified by a reviewer"), "pending": ("w", "Employer not verified yet")}.get(employer, ("w", "No employer account"))
        out.append({"key": "employer", "name": "Employer", "long": "Employer record", "st": st, "value": value, "hits": []})
    return out


def code_for(prefix: str, n: int) -> str:
    """'GA-0012': the company's initials and the listing number, as in the mock's REQ #BS-4417."""
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z]+", prefix or "")[:2]).upper() or "NC"
    return f"{letters}-{int(n):04d}"


def check_code(text: str) -> str:
    return "CHK-" + hashlib.sha1((text or "").encode()).hexdigest()[:4].upper()


def _sev_cls(f: dict) -> str:
    return "r" if f.get("severity") == "critical" else "w"


def _matched(f: dict) -> list[str]:
    out = []
    for m in f.get("matched") or []:
        m = str(m or "").strip().strip('"“”').strip()
        if m and m != "user-observed":
            out.append(m)
    return out


# ---------- the report ----------

def threat_bar(shown: int, level: int, verdict: str, n: int, strongest: str) -> str:
    lit = max(1, round(shown / 100 * 11)) if shown else 0
    segs = "".join(f'<i{" class=on" if i < lit else ""}></i>' for i in range(11))
    meta = f'<span>Matched <b>{n} signal{"s" if n != 1 else ""}</b></span>'
    if strongest:
        meta += f'<span>Strongest <b>{esc(strongest)}</b></span>'
    arrow = "▲" if level >= 2 else "●"
    return (f'<div class="gd-threat lv{level}"><div class="gd-tnum"><b>{int(shown)}</b><small>Risk / 100</small></div>'
            f'<div class="gd-tbody"><div class="gd-tlv">{arrow} Threat level · {LEVELS[level]}</div><div class="gd-tcls">{esc(verdict)}</div>'
            f'<div class="gd-lvl" aria-hidden="true">{segs}</div><div class="gd-tmeta">{meta}</div></div></div>')


def _tile(m: dict) -> str:
    state = {"r": "critical", "w": "flag"}.get(m["st"], "clear")
    more = len(m["hits"]) - 1
    extra = f" <small>+{more}</small>" if more > 0 else ""
    return (f'<div class="gd-mx {m["st"]}"><div class="n">{esc(m["name"])}<i class="dt" aria-hidden="true"></i>'
            f'<span class="sr"> · {state}</span></div><div class="v">{esc(m["value"])}{extra}</div></div>')


def matrix(mods: list[dict]) -> str:
    tiles = "".join(_tile(m) for m in mods)
    return (f'<div class="gd-sech"><span>Detection matrix</span><span>{len(mods)} module{"s" if len(mods) != 1 else ""}</span></div>'
            f'<div class="gd-matrix">{tiles}</div>')


def evidence(findings: list[dict], *, full: bool = True, lead_gen: dict | None = None, limit: int = 8) -> str:
    """Each finding: title, severity, the exact words it matched (full view only) and why it matters. Kept in a
    <ul class="reasons"> of plain <li>s, which the scam check's tests read."""
    items = []
    for f in findings[:limit]:
        m = _matched(f) if full else []
        code = ("".join(f'<code>“{esc(x)}”</code>' for x in m[:3]))
        found = f'<div class="gd-found"><span class="sr">Found: </span>{code}</div>' if code else ""
        items.append(f'<li><div class="gd-e {_sev_cls(f)}"><span class="k">{SEV.get(f.get("severity"), "NOTE")}</span>'
                     f'<b>{esc(f.get("title", ""))}</b>{found}<p>{esc(f.get("why", ""))}</p></div></li>')
    if (lead_gen or {}).get("flag") and not any(f.get("rule_id") == "lead_gen" for f in findings) and len(items) < limit:
        items.append(f'<li><div class="gd-e w"><span class="k">WARNING</span><b>Looks like a data-harvesting or aggregator ad</b>'
                     f'<p>{esc(lead_gen.get("verdict", "")) if full else ""}</p></div></li>')
    if not items:
        items.append('<li><div class="gd-e o"><span class="k">CLEAR</span><b>No scam patterns matched.</b>'
                     f'<p>The detector checked {len(_rules.RULES)} known student-scam patterns, the pay, the contact details and the links.</p></div></li>')
    return (f'<div class="gd-sech"><span>Evidence</span><span>{"exact matches" if full else "top signals"}</span></div>'
            f'<ul class="reasons">{"".join(items)}</ul>')


def hud(inner: str, cls: str = "", label: str = "") -> str:
    lab = f' aria-label="{esc(label)}"' if label else ""
    return (f'<section class="gd-hud {cls}"{lab}><i class="gd-c c1" aria-hidden="true"></i><i class="gd-c c2" aria-hidden="true"></i>'
            f'<i class="gd-c c3" aria-hidden="true"></i><i class="gd-c c4" aria-hidden="true"></i>{inner}</section>')


def report(*, code: str, title: str, sub: str, shown: int, level: int, findings: list[dict], mods: list[dict],
           foot_left: str, foot_right: str, actions: str = "", close: str = "", full: bool = True, lead_gen: dict | None = None,
           note: str = "") -> str:
    top = sorted(findings, key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), -int(f.get("weight") or 0)))
    verdict = top[0]["title"] if top else "No known scam pattern"
    strongest = SEV.get(top[0].get("severity"), "") if top else ""
    head = (f'<div class="gd-hh"><span>Security report · #{esc(code)}</span>{close}</div>'
            f'<h1 class="gd-ht">{esc(title)}</h1><div class="gd-hs">{esc(sub)}</div>')
    body = (threat_bar(shown, level, verdict, len(findings), strongest) + note + matrix(mods)
            + evidence(top, full=full, lead_gen=lead_gen))
    foot = (f'<div class="gd-rf"><div class="gd-hash"><span>{esc(foot_left)}</span><span>{esc(foot_right)}</span></div>'
            f'{f"<div class=gd-acts>{actions}</div>" if actions else ""}</div>')
    return hud(head + body + foot, "gd-report", "Security report")


# ---------- the scan (pure CSS; see css_guardian.py) ----------

def _blip_xy(i: int) -> tuple[float, float, float]:
    """A spot on the radar for the i-th finding (golden-angle spread) and the angle, so the blip lights as the beam passes."""
    ang = (38 + i * 137.5) % 360
    r = 24 + (i * 7) % 16
    import math
    a = math.radians(ang - 90)
    return round(50 + r * math.cos(a), 1), round(50 + r * math.sin(a), 1), ang


def log_lines(findings: list[dict], mods: list[dict], ruleset: str) -> list[tuple[str, str]]:
    """(html, class) lines for the scan log: the ruleset, what matched (the exact words), what came back clear."""
    out = [(f'&gt; <b>load</b> ruleset {esc(ruleset or "?")} · {len(_rules.RULES)} patterns', "")]
    for f in sorted(findings, key=lambda f: SEV_ORDER.get(f.get("severity"), 3))[:3]:
        m = _matched(f)
        what = f'“{esc(m[0][:46])}”' if m else esc(module_of(f.get("rule_id", "")))
        out.append((f'&gt; <b>match</b> {what} · <span class="{_sev_cls(f)}">{esc(f.get("title", "").lower())}</span>', ""))
    clear = [m["long"] for m in mods if m["st"] == "o"]
    if clear:
        out.append((f'&gt; <b>clear</b> <span class="o">{esc(", ".join(clear[:4]).lower())}</span>', ""))
    out.append(('&gt; <span class="g">compiling security report<i class="gd-cur">_</i></span>', ""))
    return out


def scan(*, code: str, title: str, company: str, findings: list[dict], mods: list[dict], ruleset: str) -> str:
    blips = []
    for i, f in enumerate(findings[:6]):
        x, y, ang = _blip_xy(i)
        lab = (f.get("rule_id") or "").replace("_", " ").upper()[:18]
        blips.append(f'<span class="gd-blip {_sev_cls(f)}" style="left:{x}%;top:{y}%;--d:{round(ang / 360 * 1.6, 2)}s"><small>{esc(lab)}</small></span>')
    rows = []
    for i, m in enumerate(mods):
        n = len(m["hits"])
        stt = "CLEAR" if m["st"] == "o" else (f"{n} HITS" if n > 1 else "CRITICAL" if m["st"] == "r" else "FLAG")
        rows.append(f'<div class="gd-mod" style="--i:{i}"><span>{esc(m["long"])}</span><span class="pb"><i></i></span>'
                    f'<span class="s {m["st"]}">{stt}</span></div>')
    logs = "".join(f'<div style="--i:{i}">{h}</div>' for i, (h, _) in enumerate(log_lines(findings, mods, ruleset)))
    radar = (f'<div class="gd-radar"><div class="gd-tick"></div><div class="gd-ring r0"></div><div class="gd-ring r1"></div><div class="gd-ring r2"></div>'
             f'<div class="gd-cross"></div><div class="gd-beam"></div>{"".join(blips)}<div class="gd-core">{ui.crest(40, key="scan")}</div></div>')
    inner = (f'<div class="gd-hh"><span><i class="gd-led"></i>Guardian scan engine · active</span><span>REQ #{esc(code)}</span></div>'
             f'<div class="gd-ht">{esc(title)}</div><div class="gd-hs">{esc(company)} · {len(mods)} detection modules running</div>'
             f'{radar}<div class="gd-pct"><b></b><span>Analysis complete</span></div><div class="gd-mods">{"".join(rows)}</div>'
             f'<div class="gd-log">{logs}</div>')
    return (f'<div class="gd-scan" aria-hidden="true"><i class="gd-c c1"></i><i class="gd-c c2"></i><i class="gd-c c3"></i>'
            f'<i class="gd-c c4"></i>{inner}</div>')


def stage(report_html: str, scan_html: str = "") -> str:
    """The report, with the scan played over it first when scan_html is given."""
    if not scan_html:
        return f'<div class="gd-stage">{report_html}</div>'
    return f'<div class="gd-stage anim">{scan_html}{report_html}</div>'


# ---------- a listing on the board ----------

def _findings(j: dict) -> list[dict]:
    try:
        return json.loads(j.get("findings_json") or "[]")
    except ValueError:
        return []


def is_lead_gen(j: dict) -> bool:
    return any(f.get("rule_id") == "lead_gen" for f in _findings(j))


def shown_score(j: dict) -> int:
    return ui.shown_score(int(j.get("score") or 0), is_lead_gen(j))


def level_of_job(j: dict) -> int:
    lvl = BAND_LEVEL.get(j.get("band") or "", 0)
    if j.get("scam_status") == "flagged":
        lvl = max(lvl, 1)
    if j.get("scam_status") == "held":
        lvl = 3
    return lvl


def employer_state(conn, j: dict) -> str:
    if not j.get("employer_id"):
        return "none"
    return "approved" if store.employer_approved(conn, int(j["employer_id"])) else "pending"


def job_modules(conn, j: dict) -> list[dict]:
    comp = check_compensation(j.get("title", ""), j.get("description", "")).as_dict()
    return modules(_findings(j), link_ran=bool(j.get("apply_url")), comp=comp, employer=employer_state(conn, j))


def _posted_on(j: dict) -> str:
    try:
        d = dt.datetime.fromisoformat(str(j.get("created_at"))[:19])
    except ValueError:
        return ""
    return f"{d:%b} {d.day}, {d.year}"


def opened_ids(conn, uid: int) -> set[int]:
    return {r[0] for r in conn.execute("SELECT job_id FROM report_views WHERE user_id = ?", (uid,))}


def hidden_ids(conn, uid: int) -> set[int]:
    return {r[0] for r in conn.execute("SELECT job_id FROM gallery_hidden WHERE user_id = ?", (uid,))}


def chip(j: dict, opened: set | None = None, link: bool = True) -> str:
    """The card's scan chip. For a student (`opened` given) it stays idle ("Run scan") until they have opened the listing's
    report, then shows the real result; either way it links to the report. Without `opened`, the real result."""
    jid, sc = int(j["id"]), shown_score(j)
    if opened is not None and jid not in opened:
        return ui.scan_chip("idle", label="Scam risk report · run scan", href=f"/job/{jid}/report?scan=1" if link else "")
    return ui.scan_chip(ui.scan_state(j["scam_status"]), sc, label=f"Scam risk {sc} · {j['scam_status']}",
                        href=f"/job/{jid}/report" if link else "")


def job_report(conn, j: dict, *, viewer: str, animate: bool, hidden: bool = False) -> str:
    """viewer: student | employer | reviewer."""
    jid = int(j["id"])
    findings = _findings(j)
    mods = job_modules(conn, j)
    code = code_for(j["company"], jid)
    posted = _posted_on(j)
    sub = f'{j["company"]} · scanned when it was posted' + (f", {posted}" if posted else "")
    right = ("Reviewed by a person before publishing" if j.get("review_status") == "approved"
             else "Waiting for a reviewer" if j.get("review_status") == "pending" else "Not on the board")
    close, actions = "", ""
    if viewer == "student":
        close = f'<a class="gd-x" href="/job/{jid}" aria-label="Close the report and open the listing">✕ Close</a>'
        csrf = ui.user_csrf_input()
        hide = (f'<form method="post" action="/job/{jid}/{"unhide" if hidden else "hide"}">{csrf}'
                f'<button class="gd-btn o" type="submit">{"Show in my gallery again" if hidden else "Hide from my gallery"}</button></form>')
        actions = f'<a class="gd-btn g" href="/report">Report this listing</a>{hide}'
    elif viewer == "employer":
        actions = f'<a class="gd-btn o" href="/hiring/{jid}">Back to your listing</a>'
    else:
        actions = '<a class="gd-btn o" href="/admin">Back to the review queue</a>'
    rep = report(code=code, title=j["title"], sub=sub, shown=shown_score(j), level=level_of_job(j), findings=findings, mods=mods,
                 foot_left=f'Ruleset {j.get("ruleset_version") or "unknown"}', foot_right=right, actions=actions, close=close)
    sc = scan(code=code, title=j["title"], company=j["company"], findings=findings, mods=mods, ruleset=j.get("ruleset_version") or "") if animate else ""
    return stage(rep, sc)


def _is_reviewer(request: Request) -> bool:
    return security.session_valid(request.cookies.get("session"))


def _get_job(conn, job_id: int) -> dict | None:
    return store.row(conn, "SELECT * FROM jobs WHERE id = ?", (int(job_id),))


@router.get("/job/{job_id}/report", response_class=HTMLResponse)
def job_report_page(job_id: int, request: Request, scan: int = 0, hidden: int = 0):
    security.enforce_rate_limit(request, security.general_limiter, "job_report")
    user = web.current_user(request)
    reviewer = _is_reviewer(request)
    with store.db() as conn:
        j = _get_job(conn, job_id)
        role = ""
        if user and user["role"] == "student" and j and store.visible_listing(j):
            role = "student"
        elif user and user["role"] == "employer" and j and j.get("employer_id") == store.org_id(user):
            role = "employer"
        elif reviewer and j:
            role = "reviewer"
        if not role:
            if not user and not reviewer:
                raise web.LoginRequired("student", f"/job/{int(job_id)}/report")
            return web.page('<p class="empty" style="margin:40px 0">That report isn\'t available.</p>', "Security report", active="/jobs", status=404)
        animate = bool(scan)
        is_hidden = False
        if role == "student":
            seen = conn.execute("SELECT 1 FROM report_views WHERE user_id = ? AND job_id = ?", (user["id"], int(j["id"]))).fetchone()
            animate = animate or not seen
            if not seen:
                conn.execute("INSERT OR IGNORE INTO report_views (user_id, job_id, created_at) VALUES (?,?,?)", (user["id"], int(j["id"]), time.time()))
            is_hidden = bool(conn.execute("SELECT 1 FROM gallery_hidden WHERE user_id = ? AND job_id = ?", (user["id"], int(j["id"]))).fetchone())
        body = job_report(conn, j, viewer=role, animate=animate, hidden=is_hidden)
    note = ""
    if role == "student" and hidden in (1, 2):
        note = ui.banner("info", "Hidden from your gallery. It stays on the job board." if hidden == 1 else "Back in your gallery.")
    back = {"student": ("/", "← The gallery"), "employer": (f"/hiring/{int(job_id)}", "← Your listing"), "reviewer": ("/admin", "← Review queue")}[role]
    page = f'<div class="gd-page"><a class="back" href="{back[0]}">{back[1]}</a>{note}{body}</div>'
    title = f'Security report: {j["title"]}'
    if role == "reviewer" and not user:
        return HTMLResponse(ui.shell(page, title=f"{esc(title)} — NoleCareerShield", admin=True))
    return web.page(page, esc(title), active="/jobs" if role == "student" else "/hiring")


def _toggle_hidden(job_id: int, request: Request, csrf: str, on: bool):
    user = web.require_user(request, "student")
    if not web.csrf_ok(request, csrf):
        return RedirectResponse(f"/job/{int(job_id)}/report", status_code=303)
    with store.db() as conn:
        j = _get_job(conn, job_id)
        if j and store.visible_listing(j):
            if on:
                n = conn.execute("SELECT COUNT(*) FROM gallery_hidden WHERE user_id = ?", (user["id"],)).fetchone()[0]
                if n < 500:
                    conn.execute("INSERT OR IGNORE INTO gallery_hidden (user_id, job_id, created_at) VALUES (?,?,?)", (user["id"], int(job_id), time.time()))
            else:
                conn.execute("DELETE FROM gallery_hidden WHERE user_id = ? AND job_id = ?", (user["id"], int(job_id)))
    return RedirectResponse(f"/job/{int(job_id)}/report?hidden={1 if on else 2}", status_code=303)


@router.post("/job/{job_id}/hide")
def hide(job_id: int, request: Request, csrf: str = Form("")):
    return _toggle_hidden(job_id, request, csrf, True)


@router.post("/job/{job_id}/unhide")
def unhide(job_id: int, request: Request, csrf: str = Form("")):
    return _toggle_hidden(job_id, request, csrf, False)


# ---------- the public / student scam check (/check) ----------

def check_report(r: dict, full: bool = True) -> str:
    """msgcheck's result (check or check_listing) in the same HUD. It is not on the board, so the footer says where it came from."""
    listing = r.get("kind") == "listing"
    findings = r.get("findings") or []
    link_ran = True                                   # msgcheck reads every link in the text (and the apply link) as text
    mods = modules(findings, link_ran=link_ran, comp=r.get("comp"))
    subject = r.get("subject") or ("A job listing you pasted" if listing else "A message you pasted")
    company = r.get("company") or ""
    code = check_code(r.get("digest") or subject + company)
    src = ("SCANNED FROM YOUR LINK" if r.get("url") else "SCANNED FROM YOUR TEXT")
    sub = (company + " · " if company else "") + "checked just now"
    lead_gen = r.get("lead_gen") or {}
    shown = ui.shown_score(int(r.get("score") or 0), bool(lead_gen.get("flag")))
    if not full:            # visitors get the verdict and up to three plain reasons (msgcheck.PUBLIC_REASONS)
        shown_f = [f for f in findings if f.get("severity") != "note"][:3] or findings[:3]
    else:
        shown_f = findings
    note = (f'<div class="gd-verdict {esc(r.get("key", ""))}"><span class="eyebrow">Verdict</span><b>{esc(r.get("title", ""))}</b>'
            f'<p>{esc(r.get("advice", ""))}</p></div>')
    plat = r.get("platform_employer")
    if plat:
        note += (f'<p class="gd-plat">Sent through NoleCareerShield by <b>{esc(plat.get("company", ""))}</b>, '
                 f'{"an employer our reviewers approved" if plat.get("status") == "approved" else "an employer our reviewers have not approved"}.</p>')
    top = sorted(shown_f, key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), -int(f.get("weight") or 0)))
    verdict = (sorted(findings, key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), -int(f.get("weight") or 0)))[0]["title"]
               if findings else "No known scam pattern")
    strongest = SEV.get(sorted(findings, key=lambda f: SEV_ORDER.get(f.get("severity"), 3))[0].get("severity"), "") if findings else ""
    head = (f'<div class="gd-hh"><span>Security report · #{esc(code)}</span><span>{"Listing" if listing else "Message"}</span></div>'
            f'<h2 class="gd-ht">{esc(subject)}</h2><div class="gd-hs">{esc(sub)}</div>')
    body = (threat_bar(shown, int(r.get("level") or 0), verdict, len(findings), strongest) + note + matrix(mods)
            + evidence(top, full=full, lead_gen=lead_gen))
    foot = (f'<div class="gd-rf"><div class="gd-hash"><span>Ruleset {esc(r.get("ruleset") or "")}</span>'
            f'<span>Not on NoleCareerShield · {src}</span></div></div>')
    return f'<div class="gd-stage gd-check">{hud(head + body + foot, "gd-report", "Scam check result")}</div>'


# ---------- The Gallery (student home) ----------

NUM_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}
GALLERY_SIZE = 6
_PAY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d\d)?)(?:\s?(?:-|–|to)\s?\$?\s?(\d[\d,]*(?:\.\d\d)?))?\s*(?:/|per\s+|an?\s+|each\s+)?\s*"
                  r"(hour|hr|week|wk|month|mo|year|yr)\b|\$\s?(\d[\d,]*)\s+(weekly|monthly|hourly|annually)", re.IGNORECASE)
_UNIT = {"hour": "hour", "hr": "hour", "hourly": "hour", "week": "week", "wk": "week", "weekly": "week", "month": "month",
         "mo": "month", "monthly": "month", "year": "year", "yr": "year", "annually": "year"}


def pay_of(text: str) -> tuple[str, str] | None:
    """The first pay figure stated in a listing, as ("$19", "/hour") or ("$18–22", "/hour"). None when it doesn't state one."""
    m = _PAY.search(text or "")
    if not m:
        return None
    if m.group(4):
        return f"${m.group(4)}", "/" + _UNIT[m.group(5).lower()]
    lo, hi = m.group(1), m.group(2)
    trim = lambda s: s[:-3] if s.endswith(".00") else s
    return (f"${trim(lo)}–{trim(hi)}" if hi else f"${trim(lo)}"), "/" + _UNIT[m.group(3).lower()]


def _logo_tone(name: str) -> int:
    return int(hashlib.md5((name or "").lower().encode()).hexdigest()[:2], 16) % 4


def curate(jobs: list[dict], profile: dict | None, verified: set, hidden: set, n: int = GALLERY_SIZE) -> list[dict]:
    """The best n live listings for this student: fit % first, then verified employers and recent postings, with one listing
    per employer before any employer gets a second. [{job, fit (dict or None)}]."""
    import fit
    import jobboard
    rich = jobboard.has_profile(profile)
    scored = []
    for j in jobs:
        if int(j["id"]) in hidden:
            continue
        f = fit.fit_score(j, profile) if rich else None
        rank = (f["score"] if f else 0) + (12 if j.get("employer_id") in verified else 0) + max(0.0, 14 - jobboard.days_old(j))
        scored.append((rank, int(j["id"]), j, f))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    picked, seen = [], set()
    for second in (False, True):
        for _, jid, j, f in scored:
            if len(picked) >= n:
                break
            key = j.get("employer_id") or (j.get("company") or "").strip().lower()
            if any(p["job"]["id"] == j["id"] for p in picked) or (not second and key in seen):
                continue
            picked.append({"job": j, "fit": f})
            seen.add(key)
    return picked


def gcard(j: dict, f: dict | None, verified: bool, opened: set | None) -> str:
    import jobboard
    jid = int(j["id"])
    badge = (ui.verified_badge() if verified else
             f'<span class="unv">{"Employer not verified yet" if j.get("employer_id") else "No employer account"}</span>')
    place, setting = jobboard.where(j), (j.get("work_type") or "").title()
    kinds = ", ".join(jobboard.KIND_LABEL[k] for k in jobboard.kinds_of(j)[:1])
    meta = " · ".join(x for x in (place, "" if place == setting else setting, kinds) if x)
    import fit as _fit
    req = (f or {}).get("requirements") or _fit.job_requirements(j.get("title", ""), j.get("description", ""))
    skills = list(dict.fromkeys((req.get("required") or []) + (req.get("preferred") or [])))[:2]
    tags = "".join(f'<span class="tag">{esc(s)}</span>' for s in skills)
    if f:
        tags += f'<span class="tag m">{int(f["score"])}% match</span>'
    pay = pay_of(j.get("description", ""))
    pay_html = f'<div class="pay">{esc(pay[0])}<small>{esc(pay[1])}</small></div>' if pay else '<div class="pay none"></div>'
    return (f'<article class="card gcard"><div class="hd"><span class="g-logo t{_logo_tone(j["company"])}" aria-hidden="true">{ui.initials(j["company"])}</span>'
            f'<div class="g-who"><div class="co">{esc(j["company"])}</div>{badge}</div></div>'
            f'<h3><a class="g-link" href="/job/{jid}">{esc(j["title"])}</a></h3><div class="meta">{esc(meta)}</div>'
            f'{f"<div class=tags>{tags}</div>" if tags else ""}<div class="foot">{pay_html}{chip(j, opened)}</div></article>')


def _threats_this_week(conn) -> int:
    """Listings and messages the scanner held or flagged in the last 7 days that never reached students: listings a reviewer
    rejected or removed (or still held for review), and held messages that were never delivered."""
    since = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
    jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE scam_status IN ('held','flagged') AND created_at >= ? AND "
                        "(review_status IN ('rejected','removed') OR (review_status = 'pending' AND scam_status = 'held'))", (since,)).fetchone()[0]
    msgs = conn.execute("SELECT COUNT(*) FROM messages WHERE scan_band = 'block' AND status != 'delivered' AND created_at >= ?",
                        (time.time() - 7 * 86400,)).fetchone()[0]
    return int(jobs) + int(msgs)


def _next_up(conn, uid: int) -> tuple[str, str, str] | None:
    """(label, value, href) for the next confirmed interview, else the next event the student is going to."""
    import scheduling
    iv = scheduling.upcoming_interviews(conn, uid, limit=1)
    if iv:
        d = scheduling.to_et(iv[0]["starts_at"])
        return f"Interview {scheduling._DAYS[d.weekday()]}", scheduling._hm(d), iv[0]["url"]
    r = store.row(conn, "SELECT e.id, e.starts_at FROM event_rsvps r JOIN events e ON e.id = r.event_id WHERE r.student_id = ? AND "
                        "r.status = 'going' AND e.status = 'approved' AND e.starts_at > ? ORDER BY e.starts_at LIMIT 1", (uid, time.time()))
    if r:
        d = scheduling.to_et(r["starts_at"])
        return f"Event {scheduling._DAYS[d.weekday()]}", scheduling._hm(d), f"/events/{int(r['id'])}"
    return None


def _attention(conn, uid: int, unread: int, ready: bool) -> list[tuple[str, str, str]]:
    """(text, href, tone) items for "Needs your attention". Empty when nothing does."""
    import scheduling
    out = []
    if unread:
        out.append((f"{unread} unread message{'s' if unread != 1 else ''}", "/messages", "g"))
    for p in store.rows(conn, "SELECT p.conversation_id, p.employer_id FROM interview_proposals p WHERE p.student_id = ? AND p.status = 'open' "
                              "ORDER BY p.updated_at DESC LIMIT 2", (uid,)):
        who = web.display_name(conn, p["employer_id"], "employer")[0]
        out.append((f"Pick a time for your interview with {who}", f"/messages/{int(p['conversation_id'])}", "g"))
    today = scheduling.to_et(time.time()).date()
    for e in store.rows(conn, "SELECT e.id, e.title, e.starts_at FROM event_rsvps r JOIN events e ON e.id = r.event_id WHERE r.student_id = ? AND "
                              "r.status = 'going' AND e.status = 'approved' AND e.starts_at BETWEEN ? AND ? ORDER BY e.starts_at LIMIT 2",
                        (uid, time.time(), time.time() + 3 * 86400)):
        day = scheduling.to_et(e["starts_at"]).date()
        when = "today" if day == today else "tomorrow" if day == today + dt.timedelta(days=1) else ""
        if when:
            out.append((f"{e['title']} is {when} at {scheduling._hm(scheduling.to_et(e['starts_at']))} ET", f"/events/{int(e['id'])}", "o"))
    closed = conn.execute(f"SELECT COUNT(*) FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.student_id = ? AND NOT {store.live_where('j', security.LISTING_TTL_DAYS)}",
                          (uid,)).fetchone()[0]
    if closed:
        out.append((f"{closed} listing{'s' if closed != 1 else ''} you applied to {'have' if closed != 1 else 'has'} closed", "/applications", ""))
    if not ready:
        out.append(("Finish your profile so your matches get sharper", "/profile/setup", ""))
    return out


def gallery(user: dict) -> str:
    uid = user["id"]
    with store.db() as conn:
        p = store.student_profile(conn, uid) or {}
        jobs = store.live_jobs(conn, security.LISTING_TTL_DAYS)
        emp_ids = {int(j["employer_id"]) for j in jobs if j.get("employer_id")}
        verified = {e for e in emp_ids if store.employer_approved(conn, e)}
        hidden = hidden_ids(conn, uid)
        opened = opened_ids(conn, uid)
        unread = store.unread_count(conn, uid)
        n_saved = conn.execute(f"SELECT COUNT(*) FROM saved_jobs s JOIN jobs j ON j.id = s.job_id WHERE s.user_id = ? AND {store.live_where('j', security.LISTING_TTL_DAYS)}",
                               (uid,)).fetchone()[0]
        threats = _threats_this_week(conn)
        nxt = _next_up(conn, uid)
        import profiles
        attention = _attention(conn, uid, unread, profiles.student_ready(p))
        picks = curate(jobs, p, verified, hidden)
    first = (p.get("display_name") or "").split(" ")[0]
    n = len(picks)
    day = dt.datetime.now().strftime("%A")
    who = f", <em>{esc(first)}.</em>" if first else "."
    if n:
        h1 = f'{NUM_WORDS.get(n, str(n))} role{"s" if n != 1 else ""} worth your time{who}' if first else f'{NUM_WORDS.get(n, str(n))} role{"s" if n != 1 else ""} worth <em>your time.</em>'
        word = NUM_WORDS.get(n, str(n)).lower()
        sub = (f"Every one scam-scanned and approved by a person before it reached you. We'd rather show you {word} real "
               f"one{'s' if n != 1 else ''} than {word} hundred maybes.")
    else:
        h1 = f"The gallery is quiet{who}" if first else "The gallery is <em>quiet.</em>"
        sub = ("You've hidden every live listing. They're all still on the job board." if jobs else
               "No live listings right now. Reviewers approve new ones every day, and they show up here first.")
    chips = [("All", "/jobs", True), ("Internships", "/jobs?kind=internship", False), ("Part-time", "/jobs?kind=part-time", False),
             ("Remote", "/jobs?work_type=remote", False)]
    bar = ('<form class="gal-bar" method="get" action="/jobs" role="search"><label class="sr" for="gal-q">Describe the role you want</label>'
           f'<div class="gal-search">{ui.icon("search", 18)}<input id="gal-q" name="search" maxlength="200" autocomplete="off" '
           'placeholder="Describe the role you want, e.g. “paid data internship in Tallahassee”"><button type="submit">Search</button></div>'
           '<nav class="gal-chips" aria-label="Quick filters">' + "".join(f'<a class="gchip{" on" if on else ""}" href="{h}">{t}</a>' for t, h, on in chips)
           + "</nav></form>")
    stats = [("Verified employers", len(verified & {int(j["employer_id"]) for j in jobs if j.get("employer_id")}), "g", "/jobs"),
             ("Threats intercepted this week", threats, "r"),
             ("New messages", unread, "", "/messages")]
    if nxt:
        stats.append((nxt[0], nxt[1], "", nxt[2]))
    stats.append(("Saved jobs", n_saved, "", "/jobs?tab=saved"))
    att = ""
    if attention:
        att = ('<section class="gal-att" aria-label="Needs your attention"><span class="h">Needs your attention</span>'
               + "".join(f'<a class="{t}" href="{esc(h)}"><i aria-hidden="true"></i>{esc(x)}</a>' for x, h, t in attention) + "</section>")
    nv = sum(1 for x in picks if x["job"].get("employer_id") in verified)
    note = f"{nv} verified" + (f" · {n - nv} awaiting verification" if n - nv else "") + (f" · {len(hidden)} hidden" if hidden else "")
    if picks:
        cards = "".join(gcard(x["job"], x["fit"], x["job"].get("employer_id") in verified, opened) for x in picks)
        coll = (f'<div class="gal-h"><h2>This week\'s collection</h2><span>{esc(note)}</span></div><div class="gal-grid">{cards}</div>'
                '<p class="gal-more"><a href="/jobs">See all jobs →</a></p>')
    else:
        coll = ('<div class="gal-empty card">' + ui.crest(44, key="galempty") + '<h2>Nothing to show yet</h2>'
                '<p>When a reviewer approves a listing that fits you, it lands here. Meanwhile you can check a listing you found elsewhere.</p>'
                '<p class="row"><a class="b" href="/jobs">Browse the job board</a><a class="b sec" href="/check">Scan a listing</a></p></div>')
    return (f'<section class="gal"><div class="gal-top"><div class="eyebrow">// {day} · the curated gallery</div>'
            f'<h1>{h1}</h1><p class="sub">{esc(sub)}</p></div>{bar}{ui.stat_row(stats)}{att}{coll}</section>')
