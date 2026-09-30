"""
Turn resume text into profile sections, the way Handshake and LinkedIn offer "fill my profile
from my resume": experience, education, projects, certifications, organizations, courses,
languages and skills.

It is a best guess from layout, not magic: every item lands in the profile editor where the
student can fix or delete it before anyone sees it. demo/engine.js has a line-for-line port
that tests/test_demo_engine.py checks against this file.
"""

from __future__ import annotations

import re

from matching import extract_skills
from resume_engine import SECTION_NAMES, _BULLET, parse

KINDS = ["experience", "education", "project", "certification", "organization", "course", "language"]

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|winter|expected)"
_DATE = rf"(?:{_MONTH}\.?\s+)?(?:19|20)\d{{2}}|present|current|now"
DATE_RANGE = re.compile(rf"(?P<start>{_DATE})(?:\s*(?:-|–|—|to)\s*(?P<end>{_DATE}))?", re.IGNORECASE)
SCHOOL = re.compile(r"\b(?:university|college|institute|school|academy)\b", re.IGNORECASE)
DEGREE = re.compile(r"\b(?:b\.?s\.?|b\.?a\.?|bachelor(?:'s)?(?: of (?:science|arts))?|m\.?s\.?|m\.?a\.?|master(?:'s)?(?: of (?:science|arts))?|mba|ph\.?d|"
                    r"associate(?:'s)?(?: of (?:arts|science))?|a\.?a\.?|a\.?s\.?|high school diploma)\b", re.IGNORECASE)
GPA = re.compile(r"\bgpa\b[:\s]*(\d\.\d{1,2})|(\d\.\d{1,2})\s*(?:/\s*4\.0+\s*)?gpa\b", re.IGNORECASE)
SPLIT = re.compile(r"\s+(?:\||–|—|-|·|•|@|at)\s+|,\s+", re.IGNORECASE)
LIST_SPLIT = re.compile(r"[,;|•](?![^()]*\))")
ROLE = re.compile(r"\b(?:intern|analyst|assistant|manager|associate|server|waiter|developer|engineer|generalist|specialist|coordinator|"
                  r"representative|tutor|chair|president|member|volunteer|attendant|advisor|cashier|lead|director|officer|treasurer|"
                  r"secretary|captain|founder|consultant|researcher|clerk|parker|host|barista|teller|designer|writer|editor)\b", re.IGNORECASE)
LABELLED = re.compile(r"^(skills|technical skills|tools|languages|certifications?|licenses?|coursework|relevant coursework|interests)\s*:\s*(.+)$", re.IGNORECASE)

SECTION_KIND = {"experience": "experience", "leadership": "organization", "projects": "project", "education": "education",
                "awards": "certification", "coursework": "course"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip(" \t-–—|,·•")).strip()


def _dates(line: str) -> tuple[str, str, bool, str]:
    """(start, end, current, the line without the dates)."""
    m = None
    for m in DATE_RANGE.finditer(line):
        pass                                             # the last date range on the line
    if not m:
        return "", "", False, line
    start, end = _clean(m.group("start")), _clean(m.group("end") or "")
    if not end and re.fullmatch(r"(?:present|current|now)", start, re.IGNORECASE):
        return "", "", False, line
    current = bool(re.fullmatch(r"(?:present|current|now)", end, re.IGNORECASE))
    if current:
        end = ""
    rest = (line[:m.start()] + " " + line[m.end():]).strip()
    rest = re.sub(r"(?:^|\s)(?:expected|exp\.?)\s*$", "", rest, flags=re.IGNORECASE)
    return start.title() if not start[:1].isdigit() else start, end.title() if end and not end[:1].isdigit() else end, current, rest


def _split_header(text: str) -> list[str]:
    return [p for p in (_clean(x) for x in SPLIT.split(text)) if p]


def _item(kind: str, **kw) -> dict:
    base = {"kind": kind, "title": "", "org": "", "location": "", "start": "", "end": "", "current": False,
            "description": "", "url": "", "extra": {}}
    base.update({k: v for k, v in kw.items() if v not in (None,)})
    return base


def _blocks(lines: list[str]) -> list[tuple[list[str], list[str]]]:
    """Group a section into (header lines, bullet lines) blocks."""
    blocks: list[tuple[list[str], list[str]]] = []
    head: list[str] = []
    body: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        if _BULLET.match(ln):
            body.append(_BULLET.sub("", ln).strip())
            continue
        if body or len(head) >= 2:
            blocks.append((head, body))
            head, body = [], []
        head.append(ln.strip())
    if head or body:
        blocks.append((head, body))
    return blocks


def _entry(kind: str, head: list[str], body: list[str]) -> dict | None:
    start = end = ""
    current = False
    texts = []
    for h in head:
        s, e, c, rest = _dates(h)
        if s and not start:
            start, end, current = s, e, c
        texts.append(rest)
    parts = [p for t in texts for p in _split_header(t)]
    if not parts and not body:
        return None
    title = parts[0] if parts else ""
    org = parts[1] if len(parts) > 1 else ""
    location = ""
    for p in parts[2:]:
        if re.search(r"\b[A-Z][a-z]+,?\s+(?:[A-Z]{2}|Florida)\b", p) or re.fullmatch(r"remote|hybrid|on-?site", p, re.IGNORECASE):
            location = p
            break
    if location == "" and len(parts) > 3 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
        location = f"{parts[-2]}, {parts[-1]}"
    if org and ROLE.search(org) and not ROLE.search(title):
        title, org = org, title                          # "Company, Title" order
    return _item(kind, title=title[:120], org=org[:120], location=location[:80], start=start, end=end, current=current,
                 description="\n".join("• " + b for b in body)[:1500])


def _education(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        s = _BULLET.sub("", s).strip()
        m = LABELLED.match(s)
        if m and "course" in m.group(1).lower():
            if cur is not None:
                cur["extra"]["coursework"] = [c for c in (_clean(x) for x in re.split(r"[,;]", m.group(2))) if c][:20]
            continue
        start, end, current, rest = _dates(s)
        g = GPA.search(s)
        parts = _split_header(rest)
        if parts and SCHOOL.search(parts[0]) and not DEGREE.match(parts[0]):
            cur = _item("education")
            cur["org"] = parts[0][:120]
            others = [p for p in parts[1:] if not GPA.search(p)]
            deg = next((p for p in others if DEGREE.search(p)), "")
            if deg:
                cur["title"] = deg[:120]
            loc = [p for p in others if p != deg and not DEGREE.search(p) and not re.search(r"minor|expected|coursework", p, re.I)]
            if loc and re.fullmatch(r"[A-Z][A-Za-z .]+", loc[0]) and len(loc[0]) < 40:
                cur["location"] = ", ".join(loc[:2])[:80]
            out.append(cur)
        elif cur is None:
            cur = _item("education")
            out.append(cur)
        if DEGREE.search(rest) and not cur["title"]:
            cur["title"] = _clean(GPA.sub("", next((p for p in _split_header(rest) if DEGREE.search(p)), rest)))[:120]
        if cur["title"]:
            mm = (re.search(r"\b(?:in|of)\s+([A-Z][A-Za-z&/ ]{2,60}?)(?=,|\.|;|$| (?:minor|Minor|MINOR)| with| (?:expected|Expected)| (?:gpa|GPA))", cur["title"])
                  or re.search(r"^(?:b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?a\.?|a\.?a\.?|a\.?s\.?|mba)\s+([A-Z][A-Za-z&/ ]{2,60}?)(?=,|\.|;|$)", cur["title"], re.I))
            if mm and not cur["extra"].get("major") and not re.fullmatch(r"(?:science|arts)", mm.group(1).strip(), re.I):
                cur["extra"]["major"] = _clean(mm.group(1))
        mn = re.search(r"\b(?:minor|Minor|MINOR)(?:\s+in)?\s+([A-Z][A-Za-z&/ ]{2,40}?)(?=[.,;]|$)", s)
        if mn:
            cur["extra"]["minor"] = _clean(mn.group(1))
        if g:
            cur["extra"]["gpa"] = g.group(1) or g.group(2)
        if start and not (cur["start"] or cur["end"]):
            if end or current:
                cur["start"], cur["end"], cur["current"] = start, end, current
            else:
                cur["end"] = start                      # a single date on an education line is the graduation date
    return [e for e in out if e["org"] or e["title"]]


def to_profile(text: str) -> dict:
    """Resume text -> {"skills": [...], "items": [profile items]}."""
    p = parse(text)
    lines = p["lines"]
    heads = sorted((i, key) for key, i in p["sections"].items())
    items: list[dict] = []
    skills: list[str] = []
    languages: list[str] = []
    certs: list[str] = []
    for n, (start_line, key) in enumerate(heads):
        end_line = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = lines[start_line + 1:end_line]
        heading_text = lines[start_line].strip().lower()
        if key == "education":
            items += _education(body)
            continue
        if key in ("skills", "summary") or key == "awards" and "cert" not in heading_text and "licen" not in heading_text:
            for ln in body:
                s = _BULLET.sub("", ln.strip()).strip()
                m = LABELLED.match(s)
                if m:
                    label, vals = m.group(1).lower(), [v for v in (_clean(x) for x in LIST_SPLIT.split(m.group(2))) if v]
                    if label.startswith("language"):
                        languages += vals
                    elif label.startswith(("cert", "licen")):
                        certs += vals
                    elif "course" in label:
                        items += [_item("course", title=v[:120]) for v in vals]
                    else:
                        skills += vals
                elif key == "skills" and s:
                    skills += [v for v in (_clean(x) for x in LIST_SPLIT.split(s)) if v]
            continue
        if key == "awards":
            for ln in body:
                s = _BULLET.sub("", ln.strip()).strip()
                if not s:
                    continue
                st, en, cur, rest = _dates(s)
                parts = _split_header(rest)
                if parts:
                    items.append(_item("certification", title=parts[0][:120], org=(parts[1] if len(parts) > 1 else "")[:120], start=st or en))
            continue
        if key == "coursework":
            for ln in body:
                items += [_item("course", title=v[:120]) for v in (_clean(x) for x in LIST_SPLIT.split(_BULLET.sub("", ln))) if v]
            continue
        kind = SECTION_KIND.get(key)
        if not kind:
            continue
        if kind == "project" and heading_text.startswith("research"):
            kind = "experience"
        for head, bullets in _blocks(body):
            e = _entry(kind, head, bullets)
            if e and (e["title"] or e["description"]):
                items.append(e)
    items += [_item("certification", title=c[:120]) for c in certs]
    items += [_item("language", title=l[:60]) for l in languages if not re.search(r"python|java|sql|html|css|javascript|c\+\+|\br\b", l, re.I)]
    canon = []
    for s in skills + extract_skills(text):
        c = s if len(s) <= 40 else ""
        if c and c.lower() not in {x.lower() for x in canon}:
            canon.append(c)
    return {"skills": canon[:40], "items": items[:40]}
