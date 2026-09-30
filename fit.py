"""
How well a student fits one job, scored 0-100 from the whole profile, not just job titles.

What it reads from the student: the skills list, the resume, every experience, project,
organization and certification entry, education (major, minor, GPA, coursework, graduation
date) and what they're looking for (work setting, job type, locations).

What it reads from the job: required vs preferred skills, keywords, majors it asks for, a
minimum GPA, class standing or graduation year, certifications, work setting, job type and
location.

Six parts, each 0-100, weighted and combined. A part the job doesn't ask about (say, no
certifications) is left out and the rest are re-weighted, so a job is never scored on
something it didn't ask for:
    Skills 35 · Experience & projects 25 · Education 15 · Certifications 10 · Keywords 10 · Preferences 10

Every number comes with the evidence: where each matched skill was found in the profile,
and a checklist of the job's requirements marked met, not shown yet, or unknown.
demo/engine.js has a line-for-line port checked by tests/test_demo_engine.py.
"""

from __future__ import annotations

import copy
import functools
import quals as _quals
import re
import time

from matching import CATEGORY_WORDS, JOB_KINDS, categories_for_major, extract_skills
from resume_engine import _GENERIC, parse

WEIGHTS = {"skills": 35, "experience": 25, "education": 15, "certifications": 10, "keywords": 10, "preferences": 10}
NAMES = {"skills": "Skills", "experience": "Experience & projects", "education": "Education", "certifications": "Certifications",
         "keywords": "Keywords", "preferences": "Preferences"}

PREFERRED = re.compile(r"\b(?:preferred|nice to have|a plus|bonus|ideally|desired|is helpful|are helpful|not required|familiarity with)\b", re.IGNORECASE)
_SENT = re.compile(r"[^.\n;!?]+[.\n;!?]?")

MAJORS = {
    "accounting": ["accounting"], "finance": ["finance"], "economics": ["economics"], "business": ["business administration", "business"],
    "marketing": ["marketing"], "management": ["management"], "statistics": ["statistics"], "mathematics": ["mathematics", "math"],
    "computer science": ["computer science", "cs"], "information technology": ["information technology", "information systems", "mis"],
    "data science": ["data science", "analytics"], "engineering": ["engineering"], "biology": ["biology", "biological"],
    "chemistry": ["chemistry"], "psychology": ["psychology"], "communications": ["communications", "communication", "media"],
    "journalism": ["journalism"], "public health": ["public health"], "nursing": ["nursing"], "education": ["education"],
    "english": ["english"], "political science": ["political science"], "criminology": ["criminology", "criminal justice"],
    "hospitality": ["hospitality"], "supply chain": ["supply chain"], "real estate": ["real estate"], "graphic design": ["graphic design", "design"],
    "sociology": ["sociology"], "physics": ["physics"], "neuroscience": ["neuroscience"], "nutrition": ["nutrition"],
    "exercise science": ["exercise science", "kinesiology"], "social work": ["social work"],
}
MAJOR_CONTEXT = re.compile(r"\b(?:major(?:s|ing)?|degree|studying|pursuing|coursework|background|students?|enrolled in)\b", re.IGNORECASE)
NOT_MAJOR = {"business": r"business(?!\s+(?:analytics|intelligence|development|hours|days|casual|needs|partners?|owners?))",
             "analytics": r"analytics", "communication": r"communication(?!\s+skills)", "design": r"design"}
_TERM_STOP = _GENERIC | set("""build building built help helping clean cleaning present presenting weekly daily monthly hours hour week
paid pay team teams short friday readout support supporting assist assisting including include includes must should will
would also please apply summer fall spring semester during per plus related field fields minimum required requirements preferred
role roles position candidate strong comfort comfortable ability experience experienced familiarity knowledge work working job jobs
student students intern interns internship years year ideal responsibilities responsible opportunity join grow growing learn
learning great good using used flag find make ensure provide biweekly juniors seniors sophomores freshmen freshman junior senior
majoring major majors minor degree hold holds certified certification certifications preferably""".split()) | {w for ws in MAJORS.values() for w in ws}
STANDING = re.compile(r"\b(freshm[ae]n|sophomores?|juniors?|seniors?|graduate students?|recent grad(?:uate)?s?|new grads?)\b", re.IGNORECASE)
GRAD_YEAR = re.compile(r"\b(?:graduating|graduation|class of|grad date)\D{0,24}((?:19|20)\d{2})\b", re.IGNORECASE)
GPA_REQ = re.compile(r"\b(?:gpa|grade point average)\D{0,30}?(\d\.\d{1,2})|(\d\.\d{1,2})\s*(?:\+|or (?:higher|above|better))?\s*(?:cumulative\s+|minimum\s+)?gpa\b", re.IGNORECASE)
GPA_HAVE = re.compile(r"\bgpa\b[:\s]*(\d\.\d{1,2})|(\d\.\d{1,2})\s*(?:/\s*4\.0+\s*)?gpa\b", re.IGNORECASE)
CERTS = {
    "CPR/First aid": r"\bcpr\b|\bfirst aid\b|\bbls\b", "ServSafe / food handler": r"\bservsafe\b|\bfood handler",
    "CompTIA": r"\bcomptia\b|\ba\+ certif|\bsecurity\+|\bnetwork\+", "Microsoft Office Specialist": r"\bmicrosoft office specialist\b|\bmos certif|\bexcel (?:expert|certif)",
    "Google Analytics certification": r"\bgoogle analytics (?:certif|individual)|\bga4 certif", "CNA": r"\bcna\b|\bcertified nursing assistant\b",
    "EMT": r"\bemt\b", "Lifeguard": r"\blifeguard", "Driver's license": r"\bdriver'?s licen[cs]e\b|\bvalid (?:driver'?s )?licen[cs]e\b",
    "AWS certification": r"\baws certif|\baws certified\b", "SHRM": r"\bshrm\b", "Notary": r"\bnotary\b",
    "Bloomberg (BMC)": r"\bbloomberg market concepts\b|\bbmc\b", "Tableau certification": r"\btableau (?:desktop )?(?:specialist|certif)",
    "HIPAA training": r"\bhipaa (?:training|certif)", "Salesforce certification": r"\bsalesforce (?:certif|administrator|trailhead)",
}
_TITLE_STOP = set("intern internship part time part-time full full-time assistant associate student entry level junior senior the and of for".split())
LABELS = [(80, "Strong fit"), (65, "Good fit"), (45, "Partial fit"), (0, "Stretch")]


def _year_month(today: tuple[int, int] | None) -> tuple[int, int]:
    if today:
        return today
    t = time.gmtime()
    return t.tm_year, t.tm_mon


def _grad_year(profile: dict) -> int | None:
    m = re.search(r"((?:19|20)\d{2})", profile.get("grad_term") or "")
    if m:
        return int(m.group(1))
    for it in profile.get("items") or []:
        if it.get("kind") == "education" and (it.get("current") or not it.get("end")) is False:
            m = re.search(r"((?:19|20)\d{2})", it.get("end") or "")
            if m:
                return int(m.group(1))
    return None


def _standing(grad_year: int | None, today: tuple[int, int]) -> str:
    if not grad_year:
        return ""
    y, mth = today
    years_left = grad_year - y - (0.5 if mth >= 7 else 0)
    if years_left < 0:
        return "graduate"
    if years_left <= 1:
        return "senior"
    if years_left <= 2:
        return "junior"
    if years_left <= 3:
        return "sophomore"
    return "freshman"


def _sources(profile: dict) -> list[tuple[str, str, str]]:
    """(label, kind, text) for every piece of the profile that can hold evidence."""
    out = []
    if profile.get("skills"):
        out.append(("Your skills list", "skills", ", ".join(profile["skills"])))
    for it in profile.get("items") or []:
        k = it.get("kind")
        text = " ".join(str(x) for x in (it.get("title"), it.get("org"), it.get("description"),
                                          " ".join((it.get("extra") or {}).get("coursework") or []),
                                          (it.get("extra") or {}).get("major") or "", (it.get("extra") or {}).get("skills") or ""))
        name = it.get("title") or it.get("org") or k
        label = {"experience": f"{name}" + (f" at {it['org']}" if it.get("org") and it.get("title") else ""),
                 "project": f"{name} (project)", "education": f"{it.get('org') or name}",
                 "certification": f"{name} (certification)", "organization": f"{it.get('org') or name}",
                 "course": f"{name} (course)", "language": f"{name}"}.get(k, name)
        out.append((label, k, text))
    if profile.get("resume_text"):
        out.append(("Your resume", "resume", profile["resume_text"]))
    about = " ".join(x for x in (profile.get("headline"), profile.get("bio")) if x)
    if about:
        out.append(("Your headline and about", "about", about))
    return out


def job_requirements(title: str, text: str) -> dict:
    return copy.deepcopy(_job_requirements(title, text))


@functools.lru_cache(maxsize=512)
def _job_requirements(title: str, text: str) -> dict:
    full = f"{title}\n{text}"
    required, preferred = [], []
    for m in _SENT.finditer(full):
        sent = m.group(0)
        for s in extract_skills(sent):
            (preferred if PREFERRED.search(sent) else required).append(s)
    required = list(dict.fromkeys(required))
    preferred = [s for s in dict.fromkeys(preferred) if s not in required]
    majors = []
    for m in _SENT.finditer(full):
        sent = m.group(0)
        if MAJOR_CONTEXT.search(sent):
            low = " " + sent.lower() + " "
            for canon, words in MAJORS.items():
                if any(re.search(r"\b" + NOT_MAJOR.get(w, re.escape(w)) + r"\b", low) for w in words) and canon not in majors:
                    majors.append(canon)
    g = GPA_REQ.search(full)
    gpa = float(g.group(1) or g.group(2)) if g else None
    standing = sorted({s.lower().rstrip("s").replace("freshmen", "freshman").replace("freshme", "freshman") for s in STANDING.findall(full)})
    standing = [("graduate" if s.startswith(("graduate", "recent", "new")) else s) for s in standing]
    gy = [int(y) for y in GRAD_YEAR.findall(full)]
    certs = [name for name, rx in CERTS.items() if re.search(rx, full, re.IGNORECASE)]
    required = [s for s in required if s not in certs]
    preferred = [s for s in preferred if s not in certs]
    low = " " + full.lower() + " "
    kind = next((k for k in JOB_KINDS if any(w in low for w in {"internship": [" intern", "internship", "co-op"], "part-time": ["part-time", "part time"],
                                                                     "full-time": ["full-time", "full time"], "on-campus": ["on campus", "on-campus"]}[k])), "")
    skills = set(required) | set(preferred)
    kws = [k for k in _terms(full) if k not in {s.lower() for s in skills}]
    return {"required": required, "preferred": preferred, "majors": majors, "gpa": gpa, "standing": sorted(set(standing)),
            "grad_years": sorted(set(gy)), "certs": certs, "kind": kind, "keywords": kws}


def _merge_quals(req: dict, chosen: list[dict], must_of: dict) -> dict:
    """Employer-chosen items win: skills/majors/certs are added, a chosen standing/year/GPA replaces the parsed one."""
    req = copy.deepcopy(req)
    for q in chosen:
        k, l = q["kind"], q["label"]
        must_of[l.lower()] = bool(q.get("must"))
        if k == "skill":
            bucket, other = ("required", "preferred") if q.get("must") else ("preferred", "required")
            if l in req[other]:
                req[other].remove(l)
            if l not in req[bucket] and l not in req["required"]:
                req[bucket].append(l)
        elif k == "major":
            canon = next((c for c, ws in MAJORS.items() if l.lower() == c.lower() or l.lower() in ws), l)
            if canon not in req["majors"]:
                req["majors"].append(canon)
        elif k == "cert":
            if l not in req["certs"]:
                req["certs"].append(l)
            req["required"] = [s for s in req["required"] if s != l]
        elif k == "standing":
            req["standing"] = sorted(set(req["standing"]) | {l})
        elif k == "gradyear":
            req["grad_years"] = sorted(set(req["grad_years"]) | {int(l)})
        elif k == "gpa":
            req["gpa"] = float(l)
    return req


def fit_score(job: dict, profile: dict | None, today: tuple[int, int] | None = None) -> dict:
    profile = profile or {}
    today = _year_month(today)
    req = job_requirements(job.get("title", ""), job.get("description", ""))
    chosen = _quals.of(job)
    must_of: dict[str, bool] = {}
    if chosen:
        req = _merge_quals(req, chosen, must_of)
    srcs = _sources(profile)
    skill_where: dict[str, list[str]] = {}
    for label, kind, text in srcs:
        for s in extract_skills(text):
            skill_where.setdefault(s, []).append(label)
    for s in profile.get("skills") or []:
        skill_where.setdefault(s, []).insert(0, "Your skills list") if "Your skills list" not in skill_where.get(s, []) else None
    all_text = " ".join(t for _, _, t in srcs).lower()
    for q in chosen:  # skills the employer typed that our vocabulary doesn't know: match them literally
        if q["kind"] == "skill" and q["label"] not in skill_where:
            rx = r"(?<![a-z0-9])" + re.escape(q["label"].lower()) + r"(?![a-z0-9])"
            hits = [lbl for lbl, _, t in srcs if re.search(rx, t.lower())]
            if hits:
                skill_where[q["label"]] = hits
    parts: dict[str, dict] = {}
    checklist: list[dict] = []

    # 1. Skills: required count twice as much as preferred.
    wanted = [(s, 1.0, True) for s in req["required"]] + [(s, 0.5, False) for s in req["preferred"]]
    matched, missing = [], []
    if wanted:
        got = sum(w for s, w, _ in wanted if s in skill_where)
        total = sum(w for _, w, _ in wanted)
        for s, w, is_req in wanted:
            if s in skill_where:
                matched.append({"skill": s, "required": is_req, "where": list(dict.fromkeys(skill_where[s]))[:3]})
            else:
                missing.append({"skill": s, "required": is_req})
            checklist.append({"text": s + ("" if is_req else " (preferred)"), "status": "met" if s in skill_where else "missing",
                              "evidence": ", ".join(list(dict.fromkeys(skill_where.get(s, [])))[:2])})
        parts["skills"] = {"score": round(100 * got / total),
                           "detail": f"{sum(1 for m in matched)} of {len(wanted)} skills the job lists" + (f" ({sum(1 for m in matched if m['required'])} of {len(req['required'])} required)" if req["required"] and req["preferred"] else "")}

    # 2. Experience & projects: job terms evidenced in real entries (or resume bullets), plus a related role.
    terms = [s.lower() for s in req["required"] + req["preferred"]] + req["keywords"][:8]
    entries = [(label, text.lower()) for label, kind, text in srcs if kind in ("experience", "project", "organization")]
    if not entries and profile.get("resume_text"):
        entries = [("Your resume", b["text"].lower()) for b in parse(profile["resume_text"])["bullets"]]
    relevant = []
    if entries and terms:
        covered = set()
        for label, text in entries:
            has = {x.lower() for x in extract_skills(text)}
            hits = [t for t in terms if t in has or re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text)]
            if hits:
                relevant.append({"where": label, "hits": hits[:4]})
                covered |= set(hits)
        coverage = min(1.0, len(covered) / max(3, round(len(terms) * 0.6)))
        twords = [w for w in re.findall(r"[a-z]+", (job.get("title") or "").lower()) if w not in _TITLE_STOP and len(w) > 2]
        role = any(any(w in text[:120] for w in twords) for _, text in entries) if twords else False
        parts["experience"] = {"score": round(100 * (0.75 * coverage + 0.25 * (1 if role else 0))),
                               "detail": (f"{len(relevant)} of your entries relate to this job" if relevant else "None of your entries mention what this job asks for yet")
                               + ("; you've held a similar role" if role else "")}
    elif terms:
        parts["experience"] = {"score": 0, "detail": "Add your experience and projects so they can count"}

    # 3. Education: major, GPA, class standing or graduation year.
    edu_scores, edu_notes = [], []
    my_majors = " ".join([profile.get("major") or "", profile.get("minor") or ""] +
                         [(it.get("extra") or {}).get("major", "") + " " + (it.get("extra") or {}).get("minor", "") + " " + (it.get("title") or "")
                          + " " + " ".join((it.get("extra") or {}).get("coursework") or [])
                          for it in profile.get("items") or [] if it.get("kind") == "education"]
                         + [it.get("title") or "" for it in profile.get("items") or [] if it.get("kind") == "course"]).lower()
    if req["majors"]:
        hit = [m for m in req["majors"] if any(re.search(r"\b" + NOT_MAJOR.get(w, re.escape(w)) + r"\b", my_majors) for w in MAJORS[m])]
        if hit:
            edu_scores.append(1.0); edu_notes.append("Your major or coursework covers " + " and ".join(hit[:2]))
        elif re.search(r"related field|similar field|or related|quantitative field", (job.get("description") or ""), re.IGNORECASE) and \
                set(categories_for_major(profile.get("major", ""))) & set(_job_categories(job)):
            edu_scores.append(0.6); edu_notes.append("Your major is related to the fields they list")
        else:
            edu_scores.append(0.15 if my_majors.strip() else 0.4); edu_notes.append("They list " + ", ".join(req["majors"][:3]) + " majors")
        checklist.append({"text": "Major: " + " or ".join(req["majors"][:4]), "status": "met" if hit else ("unknown" if not my_majors.strip() else "missing"),
                          "evidence": profile.get("major") or ""})
    elif profile.get("major"):
        fits = set(categories_for_major(profile["major"])) & set(_job_categories(job))
        edu_scores.append(0.9 if fits else 0.65); edu_notes.append("Your major lines up with this kind of work" if fits else "No specific major required")
    if req["gpa"]:
        have = _gpa(profile)
        if have is None:
            edu_scores.append(0.6); status = "unknown"; edu_notes.append(f"Asks for a {req['gpa']:.1f}+ GPA; add yours if you meet it")
        else:
            ok = have >= req["gpa"] - 1e-9
            edu_scores.append(1.0 if ok else 0.1); status = "met" if ok else "missing"
            edu_notes.append(f"GPA {have:.2f} vs {req['gpa']:.1f} required")
        checklist.append({"text": f"GPA {req['gpa']:.1f} or higher", "status": status, "evidence": "" if have is None else f"{have:.2f}"})
    standing = _standing(_grad_year(profile), today)
    if req["standing"] or req["grad_years"]:
        gy = _grad_year(profile)
        ok = None
        if req["grad_years"] and gy:
            ok = gy in req["grad_years"]
        elif req["standing"] and standing:
            ok = standing in req["standing"]
        want = ", ".join([s.title() + "s" if not s.endswith("e") else s.title() + " students" for s in req["standing"]] + [str(y) for y in req["grad_years"]])
        edu_scores.append(0.6 if ok is None else (1.0 if ok else 0.2))
        checklist.append({"text": "Class standing: " + want, "status": "unknown" if ok is None else ("met" if ok else "missing"),
                          "evidence": (standing.title() if standing else "") + (f", graduating {gy}" if gy else "")})
        edu_notes.append(f"They want {want}" + (f"; you're a {standing}" if standing else ""))
    if edu_scores:
        parts["education"] = {"score": round(100 * sum(edu_scores) / len(edu_scores)), "detail": "; ".join(edu_notes[:2])}

    # 4. Certifications the job names.
    if req["certs"]:
        have = [c for c in req["certs"] if re.search(CERTS.get(c) or (r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])"), all_text, re.IGNORECASE)]
        parts["certifications"] = {"score": round(100 * len(have) / len(req["certs"])),
                                   "detail": f"{len(have)} of {len(req['certs'])}: " + ", ".join(req["certs"][:3])}
        for c in req["certs"]:
            checklist.append({"text": c, "status": "met" if c in have else "missing", "evidence": ""})

    # 5. Keywords from the posting found anywhere in the profile.
    if req["keywords"]:
        kw_hit = [k for k in req["keywords"] if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", all_text)]
        parts["keywords"] = {"score": round(100 * len(kw_hit) / len(req["keywords"])),
                             "detail": f"{len(kw_hit)} of {len(req['keywords'])} key terms from the posting"}
    else:
        kw_hit = []

    # 6. What they're looking for.
    prefs, pnotes = [], []
    wt = job.get("work_type") or ""
    if profile.get("work_types"):
        ok = wt in profile["work_types"]
        prefs.append(1.0 if ok else 0.3); pnotes.append((wt[:1].upper() + wt[1:]) + (" matches what you want" if ok else " isn't your first choice"))
    if req["kind"] and profile.get("job_kinds"):
        ok = req["kind"] in profile["job_kinds"]
        prefs.append(1.0 if ok else 0.3); pnotes.append(req["kind"][:1].upper() + req["kind"][1:] + (" is a type you want" if ok else " isn't a type you picked"))
    locs = [l.lower() for l in profile.get("pref_locations") or [] if l]
    if locs and wt != "remote" and job.get("location"):
        jl = job["location"].lower()
        ok = any(l.split(",")[0].strip() in jl or jl.split(",")[0].strip() in l for l in locs)
        prefs.append(1.0 if ok else 0.4); pnotes.append(("In " if ok else "Outside ") + "your preferred locations")
    if prefs:
        parts["preferences"] = {"score": round(100 * sum(prefs) / len(prefs)), "detail": "; ".join(pnotes[:2])}

    total_w = sum(WEIGHTS[k] for k in parts)
    score = round(sum(WEIGHTS[k] * p["score"] for k, p in parts.items()) / total_w) if total_w else 0
    completeness = sum(1 for x in (profile.get("skills"), profile.get("resume_text"),
                                   any(i.get("kind") in ("experience", "project") for i in profile.get("items") or []),
                                   profile.get("major")) if x)
    label = next(name for cut, name in LABELS if score >= cut)
    return {"score": score, "label": label, "confidence": ["low", "low", "medium", "medium", "high"][completeness],
            "parts": [{"key": k, "name": NAMES[k], "weight": WEIGHTS[k], **parts[k]} for k in WEIGHTS if k in parts],
            "matched": matched, "missing": missing, "relevant": relevant[:5], "keywords_hit": kw_hit,
            "keywords_missing": [k for k in req["keywords"] if k not in kw_hit][:8], "checklist": [{**c, "must": _is_must(c["text"], must_of)} for c in checklist[:16]], "requirements": req,
            "percent": score, "level": "high" if score >= 75 else ("medium" if score >= 50 else "low"),
            "met": sum(1 for c in checklist if c["status"] == "met"), "total": len(checklist)}


def _is_must(text: str, must_of: dict) -> bool:
    t = text.lower().replace(" (preferred)", "")
    for k in (t, t.split(":", 1)[-1].strip()):
        if k in must_of:
            return must_of[k]
    return any(m and m in t for m in must_of if must_of[m])


def _terms(text: str, n: int = 10) -> list[str]:
    """The posting's distinctive words: most frequent first, then first appearance."""
    counts: dict[str, int] = {}
    for w in re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower()):
        if w not in _TERM_STOP and not w.endswith("ly"):
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:n]


def _gpa(profile: dict) -> float | None:
    for it in profile.get("items") or []:
        g = (it.get("extra") or {}).get("gpa")
        if g:
            try:
                return float(g)
            except ValueError:
                pass
    m = GPA_HAVE.search(profile.get("resume_text") or "")
    return float(m.group(1) or m.group(2)) if m else None


def _job_categories(job: dict) -> list[str]:
    out = [job.get("category")] if job.get("category") else []
    low = " " + ((job.get("title") or "") + " " + (job.get("description") or "")).lower() + " "
    for cat, words in CATEGORY_WORDS.items():
        if cat not in out and sum(1 for w in words if w in low) >= 2:
            out.append(cat)
    return out
