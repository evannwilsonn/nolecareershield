"""
Resume tools that run without a model: read an uploaded resume, score it, suggest bullet
rewrites, compare it to a job, and write a .docx. The AI versions (resume_tools.py) build on
these; when no AI key is set, these are the whole answer.

Rules of the road:
  * Never invent experience. Rewrites only rephrase what the student wrote, and anything
    unknown becomes a visible placeholder like [number].
  * Uploaded files are untrusted: size-capped, page-capped, parsed without executing anything.
"""

from __future__ import annotations

import html
import io
import re
import zipfile

from matching import extract_skills, keyword_gap

MAX_UPLOAD = 2 * 1024 * 1024
MAX_TEXT = 20000


class ResumeError(ValueError):
    pass


# ---------- reading files ----------

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str) -> str:
    text = _CTRL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\t", "  "))
    text = re.sub(r"[  ]+\n", "\n", text)
    text = re.sub(r"^[  ]*[•▪●◦‣■□➢►–]\s*", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT]


def _pdf_text(data: bytes) -> str:
    if not data.startswith(b"%PDF"):
        raise ResumeError("That file isn't a PDF.")
    try:
        from pypdf import PdfReader
    except ImportError as e:                   # pragma: no cover - dependency is in requirements.txt
        raise ResumeError("PDF upload isn't available right now. Paste the text instead.") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ResumeError("That PDF is password-protected. Export it again without a password, or paste the text.")
        if len(reader.pages) > 6:
            raise ResumeError("That PDF is longer than 6 pages. A student resume should be one page.")
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except ResumeError:
        raise
    except Exception as e:                    # noqa: BLE001 - any parser failure is a user-facing "couldn't read"
        raise ResumeError("Couldn't read that PDF. Try exporting it again, or paste the text.") from e


def _docx_text(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ResumeError("That file isn't a Word document (.docx).") from e
    with zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > 25 * 1024 * 1024 or len(infos) > 400:
            raise ResumeError("That document is too large to read.")
        try:
            info = zf.getinfo("word/document.xml")
        except KeyError as e:
            raise ResumeError("That file isn't a Word document (.docx).") from e
        if info.file_size > 6 * 1024 * 1024:
            raise ResumeError("That document is too large to read.")
        xml = zf.read(info).decode("utf-8", "replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, flags=re.DOTALL):
        p = re.sub(r"<w:tab/>", "\t", p)
        p = re.sub(r"<w:br[^>]*/>", "\n", p)
        bullet = "• " if "<w:numPr>" in p else ""
        runs = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", p, flags=re.DOTALL)
        paras.append(bullet + html.unescape("".join(runs)))
    return "\n".join(paras)


def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD:
        raise ResumeError("That file is larger than 2 MB.")
    name = (filename or "").lower()
    if name.endswith(".pdf") or data.startswith(b"%PDF"):
        text = _pdf_text(data)
    elif name.endswith(".docx") or data.startswith(b"PK"):
        text = _docx_text(data)
    elif name.endswith((".txt", ".md")) or not name:
        text = data.decode("utf-8", "replace")
    else:
        raise ResumeError("Upload a PDF, a Word document (.docx), or a text file.")
    text = clean(text)
    if len(text) < 80:
        raise ResumeError("We couldn't find much text in that file. If it's a scanned image, paste the text instead.")
    return text


# ---------- reading the resume ----------

SECTION_NAMES = {
    "education": ["education", "academic background", "academics"],
    "experience": ["experience", "work experience", "professional experience", "employment", "work history",
                   "relevant experience", "internships", "internship experience"],
    "projects": ["projects", "academic projects", "personal projects", "selected projects", "research", "research experience"],
    "skills": ["skills", "technical skills", "skills & interests", "skills and interests", "core skills", "tools", "technologies"],
    "leadership": ["leadership", "leadership experience", "activities", "involvement", "campus involvement",
                   "extracurricular activities", "organizations", "volunteer", "volunteer experience", "service"],
    "awards": ["awards", "honors", "honors & awards", "honors and awards", "certifications", "certificates"],
    "summary": ["summary", "profile", "professional summary", "objective", "career objective"],
    "coursework": ["relevant coursework", "coursework"],
}
_HEADING_LOOKUP = {n: key for key, names in SECTION_NAMES.items() for n in names}

STRONG_VERBS = set("""
accelerated achieved administered advised advocated analyzed answered architected arranged assembled assessed audited
authored automated balanced boosted briefed budgeted built calculated campaigned captured catalogued chaired championed
clarified coached collaborated collected compiled completed composed computed conceived conducted configured consolidated
constructed consulted converted coordinated corrected counseled created cultivated curated cut debugged decreased defined
delivered demonstrated deployed designed detected determined developed devised diagnosed directed discovered documented
drafted drove edited educated eliminated enabled engineered enhanced established evaluated examined executed expanded
expedited facilitated filmed forecasted formulated founded gathered generated grew guided handled headed hired identified
illustrated implemented improved increased influenced informed initiated inspected installed instructed integrated interpreted
interviewed introduced invented investigated launched led lectured logged maintained managed mapped marketed maximized measured
mediated mentored merged migrated minimized modeled monitored motivated negotiated obtained operated optimized orchestrated organized
oversaw partnered performed persuaded photographed piloted pitched planned prepared presented prioritized processed produced
programmed promoted proposed prototyped provided published qualified quantified raised ran rebuilt recommended reconciled recorded
recruited redesigned reduced refined reorganized repaired reported represented researched resolved restructured revamped reviewed
revised saved scheduled screened secured served shaped simplified sold solved spearheaded standardized started streamlined
strengthened structured supervised supported surveyed synthesized taught tested tracked trained transformed translated tutored
unified updated upgraded validated verified volunteered won wrote
""".split())
WEAK_STARTS = [
    (r"^(?:was\s+)?responsible\s+for\s+", ""), (r"^duties\s+(?:included|include)\s*:?\s*", ""), (r"^tasked\s+with\s+", ""),
    (r"^in\s+charge\s+of\s+", "Led "), (r"^helped\s+(?:with\s+|to\s+)?", "Supported "), (r"^assisted\s+(?:with\s+|in\s+)?", "Supported "),
    (r"^worked\s+on\s+", "Developed "), (r"^worked\s+with\s+", "Collaborated with "), (r"^participated\s+in\s+", "Contributed to "),
    (r"^involved\s+in\s+", "Contributed to "), (r"^did\s+", "Completed "), (r"^handled\s+", "Managed "),
]
BUZZWORDS = ["hard-working", "hardworking", "team player", "go-getter", "detail-oriented", "detail oriented", "self-starter",
             "results-driven", "synergy", "think outside the box", "passionate", "dynamic individual", "motivated individual",
             "people person", "fast learner", "quick learner", "go getter", "rockstar", "ninja"]
IRREGULAR = {"writing": "Wrote", "leading": "Led", "making": "Made", "building": "Built", "teaching": "Taught",
             "running": "Ran", "selling": "Sold", "speaking": "Spoke", "taking": "Took", "giving": "Gave", "keeping": "Kept",
             "meeting": "Met", "finding": "Found", "bringing": "Brought", "holding": "Held", "setting": "Set",
             "putting": "Put", "cutting": "Cut", "getting": "Got", "driving": "Drove", "drawing": "Drew", "doing": "Completed",
             "having": "Had", "overseeing": "Oversaw", "shooting": "Shot", "winning": "Won", "paying": "Paid", "saying": "Said"}

_BULLET = re.compile(r"^\s*(?:[•▪●◦‣■\-\*–]|o\s)\s*")
_NUM = re.compile(r"\d|%|\$|\b(?:dozens?|hundreds?|thousands?|twice|double[ds]?|tripled?|half)\b", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(?:I|me|my|mine|we|our)\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_STREET = re.compile(r"\b\d{2,6}\s+[A-Za-z0-9.' ]{2,30}\s(?:st|street|ave|avenue|rd|road|blvd|drive|dr|lane|ln|way|ct|court|apt|circle|cir)\b\.?", re.IGNORECASE)
_DATE_TAIL = re.compile(r"(?:19|20)\d{2}|present|current", re.IGNORECASE)


def _heading(line: str) -> str | None:
    t = re.sub(r"[^a-z& ]", "", line.strip().lower()).strip()
    if 2 < len(t) <= 40 and t in _HEADING_LOOKUP:
        return _HEADING_LOOKUP[t]
    return None


def parse(text: str) -> dict:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    sections: dict[str, int] = {}
    current = "header"
    bullets = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        h = _heading(ln)
        if h:
            sections.setdefault(h, i)
            current = h
            continue
        if _BULLET.match(ln):
            bullets.append({"line": i, "text": _BULLET.sub("", ln).strip(), "section": current})
    if not bullets:
        # No bullet characters: treat sentence-like lines inside experience-type sections as bullets.
        current = "header"
        for i, ln in enumerate(lines):
            h = _heading(ln)
            if h:
                current = h
                continue
            words = ln.split()
            if current in ("experience", "projects", "leadership") and len(words) >= 6 and not _DATE_TAIL.search(ln[-14:]):
                bullets.append({"line": i, "text": ln.strip(), "section": current})
    return {"lines": lines, "sections": sections, "bullets": [b for b in bullets if b["text"]]}


def _first_word(text: str) -> str:
    m = re.match(r"[A-Za-z][A-Za-z'-]*", text.strip())
    return m.group(0).lower() if m else ""


def _gerund_to_past(word: str) -> str | None:
    """managing -> Managed, planning -> Planned, studying -> Studied, writing -> Wrote."""
    w = word.lower()
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w.endswith("ing") and len(w) > 5:
        stem = w[:-3]                       # creat(e)ing, plann-ing and develop-ing all just take "ed"
        past = stem[:-1] + "ied" if stem.endswith("y") and stem[-2:-1] not in "aeiou" else stem + "ed"
        return past[0].upper() + past[1:]
    return None


def bullet_issues(text: str) -> list[str]:
    issues = []
    first = _first_word(text)
    low = text.lower()
    if any(re.match(p, low) for p, _ in WEAK_STARTS):
        issues.append("Starts with a weak phrase. Lead with what you did.")
    elif first and first not in STRONG_VERBS and not first.endswith("ed"):
        issues.append("Start with a strong past-tense verb (Led, Built, Analyzed...).")
    if not _NUM.search(text):
        issues.append("No number. How many, how much, or how often?")
    n = len(text.split())
    if n > 34:
        issues.append(f"Long ({n} words). Aim for one line or two, under ~30 words.")
    elif n < 5:
        issues.append("Very short. Add what you did and what came of it.")
    if _PRONOUN.search(text):
        issues.append("Drop I/my/we; resumes are written without pronouns.")
    for b in BUZZWORDS:
        if b in low:
            issues.append(f"“{b}” is a claim. Show it with an example instead.")
            break
    return issues


def improve_bullet(text: str) -> dict:
    """A rule-based rewrite and tips. Never adds facts; unknowns become [placeholders]."""
    t = _BULLET.sub("", text or "").strip().rstrip(".")
    original = t
    t = re.sub(r"^(?:I|We)\s+", "", t)
    t = re.sub(r"^(?:was|were|am)\s+(?=(?:in\s+charge|responsible|tasked|involved)\b)", "", t, flags=re.IGNORECASE)
    low = t.lower()
    for pat, repl in WEAK_STARTS:
        m = re.match(pat, low)
        if m:
            rest = t[m.end():]
            nxt = _first_word(rest)
            # "In charge of planning X" -> "Planned X": ownership phrases take the verb that follows.
            if repl in ("", "Led ", "Managed ") and nxt and _gerund_to_past(nxt):
                t = rest
            elif repl == "Supported " and nxt.endswith("ing"):
                t = "Assisted in " + rest                     # "Supported making charts" isn't English
            else:
                t = (repl or "Managed ") + rest
            break
    first = _first_word(t)
    past = _gerund_to_past(first) if first else None
    if past:
        t = past + t[len(first):]
    t = re.sub(r"\b(?:my|our)\s+", "the ", t)
    t = t[:1].upper() + t[1:] if t else t
    tips = []
    if not _NUM.search(t):
        tips.append("Add a number: people served, dollars, hours saved, % change, or how often.")
        t = t + " [add a number: how many, how much, or how often]"
    if not re.search(r"\b(?:resulting|which|leading to|so that|to (?:increase|reduce|improve|help|support|save))\b", t, re.IGNORECASE):
        tips.append("Say what changed because of your work (the result).")
    for b in BUZZWORDS:
        if b in t.lower():
            tips.append(f"Cut “{b}” and show it with a detail.")
    return {"original": original, "rewrite": t, "tips": tips[:3]}


def review(text: str) -> dict:
    text = text or ""
    p = parse(text)
    bullets = p["bullets"]
    secs = p["sections"]
    words = len(re.findall(r"\b\w+\b", text))
    findings: list[dict] = []

    def note(sev, msg):
        findings.append({"severity": sev, "message": msg})

    # 1. Impact
    nb = len(bullets)
    quant = sum(1 for b in bullets if _NUM.search(b["text"]))
    q_ratio = quant / nb if nb else 0
    impact = round(25 * min(1.0, q_ratio / 0.5)) if nb else 5
    if nb and q_ratio < 0.4:
        note("warn", f"Only {quant} of {nb} bullets have a number. Aim for at least half.")
    # 2. Action verbs
    strong = sum(1 for b in bullets if not any(i.startswith(("Starts with a weak", "Start with a strong")) for i in bullet_issues(b["text"])))
    v_ratio = strong / nb if nb else 0
    verbs = round(20 * v_ratio) if nb else 4
    starts = [_first_word(b["text"]) for b in bullets]
    repeated = sorted({w for w in starts if w and starts.count(w) >= 3})
    if nb and v_ratio < 0.7:
        note("warn", f"{nb - strong} bullet{'s don' if nb - strong != 1 else ' doesn'}'t start with a strong verb.")
    if repeated:
        note("info", "You start several bullets with the same verb (" + ", ".join(w.title() for w in repeated) + "). Vary them.")
    # 3. Structure
    structure = 0
    emails = _EMAIL.findall(text)
    if emails:
        structure += 2
    else:
        note("bad", "No email address. Put one at the top.")
    if _PHONE.search(text):
        structure += 1
    else:
        note("info", "No phone number. Many employers still call.")
    if re.search(r"linkedin\.com/in/", text, re.IGNORECASE):
        structure += 1
    else:
        note("info", "Add your LinkedIn URL (linkedin.com/in/...).")
    if "education" in secs:
        structure += 6
        edu_block = "\n".join(p["lines"][secs["education"]:secs["education"] + 8]).lower()
        if not re.search(r"(?:19|20)\d{2}", edu_block):
            note("warn", "Add your graduation month and year (e.g. Expected May 2027).")
    else:
        note("bad", "No Education section. For students it usually goes near the top.")
    if "experience" in secs or "projects" in secs or "leadership" in secs:
        structure += 6
    else:
        note("bad", "No Experience, Projects or Leadership section found.")
    if "skills" in secs:
        structure += 4
    else:
        note("warn", "Add a Skills section so screeners and ATS software find your tools.")
    # 4. Length & readability
    length = 0
    if 250 <= words <= 750:
        length += 8
    elif words < 250:
        length += 4
        note("warn", f"Short ({words} words). Add projects, coursework or campus involvement.")
    else:
        length += 3 if words <= 950 else 1
        note("warn", f"Long ({words} words). As a student, fit it on one page.")
    ok_len = sum(1 for b in bullets if 5 <= len(b["text"].split()) <= 34)
    length += round(7 * (ok_len / nb)) if nb else 2
    if nb < 4:
        note("warn", "Fewer than 4 bullet points. Describe each role with 2 to 4 bullets.")
    # 5. Clarity
    clarity = 10
    pron = [b for b in bullets if _PRONOUN.search(b["text"])]
    if pron:
        clarity -= 4
        note("info", f"{len(pron)} bullet{'s use' if len(pron) != 1 else ' uses'} I/my/we. Drop the pronouns.")
    buzz = sorted({b for b in BUZZWORDS if b in text.lower()})
    if buzz:
        clarity -= 3
        note("info", "Buzzwords to replace with evidence: " + ", ".join(buzz[:4]) + ".")
    if repeated:
        clarity -= 3
    # 6. Safety & privacy (a scam-safety angle: this document gets sent to strangers)
    safety = 10
    if _SSN.search(text):
        safety = 0
        note("bad", "Remove what looks like a Social Security number. No resume should include one.")
    if re.search(r"\b(?:date of birth|d\.o\.b|dob|birthdate|marital status|age\s*:)\b", text, re.IGNORECASE):
        safety -= 6
        note("bad", "Remove date of birth, age or marital status. Employers don't need them, and scammers do.")
    if _STREET.search(text):
        safety -= 2
        note("info", "Consider listing just your city and state instead of a street address.")
    safety = max(0, safety)

    cats = [
        {"key": "impact", "name": "Impact (numbers)", "score": impact, "max": 25},
        {"key": "verbs", "name": "Action verbs", "score": verbs, "max": 20},
        {"key": "structure", "name": "Sections & contact", "score": structure, "max": 20},
        {"key": "length", "name": "Length & readability", "score": length, "max": 15},
        {"key": "clarity", "name": "Clarity", "score": max(0, clarity), "max": 10},
        {"key": "safety", "name": "Privacy & safety", "score": safety, "max": 10},
    ]
    total = sum(c["score"] for c in cats)
    grade = "Strong" if total >= 85 else "Solid" if total >= 70 else "Needs work" if total >= 55 else "Early draft"
    items = []
    for b in bullets:
        iss = bullet_issues(b["text"])
        if iss:
            items.append({"text": b["text"], "issues": iss, **{k: v for k, v in improve_bullet(b["text"]).items() if k != "original"}})
    order = {"bad": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"score": total, "grade": grade, "categories": cats, "findings": findings, "bullets": items[:12],
            "stats": {"words": words, "bullets": nb, "quantified": quant, "sections": sorted(secs)},
            "skills": extract_skills(text)}


# ---------- tailoring ----------

_GENERIC = set("""about above across after also among an and any are as at be been being below between both but by can candidate
candidates company could day days do duties each ensure etc experience for from full has have help hours if in including into is it
its job join looking may more most must new not of on one or other our part per plus preferred position provide related required
requirements responsibilities role skills strong such team than that the their them there these they this through time to under
up us using we well what when where which who will with within work working years you your able ability students student
opportunity apply applicants including knowledge excellent good great including various other""".split())


def _keywords(text: str, n: int = 14) -> list[str]:
    words = re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in _GENERIC:
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, c in ranked if c >= 2][:n]


def tailor(resume_text: str, job_title: str, job_text: str, profile: dict | None = None) -> dict:
    gap = keyword_gap(resume_text, job_title + "\n" + job_text)
    kws = _keywords(job_title + " " + job_text)
    low_resume = (resume_text or "").lower()
    kw_present = [k for k in kws if k in low_resume]
    kw_missing = [k for k in kws if k not in low_resume]
    kw_pct = round(100 * len(kw_present) / len(kws)) if kws else 0
    match = round(0.65 * gap["match_pct"] + 0.35 * kw_pct) if gap["job_skills"] else kw_pct

    job_terms = set(kws) | {s.lower() for s in gap["job_skills"]}
    scored = []
    for b in parse(resume_text)["bullets"]:
        low = b["text"].lower()
        hits = [t for t in job_terms if t in low]
        if hits:
            scored.append((len(hits), b["text"], hits))
    scored.sort(key=lambda x: -x[0])
    lead = [{"text": t, "why": "Mentions " + ", ".join(sorted(h)[:3])} for _, t, h in scored[:4]]

    prof = profile or {}
    who = f"{prof.get('major')} student" if prof.get("major") else "Student"
    when = f" graduating {prof.get('grad_term')}" if prof.get("grad_term") else ""
    strengths = gap["present"][:3] or [k for k in kw_present[:2]]
    summary = (f"{who} at Florida State University{when} with hands-on experience in "
               f"{', '.join(strengths) if strengths else '[your two strongest skills]'}, "
               f"looking to bring that to the {job_title or 'role'} position.")
    gaps = [{"skill": s, "advice": f"Only add {s} if you've really used it, even in a class or club. If not, mention a related skill you do have."}
            for s in gap["missing"][:6]]
    return {"match": match, "skills_present": gap["present"], "skills_missing": gap["missing"],
            "keywords_present": kw_present, "keywords_missing": kw_missing[:10], "lead_bullets": lead,
            "summary": summary, "gaps": gaps}


# ---------- .docx export ----------

def _x(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_docx(text: str) -> bytes:
    """A clean one-column Word document from the resume text (name, headings, bullets)."""
    paras = []
    first = True
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            paras.append('<w:p/>')
            continue
        run_props = ""
        ppr = ""
        if first:
            run_props = '<w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
            ppr = '<w:pPr><w:jc w:val="center"/></w:pPr>'
            first = False
        elif _heading(s):
            run_props = '<w:rPr><w:b/><w:caps/><w:sz w:val="22"/></w:rPr>'
            ppr = ('<w:pPr><w:spacing w:before="200" w:after="60"/><w:pBdr><w:bottom w:val="single" w:sz="4" '
                   'w:space="1" w:color="999999"/></w:pBdr></w:pPr>')
        elif _BULLET.match(s):
            s = "•\t" + _BULLET.sub("", s)
            ppr = '<w:pPr><w:ind w:left="360" w:hanging="220"/><w:spacing w:after="20"/></w:pPr>'
        paras.append(f'<w:p>{ppr}<w:r>{run_props}<w:t xml:space="preserve">{_x(s)}</w:t></w:r></w:p>')
    body = "".join(paras)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                f'{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="720" w:right="864" w:bottom="720" w:left="864" w:header="0" w:footer="0" w:gutter="0"/>'
                '</w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault>'
              '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="21"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="40" w:line="252" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
              '</w:docDefaults></w:styles>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return buf.getvalue()
