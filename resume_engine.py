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
import math
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
    for p in _between(xml, _P_TAG, self_closing=True):
        bullet = "• " if "<w:numPr>" in p else ""
        runs = _between(p, _T_TAG)
        paras.append(bullet + html.unescape("".join(runs)))
    return "\n".join(paras)


# Opening/closing tags for paragraphs and text runs. Attribute runs are bounded ({0,2000}) and pairing is done in one
# pass, so a hostile document (thousands of unclosed tags) costs linear time. A non-greedy ".*?</w:p>" search, by
# contrast, rescans to the end of the file from every unclosed tag: quadratic, minutes of CPU from a few KB.
_P_TAG = re.compile(r"<w:p(?:\s[^>]{0,2000})?>|<w:p/>|</w:p>")
_T_TAG = re.compile(r"<w:t(?:\s[^>]{0,2000})?>|</w:t>")


def _between(text: str, tags: re.Pattern, self_closing: bool = False) -> list[str]:
    """Contents of each <tag>...</tag> pair, in order (and "" for each <tag/> when self_closing)."""
    out, start = [], None
    for m in tags.finditer(text):
        tok = m.group(0)
        if tok.startswith("</"):
            if start is not None:
                out.append(text[start:m.start()])
                start = None
        elif tok.endswith("/>"):
            if self_closing:
                out.append("")
            start = None
        else:
            start = m.end()
    return out


def extract_text_safely(filename: str, data: bytes) -> str:
    """extract_text() in a separate process with a time limit, for uploads from users (see sandbox.py)."""
    import sandbox
    if len(data) > MAX_UPLOAD:
        raise ResumeError("That file is larger than 2 MB.")
    try:
        return sandbox.run(extract_text, filename, data)
    except sandbox.ParseBusy as e:
        raise ResumeError("We're reading a lot of files right now. Try again in a minute, or paste the text.") from e
    except sandbox.ParseTimeout as e:
        raise ResumeError("That file took too long to read. Try exporting it again, or paste the text.") from e
    except ResumeError:
        raise
    except Exception as e:                    # noqa: BLE001 - the parser process failing is a user-facing "couldn't read"
        raise ResumeError("Couldn't read that file. Try exporting it again, or paste the text.") from e


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


def versioned(resume: str, summary: str) -> str:
    """A copy of the resume with a SUMMARY section added above the first heading."""
    lines = (resume or "").splitlines()
    at = next((i for i, ln in enumerate(lines) if _heading(ln)), min(3, len(lines)))
    return "\n".join(lines[:at] + ["SUMMARY", summary, ""] + lines[at:])


# ---------- optimizer report (ATS readiness) ----------

REPORT_SECTIONS = [("formatting", "Formatting", 35), ("keywords", "Keywords", 20),
                   ("impact", "Impact & bullets", 45), ("contact", "Contact & structure", 20)]
_FIND_SECTION = [(r"^Only \d+ of|strong verb|same verb", "impact"),
                 (r"^No email|^No phone|LinkedIn|Education|graduation|Experience, Projects", "contact"),
                 (r"Skills section", "keywords")]


def _finding_section(msg: str) -> str:
    for pat, key in _FIND_SECTION:
        if re.search(pat, msg):
            return key
    return "formatting"


def _has_word(low: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", low) is not None


def missing_profile_skills(text: str, skills: list | None) -> list[str]:
    """Skills the student listed on their profile that the resume text doesn't mention (safe to add: they're theirs)."""
    low = (text or "").lower()
    out: list[str] = []
    for s in skills or []:
        s = str(s).strip()
        if s and len(s) <= 40 and not _has_word(low, s) and s.lower() not in [o.lower() for o in out]:
            out.append(s)
    return out[:12]


def add_skills(text: str, skills: list) -> str:
    """Append skills to the Skills line (or add a Skills section). Skills already on the resume are skipped."""
    skills = missing_profile_skills(text, skills)
    if not skills:
        return text
    lines = (text or "").splitlines()
    at = parse(text)["sections"].get("skills")
    if at is None:
        return (text or "").rstrip("\n") + "\n\nSKILLS\n" + ", ".join(skills) + "\n"
    j = at + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or _heading(lines[j]):
        lines.insert(at + 1, ", ".join(skills))
    else:
        lines[j] = lines[j].rstrip().rstrip(",;") + ", " + ", ".join(skills)
    return "\n".join(lines)


def set_summary(text: str, summary: str) -> str:
    """Put a summary at the top: fill an existing SUMMARY section, or add one above the first heading."""
    summary = re.sub(r"\s+", " ", summary or "").strip()
    lines = (text or "").splitlines()
    at = parse(text)["sections"].get("summary")
    if at is None:
        return versioned(text, summary)
    j = at + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or _heading(lines[j]):
        lines.insert(at + 1, summary)
    else:
        lines[j] = summary
    return "\n".join(lines)


def report(text: str, profile_skills: list | None = None) -> dict:
    """The optimizer's answer: ATS readiness 0-100 in four sections, and every suggestion as a card that
    can be accepted or dismissed. Nothing here changes the resume."""
    rv = review(text)
    cat = {c["key"]: c["score"] for c in rv["categories"]}
    secs = set(rv["stats"]["sections"])
    skills = rv["skills"]
    scores = {"formatting": cat["length"] + cat["clarity"] + cat["safety"],
              "keywords": min(20, 3 * len(skills) + (5 if "skills" in secs else 0)),
              "impact": cat["impact"] + cat["verbs"], "contact": cat["structure"]}
    sections = []
    for key, name, mx in REPORT_SECTIONS:
        pct = round(100 * scores[key] / mx)
        sections.append({"key": key, "name": name, "score": scores[key], "max": mx, "percent": pct,
                         "tone": "ok" if pct >= 80 else "warn" if pct < 50 else ""})
    percent = round(100 * sum(scores.values()) / sum(m for _, _, m in REPORT_SECTIONS))
    label = "ATS-ready" if percent >= 80 else "Almost ready" if percent >= 60 else "Needs work"
    sugg: list[dict] = []
    miss = missing_profile_skills(text, profile_skills)
    if miss:
        sugg.append({"section": "keywords", "kind": "skills", "severity": "warn", "title": "Add skills you already list on your profile",
                     "detail": "These are on your profile but not on this resume: " + ", ".join(miss) + ". Screeners search resumes for them.",
                     "old": "", "new": ", ".join(miss)})
    for f in rv["findings"]:
        if miss and f["message"].startswith("Add a Skills section"):
            continue
        sugg.append({"section": _finding_section(f["message"]), "kind": "tip", "severity": f["severity"], "title": f["message"],
                     "detail": "", "old": "", "new": ""})
    for b in rv["bullets"]:
        sugg.append({"section": "impact", "kind": "rewrite", "severity": "warn", "title": "Strengthen this bullet",
                     "detail": " ".join(b["issues"][:2]), "old": b["text"], "new": b["rewrite"]})
    order = {key: i for i, (key, _, _) in enumerate(REPORT_SECTIONS)}
    sev = {"bad": 0, "warn": 1, "info": 2}
    sugg.sort(key=lambda x: (order[x["section"]], sev[x["severity"]]))
    for i, x in enumerate(sugg):
        x["id"] = f"s{i}"
    return {"percent": percent, "label": label, "sections": sections, "suggestions": sugg, "stats": rv["stats"], "skills": skills}


def stand_out(text: str) -> list[dict]:
    """A few 'help me stand out' tips drawn from what the resume already says."""
    p = parse(text)
    tips = []
    if "summary" not in p["sections"]:
        tips.append({"title": "Open with a short summary",
                     "detail": "Two lines on who you are and what you want. Tailor to a job writes one for a specific role."})
    good = next((b["text"] for b in p["bullets"] if _NUM.search(b["text"]) and not bullet_issues(b["text"])), "")
    if good:
        tips.append({"title": "Lead with your strongest result", "detail": f"\u201c{good[:140]}\u201d shows a result. Put it first under its role."})
    sk = extract_skills(text)[:5]
    if sk:
        tips.append({"title": "Name your tools", "detail": "Screeners search for skills like " + ", ".join(sk) + ". Keep them in a Skills section and in bullets where true."})
    if not ({"leadership", "organizations", "activities"} & set(p["sections"])):
        tips.append({"title": "Show campus involvement", "detail": "Clubs, teams and volunteering show initiative, especially with limited work history."})
    return tips[:4]


# ---------- .docx export ----------

def _x(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_docx(text) -> bytes:
    """A clean one-column Word document: from a built resume (build_resume's dict) or from plain resume text."""
    if isinstance(text, dict):
        return doc_docx(text)
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
    return _docx_pack("".join(paras))


def _docx_pack(body: str) -> bytes:
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


# ---------- the new resume: build it, then write it as HTML, text, .docx and .pdf ----------
#
# build_resume() turns the student's own resume text (plus their profile) into a clean, structured
# resume. For a job it also picks and orders what to show. Every change is listed with an id so the
# student can undo it, and the same ids drive the downloads (?undo=c2,c5). It only rephrases,
# reorders and selects: numbers, employers, dates and skills all come from the student.
# demo/engine.js has a line-for-line port (buildResume, toPdf) checked by tests/test_tailored_resume.py.

DOC_ORDER = ["summary", "education", "experience", "projects", "skills", "awards", "leadership", "coursework"]
DOC_TITLES = {"summary": "Summary", "education": "Education", "experience": "Experience", "projects": "Projects", "skills": "Skills",
              "awards": "Certifications", "leadership": "Activities", "coursework": "Relevant Coursework"}
BULLET_KEYS = ("experience", "projects", "leadership")
PLACEHOLDER_TAIL = " [add a number: how many, how much, or how often]"
_SCHOOL = re.compile(r"\b(?:university|college|institute|school|academy)\b", re.IGNORECASE)
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+|(?:spring|summer|fall|winter)\s+"
_DSTART = rf"(?:expected\s+)?(?:{_MON})?(?:19|20)\d{{2}}"
_DOC_DATE = re.compile(rf"(?:^|[\s,|(·—–-])({_DSTART}(?:\s*(?:-|–|—|to)\s*(?:{_DSTART}|present|current|now))?)[\s)|,.]*$", re.IGNORECASE)
_DATE_ONLY = re.compile(rf"^{_DSTART}(?:\s*(?:-|–|—|to)\s*(?:{_DSTART}|present|current|now))?$", re.IGNORECASE)
_SEG = re.compile(r"\s+[|·]\s+")
_SPLIT_CONTACT = re.compile(r"\s*[|·•]\s*|\s{3,}")
_EDGE = " ,|·—–-"
PROFILE_ITEM_KEYS = {"experience": "experience", "project": "projects", "organization": "leadership", "certification": "awards"}


def _nrm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _edge_strip(s: str) -> str:
    a, b = 0, len(s)
    while a < b and s[a] in _EDGE:
        a += 1
    while b > a and s[b - 1] in _EDGE:
        b -= 1
    return s[a:b]


def _tc(s: str) -> str:
    """Title-case an ALL-CAPS heading (SKILLS & INTERESTS -> Skills & Interests); leave others alone."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split()) if s == s.upper() else s


def _and(xs: list) -> str:
    xs = [str(x) for x in xs]
    if not xs:
        return ""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _entry(line: str) -> dict:
    m = _DOC_DATE.search(line)
    if m and m.group(1).strip() != line.strip():
        return {"head": _edge_strip(line[:m.start(1)].strip()), "date": m.group(1).strip(), "line": line, "sub": [], "bullets": []}
    parts = _SEG.split(line)                        # "Role — Org | Aug 2026 – Present | Remote": the date is one of the parts
    for i, p in enumerate(parts):
        if i and _DATE_ONLY.match(p.strip()):
            return {"head": " | ".join(parts[:i] + parts[i + 1:]), "date": p.strip(), "line": line, "sub": [], "bullets": []}
    return {"head": line, "date": "", "line": line, "sub": [], "bullets": []}


def _doc_parse(text: str) -> dict:
    lines = (text or "").splitlines()
    any_bullet = any(_BULLET.match(ln) for ln in lines if ln.strip())
    header: list[str] = []
    sections: list[dict] = []
    cur = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        h = _heading(s)
        if h:
            cur = {"key": h, "title": _tc(re.sub(r"[:\s]+$", "", s)), "text": "", "lines": [], "entries": []}
            sections.append(cur)
            continue
        if cur is None:
            header.append(s)
        else:
            cur["lines"].append(s)
    n = 0
    for sec in sections:
        raw, sec["lines"] = sec["lines"], []
        if sec["key"] == "summary":
            sec["text"] = " ".join(_BULLET.sub("", s).strip() for s in raw).strip()
            continue
        if sec["key"] == "skills":
            sec["lines"] = [t for t in (_BULLET.sub("", s).strip() for s in raw) if t]
            continue
        e = None
        for s in raw:
            if any_bullet:
                is_b = bool(_BULLET.match(s))
            else:
                is_b = sec["key"] in BULLET_KEYS and len(s.split()) >= 6 and not _DATE_TAIL.search(s[-14:])
            if is_b:
                t = _BULLET.sub("", s).strip() if any_bullet else s
                if not t:
                    continue
                if e is None:
                    e = _entry("")
                    sec["entries"].append(e)
                n += 1
                e["bullets"].append({"id": f"b{n}", "text": t, "change": ""})
            elif e is None or e["bullets"] or sec["key"] in ("awards", "coursework") or \
                    (sec["key"] == "education" and _SCHOOL.search(s) and e["head"]):
                e = _entry(s)
                sec["entries"].append(e)
            else:
                e["sub"].append(s)
    name = ""
    contact_lines = header
    if header and "@" not in header[0] and not re.search(r"\d", header[0]) and len(header[0].split()) <= 6 and len(header[0]) <= 60:
        name, contact_lines = header[0], header[1:]
    contact: list[str] = []
    for ln in contact_lines:
        for part in _SPLIT_CONTACT.split(ln):
            part = part.strip()
            if part and part not in contact:
                contact.append(part)
    return {"name": name, "contact": contact, "sections": sections}


def _linknorm(s: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", (s or "").strip().lower()).rstrip("/")


def _relevance(text: str, jskills: list, kws: list) -> tuple[int, list]:
    low = text.lower()
    has = [x.lower() for x in extract_skills(text)]
    hits = [s for s in jskills if s.lower() in has or _has_word(low, s)]
    hl = [h.lower() for h in hits]
    more = [k for k in kws if k not in hl and _has_word(low, k)]
    return 2 * len(hits) + len(more), hits + more


def _summary_text(profile: dict, doc: dict, have: list, jl: list | None, job: dict | None) -> str:
    major = str(profile.get("major") or "").strip()
    grad = str(profile.get("grad_term") or "").strip()
    s = (major + " student" if major else "Student") + " at Florida State University" + (" graduating " + grad if grad else "")
    pick = [h for h in have if h.lower() in jl] if jl is not None else []
    if not pick:
        pick = have[:3]
    if pick:
        s += " with hands-on experience in " + _and(pick[:3])
    s += "."
    exp = next((sec for sec in doc["sections"] if sec["key"] == "experience" and sec["entries"]), None)
    head = _SEG.split(next((e["head"] for e in (exp["entries"] if exp else []) if e["head"]), ""))[0].strip()
    if head and len(head) <= 90:
        s += " Experience includes " + head.rstrip(".") + "."
    cat = str((job or {}).get("category") or "").strip()
    if job and cat and cat.lower() != "other":
        s += " Interested in " + cat.lower() + " work."
    return s


def _profile_entry(it: dict) -> dict:
    title, org = str(it.get("title") or "").strip(), str(it.get("org") or "").strip()
    head = title + (", " + org if org and title else "") if title else org
    start = str(it.get("start") or "").strip()
    end = "Present" if it.get("current") else str(it.get("end") or "").strip()
    date = start + " – " + end if start and end else (start or end)
    bl = [t for t in (_BULLET.sub("", x).strip() for x in re.split(r"\n+", str(it.get("description") or ""))) if t][:3]
    return {"head": head, "date": date, "line": head + (", " + date if date else ""), "sub": [],
            "bullets": [{"id": "", "text": t, "change": ""} for t in bl]}


def build_resume(profile: dict | None, base_text: str, job: dict | None = None, accepted=None, *, undo=None,
                 ai_edits: dict | None = None, today: tuple[int, int] | None = None) -> dict:
    """A complete resume document from the student's resume text and profile, optionally aimed at one job.

    Returns {name, contact, sections, changes, gaps, match, job, text}. `accepted` (ids to apply; None = all) and
    `undo` (ids to leave out) choose which changes are applied; every change is always listed, with `on`."""
    import copy as _copy
    profile = profile or {}
    text = base_text or ""
    undo = set(undo or [])

    def on(cid: str) -> bool:
        return (accepted is None or cid in accepted) and cid not in undo

    parsed = _doc_parse(text)
    doc = _copy.deepcopy(parsed)
    changes: list[dict] = []

    def change(kind, title, detail="", before="", after="") -> str:
        cid = f"c{len(changes) + 1}"
        changes.append({"id": cid, "kind": kind, "title": title, "detail": detail, "before": before, "after": after, "on": on(cid)})
        return cid

    def section(key: str, make: bool = False) -> dict | None:
        sec = next((s for s in doc["sections"] if s["key"] == key), None)
        if sec is None and make:
            sec = {"key": key, "title": DOC_TITLES[key], "text": "", "lines": [], "entries": []}
            doc["sections"].append(sec)
        return sec

    # Header: the resume's own name and contact line, plus the profile's email and links if it doesn't show them.
    if not doc["name"]:
        doc["name"] = str(profile.get("display_name") or "").strip() or "Your Name"
    have_links = " ".join(_linknorm(c) for c in doc["contact"])
    email = str(profile.get("email") or "").strip()
    if email and not _EMAIL.search(text):
        doc["contact"].append(email)
    links = profile.get("links") or {}
    for k in ("linkedin", "website"):
        v = str(links.get(k) or "").strip()
        if v and _linknorm(v) not in have_links and not (k == "linkedin" and "linkedin.com" in have_links):
            doc["contact"].append(re.sub(r"^(?:https?://)?(?:www\.)?", "", v).rstrip("/"))

    jl = None
    jskills: list = []
    kws: list = []
    if job:
        jskills, kws = _job_terms(job)
        jl = [s.lower() for s in jskills]
    skills_profile = [str(s).strip() for s in (profile.get("skills") or []) if str(s).strip()]
    have: list = []
    listed = " ".join(ln for sec in parsed["sections"] if sec["key"] == "skills" for ln in sec["lines"])
    for s in extract_skills(listed) + extract_skills(text) + skills_profile:
        if s.lower() not in [h.lower() for h in have]:
            have.append(s)

    # 1. Summary: written from the student's major, graduation term, skills and first role.
    old_sum = (section("summary") or {}).get("text", "")
    gen = (ai_edits or {}).get("summary") or _summary_text(profile, parsed, have, jl, job)
    if (job and _nrm(gen) != _nrm(old_sum)) or (not job and not old_sum):
        cid = change("summary", ("Rewrote your summary for this job" if old_sum else "Added a summary for this job") if job else "Added a short summary",
                     "Built from your major, graduation term, skills" + (" this job lists" if job else "") + " and experience. Nothing new is claimed.",
                     old_sum, gen)
        if on(cid):
            section("summary", True)["text"] = gen

    # 2. Profile entries the resume doesn't have yet (they're the student's own).
    text_n = _nrm(text)
    added = 0
    for it in profile.get("items") or []:
        key = PROFILE_ITEM_KEYS.get(it.get("kind") or "")
        title = str(it.get("title") or "").strip()
        if not key or not title or _nrm(title) in text_n or added >= 4:
            continue
        added += 1
        e = _profile_entry(it)
        label = {"awards": "certification", "projects": "project", "leadership": "activity"}.get(key, "experience")
        cid = change("profile", f"Added your {label} “{title}” from your profile", "It's on your profile but wasn't on this resume.", "", e["line"])
        if on(cid):
            section(key, True)["entries"].append(e)

    # 3. Order bullets: most relevant to the job first (with no job, the strongest result first).
    score_of: dict = {}
    for sec in doc["sections"]:
        if sec["key"] not in BULLET_KEYS:
            continue
        for e in sec["entries"]:
            sc = []
            for b in e["bullets"]:
                if job:
                    r, hits = _relevance(b["text"], jskills, kws)
                else:
                    r, hits = (1 if _NUM.search(b["text"]) and not bullet_issues(b["text"]) else 0), []
                if b["id"]:
                    score_of[b["id"]] = r
                sc.append((r, hits))
            if len(e["bullets"]) < 2:
                continue
            order = sorted(range(len(e["bullets"])), key=lambda i: (-sc[i][0], i))
            if order != list(range(len(order))) and sc[order[0]][0] > sc[0][0]:
                where = e["head"] or DOC_TITLES.get(sec["key"], "")
                detail = (f"It mentions {_and(sc[order[0]][1][:3])}, which this job asks for." if job
                          else "It shows a result with a number, so it should come first.")
                cid = change("order", ("Led " + where[:60] + " with its most relevant bullet") if job else ("Led " + where[:60] + " with its strongest result"),
                             detail, e["bullets"][0]["text"], e["bullets"][order[0]]["text"])
                if on(cid):
                    e["bullets"] = [e["bullets"][i] for i in order]

    # 4. For a job, leave out bullets that don't relate to it when one role has more than four.
    dropped: set = set()
    if job:
        for sec in doc["sections"]:
            if sec["key"] not in BULLET_KEYS:
                continue
            for e in sec["entries"]:
                if len(e["bullets"]) <= 4:
                    continue
                ranked = sorted(e["bullets"], key=lambda b: -score_of.get(b["id"], 0))
                gone = [b for b in ranked[4:] if b["id"] and score_of.get(b["id"], 0) == 0]
                if gone:
                    where = e["head"] or DOC_TITLES.get(sec["key"], "")
                    cid = change("trim", f"Left out {len(gone)} bullet{'s' if len(gone) != 1 else ''} under {where[:60]} that don't relate to this job",
                                 "Keeps the page on what this employer asks for. They stay on your main resume.",
                                 " / ".join(b["text"] for b in gone), "")
                    ids = {b["id"] for b in gone}
                    dropped |= ids
                    if on(cid):
                        e["bullets"] = [b for b in e["bullets"] if b["id"] not in ids]

    # 5. Reword weak bullets: same facts; anything unknown is left for the student to add.
    ai_b = (ai_edits or {}).get("bullets") or {}
    n_rw = 0
    for b in [b for sec in parsed["sections"] for e in sec["entries"] for b in e["bullets"]]:
        if b["id"] in dropped or n_rw >= 10:
            continue
        t = b["text"]
        if t in ai_b:
            new, why, title = ai_b[t].get("text", ""), ai_b[t].get("why") or "Reworded to match the posting.", "Reworded a bullet to match the posting"
        else:
            iss = bullet_issues(t)
            if not iss:
                continue
            new = improve_bullet(t)["rewrite"].replace(PLACEHOLDER_TAIL, "")
            why = iss[0] + (" If you have a number for it, add it." if not _NUM.search(t) and not iss[0].startswith("No number") else "")
            title = "Reworded a bullet to lead with what you did"
        if not new or _nrm(new) == _nrm(t):
            continue
        n_rw += 1
        cid = change("rewrite", title, why, t, new)
        if on(cid):
            for sec in doc["sections"]:
                for e in sec["entries"]:
                    for x in e["bullets"]:
                        if x["id"] == b["id"]:
                            x["text"], x["change"] = new, cid

    # 6. Skills from the profile that the resume doesn't list (for a job: only the ones the job asks for).
    cand = [s for s in skills_profile if s.lower() in jl] if jl is not None else skills_profile
    miss = missing_profile_skills(text, cand)
    if miss:
        many = len(miss) > 1
        cid = change("skills", "Added " + _and(miss[:4]) + (f" and {len(miss) - 4} more" if len(miss) > 4 else "") + " to Skills",
                     ("This job lists " + ("them" if many else "it") + ", and " + ("they're" if many else "it's") + " on your profile.") if job
                     else (("They're" if many else "It's") + " on your profile but " + ("weren't" if many else "wasn't") + " on your resume."),
                     "", ", ".join(miss))
        if on(cid):
            sec = section("skills", True)
            i = next((k for k, ln in enumerate(sec["lines"]) if ":" not in ln), -1)
            if i >= 0:
                sec["lines"][i] = sec["lines"][i].rstrip().rstrip(",;") + ", " + ", ".join(miss)
            else:
                sec["lines"].append(("Additional: " if sec["lines"] else "") + ", ".join(miss))

    doc["sections"] = [s for s in sorted(doc["sections"], key=lambda s: DOC_ORDER.index(s["key"])) if s["text"] or s["lines"] or s["entries"]]
    out = {"name": doc["name"], "contact": doc["contact"], "sections": doc["sections"], "changes": changes, "gaps": [], "match": None,
           "job": {"id": job.get("id"), "title": job.get("title") or "", "company": job.get("company") or ""} if job else None}
    out["text"] = doc_text(out)
    if job:
        import fit as _fit
        lean = lambda t: dict(profile, skills=[], items=[], headline="", bio="", resume_text=t)      # noqa: E731
        f0 = _fit.fit_score(job, lean(text), today)
        f1 = _fit.fit_score(job, lean(out["text"]), today)
        out["match"] = {"before": f0["percent"], "after": f1["percent"], "met_before": f0["met"], "met_after": f1["met"], "total": f1["total"]}
        out["gaps"] = [{"text": c["text"], "must": bool(c.get("must")), "advice": _gap_advice(c["text"], c["status"])}
                       for c in f1["checklist"] if c["status"] != "met"][:8]
    return out


def fact_safe(new: str, orig: str, allowed=()) -> bool:
    """True when `new` claims nothing `orig` doesn't: no new numbers, skills, names, links or emails.
    Used to check wording from the AI before it can reach a resume."""
    new, orig = str(new or "").strip(), str(orig or "")
    if not new or len(new) > 320 or _EMAIL.search(new) or re.search(r"https?://|www\.|\[", new):
        return False
    nums = lambda s: set(re.findall(r"\d[\d,.]*\d|\d", s))      # noqa: E731
    if not nums(new) <= nums(orig):
        return False
    ok = {s.lower() for s in extract_skills(orig)} | {str(a).lower() for a in allowed}
    if any(s.lower() not in ok for s in extract_skills(new)):
        return False
    words = set(re.findall(r"[a-z0-9]+", (orig + " " + " ".join(str(a) for a in allowed)).lower()))
    names = re.findall(r"(?<=[a-z,;] )[A-Z][A-Za-z]+", new)            # capitalized words mid-sentence: names of places, firms, tools
    return all(n.lower() in words for n in names)


def _job_terms(job: dict) -> tuple[list, list]:
    from quals import of as _quals_of
    jtext = str(job.get("title") or "") + "\n" + str(job.get("description") or "")
    jskills = list(dict.fromkeys(extract_skills(jtext) + [q["label"] for q in _quals_of(job) if q.get("kind") == "skill"]))
    return jskills, _keywords(str(job.get("title") or "") + " " + str(job.get("description") or ""))


def _best_entry(doc: dict, keys: tuple, jskills: list, kws: list) -> tuple[dict | None, int, list]:
    best, top, hits = None, 0, []
    for sec in doc["sections"]:
        if sec["key"] not in keys:
            continue
        for e in sec["entries"]:
            sc, hs = _relevance(e["head"] + " " + " ".join(b["text"] for b in e["bullets"]), jskills, kws)
            if sc > top:
                best, top, hits = e, sc, hs
    return best, top, hits


def stand_out_job(profile: dict | None, text: str, job: dict, today: tuple[int, int] | None = None) -> list[dict]:
    """'Help me stand out' for one job: 3-6 concrete tips drawn only from the student's own resume and profile."""
    profile = profile or {}
    doc = _doc_parse(text)
    jskills, kws = _job_terms(job)
    tips: list[dict] = []
    e, sc, hits = _best_entry(doc, ("experience", "leadership"), jskills, kws)
    if e and (e["head"] or e["bullets"]):
        where = _SEG.split(e["head"])[0].strip() or "that role"
        tips.append({"title": "Lead with " + where[:80], "kind": "lead",
                     "detail": f"It shows {_and(hits[:3])}, which this posting asks for. Keep it near the top, and bring it up first when you talk to them."})
    proj, psc, phits = _best_entry(doc, ("projects",), jskills, kws)
    ptitle = _SEG.split(proj["head"])[0].strip() if proj else ""
    if not proj:
        for it in profile.get("items") or []:
            if it.get("kind") == "project" and it.get("title"):
                s2, h2 = _relevance(str(it.get("title")) + " " + str(it.get("description") or ""), jskills, kws)
                if s2 > psc:
                    ptitle, psc, phits = str(it["title"]).strip(), s2, h2
    if ptitle and psc:
        tips.append({"title": "Mention your project " + ptitle[:70], "kind": "project",
                     "detail": f"It's the project that best matches this job: it shows {_and(phits[:3])}. Put the link on your resume if it's online."})
    import fit as _fit
    f = _fit.fit_score(job, dict(profile, skills=[], items=[], headline="", bio="", resume_text=text), today)
    mine = {str(s).lower() for s in (profile.get("skills") or [])}
    shown = 0
    for c in f["checklist"]:
        if c["status"] != "missing" or c["text"].startswith(("Major:", "GPA", "Class standing")) or shown >= 2:
            continue
        s = c["text"].replace(" (preferred)", "")
        if s.lower() in mine:
            tips.append({"title": f"Show where you used {s}", "kind": "evidence",
                         "detail": f"It's on your profile and this job lists it, but nothing on your resume shows it. Add one bullet about where you used it."})
        else:
            tips.append({"title": f"Build evidence for {s}", "kind": "gap",
                         "detail": f"The posting asks for {s} and nothing you've shared shows it. If you've used it in a class or club, add that. If not, a short course or a small project can show it. Don't list it until it's true."})
        shown += 1
    if e:
        bare = [b for b in e["bullets"] if not _NUM.search(b["text"])]
        if bare:
            tips.append({"title": "Add numbers to " + (_SEG.split(e["head"])[0].strip() or "your top role")[:70], "kind": "numbers",
                         "detail": f"{len(bare)} of its bullets {'has' if len(bare) == 1 else 'have'} no number. How many people, hours, dollars or percent? Numbers are what screeners remember."})
    if any(c["status"] == "met" and c["text"].startswith("Major:") for c in f["checklist"]):
        tips.append({"title": "Say your major up front", "kind": "major",
                     "detail": "This posting lists your major. Your summary and note should say it in the first line."})
    if len(tips) < 3:
        tips.append({"title": "Open with a summary aimed at this job", "kind": "summary",
                     "detail": "Two lines on your major, your strongest skills for this role and your most relevant experience. Tailor my resume writes one from what you've shared."})
    if len(tips) < 3:
        tips.append({"title": "Follow up after you apply", "kind": "follow",
                     "detail": "Once you've applied, a short, specific note to the person who posted the job helps you stand out. There's a draft under Message the poster."})
    return tips[:6]


def cover_note(profile: dict | None, text: str, job: dict, poster: str = "") -> str:
    """A short note to the listing's poster, built only from what the student has shared."""
    profile = profile or {}
    doc = _doc_parse(text)
    jskills, kws = _job_terms(job)
    name = str(profile.get("display_name") or doc["name"] or "").strip()
    major, grad = str(profile.get("major") or "").strip(), str(profile.get("grad_term") or "").strip()
    who = (f"I'm {name}, a" if name else "I'm a") + (f" {major}" if major else "") + " student at Florida State University" + (f" graduating {grad}" if grad else "") + "."
    title, company = str(job.get("title") or "this").strip(), str(job.get("company") or "").strip()
    body = who + f" I'm interested in the {title} role" + (f" at {company}" if company else "") + "."
    best, top = "", 0
    for sec in doc["sections"]:
        if sec["key"] not in BULLET_KEYS:
            continue
        for e in sec["entries"]:
            for b in e["bullets"]:
                t = b["text"].rstrip(".")
                fw = _first_word(t)
                sc, _ = _relevance(t, jskills, kws)
                if sc > top and (fw in STRONG_VERBS or fw.endswith("ed")) and not _PRONOUN.search(t) and len(t.split()) <= 30:
                    best, top = t, sc
    if best:
        body += " For example, I " + best[:1].lower() + best[1:] + "."
    have = []
    for s in extract_skills(text) + [str(x) for x in profile.get("skills") or []]:
        if s.lower() in [j.lower() for j in jskills] and s.lower() not in [h.lower() for h in have]:
            have.append(s)
    if have:
        body += f" I've worked with {_and(have[:3])}, which the posting mentions."
    body += " I'd welcome the chance to talk about how I could help. Thank you for your time."
    return (f"Hi {poster}," if poster else "Hi,") + "\n\n" + body + ("\n\n" + name if name else "")


def _gap_advice(item: str, status: str) -> str:
    if item.startswith("Major:"):
        return "They list these majors. If yours is related, say how your classes connect in your note to the poster."
    if item.startswith("GPA"):
        return "Add your GPA to the Education line if you meet it. If you don't, leave it off; many employers still consider you."
    if item.startswith("Class standing"):
        return "Make sure your expected graduation month and year are on the resume."
    s = item.replace(" (preferred)", "")
    if status == "unknown":
        return f"We can't tell from your resume. If {s} applies to you, add it."
    return (f"Only add {s} if you've really used it, in a class, a club, a project or a job. If you have, write a bullet that shows it. "
            "If not, leave it off and mention a related skill you do have.")


def doc_text(doc: dict) -> str:
    """The resume as plain text (the same form the studio stores, so it can be re-read and re-scored)."""
    out = [doc["name"]]
    if doc["contact"]:
        out.append(" | ".join(doc["contact"]))
    for sec in doc["sections"]:
        out += ["", sec["title"].upper()]
        if sec["key"] == "summary":
            out.append(sec["text"])
            continue
        out += sec["lines"]
        for e in sec["entries"]:
            if e["line"]:
                out.append(e["line"])
            out += e["sub"]
            out += ["• " + b["text"] for b in e["bullets"]]
    return "\n".join(out).strip() + "\n"


def doc_html(doc: dict, marks: bool = True) -> str:
    """The resume as a page-like block (.rs-doc); css_resume styles it and prints only it."""
    e_ = lambda s: html.escape(s or "", quote=True)      # noqa: E731
    parts = [f'<article class="rs-doc" aria-label="Resume preview"><div class="rs-dhd"><h1>{e_(doc["name"])}</h1>']
    if doc["contact"]:
        parts.append('<p class="rs-dc">' + '<i aria-hidden="true"> · </i>'.join(f"<span>{e_(c)}</span>" for c in doc["contact"]) + "</p>")
    parts.append("</div>")
    for sec in doc["sections"]:
        parts.append(f'<section><h2>{e_(sec["title"])}</h2>')
        if sec["key"] == "summary":
            parts.append(f'<p class="rs-ds">{e_(sec["text"])}</p>')
        for ln in sec["lines"]:
            k = ln.find(":")
            parts.append(f'<p class="rs-dsk"><b>{e_(ln[:k + 1])}</b>{e_(ln[k + 1:])}</p>' if 0 < k < 40 else f'<p class="rs-dsk">{e_(ln)}</p>')
        for en in sec["entries"]:
            parts.append('<div class="rs-de">')
            if en["head"] or en["date"]:
                parts.append(f'<div class="rs-dh"><b>{e_(en["head"])}</b>' + (f'<span>{e_(en["date"])}</span>' if en["date"] else "") + "</div>")
            parts += [f'<p class="rs-dsub">{e_(s)}</p>' for s in en["sub"]]
            if en["bullets"]:
                chg = ' class="rs-chg"'
                parts.append("<ul>" + "".join(f'<li{chg if marks and b["change"] else ""}>{e_(b["text"])}</li>' for b in en["bullets"]) + "</ul>")
            parts.append("</div>")
        parts.append("</section>")
    parts.append("</article>")
    return "".join(parts)


def doc_docx(doc: dict) -> bytes:
    """The structured resume as Word: centered name and contact line, ruled headings, bold entry lines with dates, bullets."""
    rows: list[tuple[str, str]] = [("name", doc["name"])] + ([("contact", " | ".join(doc["contact"]))] if doc["contact"] else [])
    for sec in doc["sections"]:
        rows.append(("h", sec["title"].upper()))
        if sec["key"] == "summary":
            rows.append(("p", sec["text"]))
        rows += [("p", ln) for ln in sec["lines"]]
        for e in sec["entries"]:
            if e["head"] or e["date"]:
                rows.append(("e", e["head"] + ("\t" + e["date"] if e["date"] else "")))
            rows += [("p", s) for s in e["sub"]]
            rows += [("b", b["text"]) for b in e["bullets"]]
    return _docx_rows(rows)


def _docx_rows(rows: list[tuple[str, str]]) -> bytes:
    paras = []
    for kind, s in rows:
        rpr, ppr = "", ""
        if kind == "name":
            rpr, ppr = '<w:rPr><w:b/><w:sz w:val="36"/></w:rPr>', '<w:pPr><w:jc w:val="center"/><w:spacing w:after="40"/></w:pPr>'
        elif kind == "contact":
            rpr, ppr = '<w:rPr><w:sz w:val="19"/></w:rPr>', '<w:pPr><w:jc w:val="center"/><w:spacing w:after="120"/></w:pPr>'
        elif kind == "h":
            rpr = '<w:rPr><w:b/><w:caps/><w:sz w:val="22"/></w:rPr>'
            ppr = ('<w:pPr><w:spacing w:before="200" w:after="60"/><w:pBdr><w:bottom w:val="single" w:sz="4" '
                   'w:space="1" w:color="999999"/></w:pBdr></w:pPr>')
        elif kind == "e":
            rpr = "<w:rPr><w:b/></w:rPr>"
            ppr = '<w:pPr><w:tabs><w:tab w:val="right" w:pos="10512"/></w:tabs><w:spacing w:before="80" w:after="20"/></w:pPr>'
        elif kind == "b":
            s = "•\t" + s
            ppr = '<w:pPr><w:ind w:left="360" w:hanging="220"/><w:spacing w:after="20"/></w:pPr>'
        if kind == "e" and "\t" in s:
            head, date = s.split("\t", 1)
            paras.append(f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_x(head)}</w:t></w:r><w:r><w:tab/>'
                         f'<w:t xml:space="preserve">{_x(date)}</w:t></w:r></w:p>')
        else:
            paras.append(f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_x(s)}</w:t></w:r></w:p>')
    return _docx_pack("".join(paras))


# ---------- .pdf export (a small PDF writer: Helvetica, letter size, no dependencies) ----------

# Advance widths (1/1000 em) of Helvetica and Helvetica-Bold for WinAnsi codes 32..255 (0 = not drawable).
_HELV = [int(x) for x in """278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584,0,556,0,222,556,333,1000,556,556,333,1000,667,333,1000,0,611,0,0,222,222,333,333,350,556,1000,333,1000,500,333,944,0,500,667,0,333,556,556,556,556,260,556,333,737,370,556,584,0,737,333,400,584,0,0,333,556,537,278,333,0,365,556,834,834,834,611,667,667,667,667,667,667,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,556,556,556,556,556,556,889,500,556,556,556,556,278,278,278,278,556,556,556,556,556,556,556,584,611,556,556,556,556,500,556,500""".split(",")]
_HELVB = [int(x) for x in """278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,333,333,584,584,584,611,975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611,333,278,333,584,556,333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500,389,280,389,584,0,556,0,278,556,500,1000,556,556,333,1000,667,333,1000,0,611,0,0,278,278,500,500,350,556,1000,333,1000,556,333,944,0,500,667,0,333,556,556,556,556,280,556,333,737,370,556,584,0,737,333,400,584,0,0,333,611,556,278,333,0,365,556,834,834,834,611,722,722,722,722,722,722,1000,722,667,667,667,667,278,278,278,278,722,722,778,778,778,778,778,584,778,722,722,722,722,667,667,611,556,556,556,556,556,556,889,556,556,556,556,556,278,278,278,278,611,611,611,611,611,611,611,584,611,611,611,611,611,556,611,556""".split(",")]
_WIN_HI = "€\x81‚ƒ„…†‡ˆ‰Š‹Œ\x8dŽ\x8f\x90‘’“”•–—˜™š›œ\x9džŸ"      # the characters at WinAnsi 128..159


def _win(ch: str) -> int:
    o = ord(ch)
    if 32 <= o <= 126 or 160 <= o <= 255:
        c = o
    elif ch in _WIN_HI:
        c = 128 + _WIN_HI.index(ch)
    elif ch in "\t   ":
        c = 32
    elif ch in "‐‑‒":
        c = 45
    else:
        return 63
    return c if _HELV[c - 32] else 63


def _pdf_width(s: str, bold: bool, size: float) -> float:
    w = _HELVB if bold else _HELV
    return sum(w[_win(ch) - 32] for ch in s) * size / 1000


def _pdf_str(s: str) -> str:
    out = []
    for ch in s:
        c = _win(ch)
        if c in (40, 41, 92):
            out.append("\\" + chr(c))
        elif c > 126:
            out.append("\\" + format(c, "o").zfill(3))
        else:
            out.append(chr(c))
    return "(" + "".join(out) + ")"


def _wrap(s: str, bold: bool, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for w in s.split():
        t = cur + " " + w if cur else w
        if cur and _pdf_width(t, bold, size) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
        while len(cur) > 1 and _pdf_width(cur, bold, size) > width:       # one very long word: break it
            k = len(cur)
            while k > 1 and _pdf_width(cur[:k], bold, size) > width:
                k -= 1
            lines.append(cur[:k])
            cur = cur[k:]
    if cur:
        lines.append(cur)
    return lines or [""]


def _num(v: float) -> str:
    s = str(math.floor(v * 100 + 0.5) / 100)          # half-up, the same as the demo's Math.round port
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def pdf_bytes(pages: list[list[str]], title: str = "Resume") -> bytes:
    """Assemble a PDF from per-page content-stream operators: uncompressed, ASCII and deterministic."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            f"<< /Title {_pdf_str(title)} /Producer (NoleCareerShield) >>"]
    kids = []
    for ops in pages:
        stream = "\n".join(ops)
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = "%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(str(o).zfill(10) + " 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("ascii")


def to_pdf(doc: dict) -> bytes:
    """The resume as a letter-size PDF: name, contact line, ruled section headings, entries with dates on the right, bullets."""
    M, W, TOP, BOT = 54, 504, 738, 54
    pages: list[list[str]] = [[]]
    st = {"y": TOP}

    def need(h):
        if st["y"] - h < BOT:
            pages.append([])
            st["y"] = TOP

    def put(x, s, bold, size):
        pages[-1].append(f"BT /{'F2' if bold else 'F1'} {_num(size)} Tf {_num(x)} {_num(st['y'])} Td {_pdf_str(s)} Tj ET")

    def para(s, indent=0, bullet=False):
        for i, ln in enumerate(_wrap(s, False, 10, W - indent)):
            need(12.5)
            st["y"] -= 12.5
            if i == 0 and bullet:
                put(M + indent - 10, "•", False, 10)
            put(M + indent, ln, False, 10)

    for ln in _wrap(doc["name"], True, 20, W):
        st["y"] -= 22
        put(M + (W - _pdf_width(ln, True, 20)) / 2, ln, True, 20)
    if doc["contact"]:
        for ln in _wrap("  |  ".join(doc["contact"]), False, 9.5, W):
            st["y"] -= 13
            put(M + (W - _pdf_width(ln, False, 9.5)) / 2, ln, False, 9.5)
    for sec in doc["sections"]:
        need(40)
        st["y"] -= 20
        put(M, sec["title"].upper(), True, 10.5)
        pages[-1].append(f"0.6 w 0.55 G {M} {_num(st['y'] - 4)} m {M + W} {_num(st['y'] - 4)} l S 0 G")
        st["y"] -= 4
        if sec["key"] == "summary":
            para(sec["text"])
        for ln in sec["lines"]:
            para(ln)
        for e in sec["entries"]:
            if e["head"] or e["date"]:
                dw = _pdf_width(e["date"], False, 10) if e["date"] else 0
                heads = _wrap(e["head"], True, 10, W - dw - 12)
                need(3 + 12.5 * len(heads))
                st["y"] -= 3
                for i, h in enumerate(heads):
                    st["y"] -= 12.5
                    put(M, h, True, 10)
                    if i == 0 and e["date"]:
                        put(M + W - dw, e["date"], False, 10)
            for s in e["sub"]:
                para(s)
            for b in e["bullets"]:
                para(b["text"], 14, True)
    return pdf_bytes([p for p in pages if p] or [[]], doc["name"] + " resume")
