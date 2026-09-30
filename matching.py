"""
Job matching without a model: skills vocabulary, skill extraction, query parsing and an
explainable ranking. The AI assistant calls these as tools, and they are the whole answer
when no AI key is configured. Every score comes with the reasons behind it.
"""

from __future__ import annotations

import re
from functools import lru_cache

# canonical skill -> phrases that mean it (lower case). Single ambiguous words ("R", "Go",
# "Word", "Access") only count in unambiguous forms.
SKILLS: dict[str, list[str]] = {
    # data & analytics
    "Excel": ["excel", "spreadsheets", "spreadsheet", "vlookup", "xlookup", "pivot tables", "pivot table"],
    "SQL": ["sql", "mysql", "postgresql", "postgres", "sqlite", "t-sql", "pl/sql", "sql server"],
    "Python": ["python", "pandas", "numpy", "jupyter"],
    "R": ["r programming", "rstudio", "tidyverse", "ggplot"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Data analysis": ["data analysis", "data analytics", "analyzing data", "analyze data", "data analyst"],
    "Data visualization": ["data visualization", "dashboards", "dashboard", "data viz"],
    "Statistics": ["statistics", "statistical analysis", "regression", "hypothesis testing"],
    "SPSS": ["spss"], "Stata": ["stata"], "SAS": ["sas programming", "sas enterprise", "base sas"],
    "Machine learning": ["machine learning", "scikit-learn", "sklearn", "deep learning", "pytorch", "tensorflow"],
    "Data entry": ["data entry", "typing"],
    "Google Analytics": ["google analytics", "ga4"],
    # software & IT
    "Java": ["java"], "JavaScript": ["javascript", "js", "node.js", "nodejs", "typescript"],
    "React": ["react", "react.js", "reactjs", "next.js"], "HTML/CSS": ["html", "css", "html/css"],
    "C++": ["c++", "cpp"], "C#": ["c#", ".net", "dotnet"], "Go": ["golang"], "Swift": ["swift", "ios development"],
    "Kotlin": ["kotlin", "android development"], "PHP": ["php", "laravel"], "Ruby": ["ruby", "rails"],
    "Git": ["git", "github", "gitlab", "version control"], "Linux": ["linux", "unix", "bash", "shell scripting"],
    "AWS": ["aws", "amazon web services", "ec2", "s3"], "Azure": ["azure"], "Docker": ["docker", "kubernetes", "containers"],
    "APIs": ["api", "apis", "rest api", "restful"], "Cybersecurity": ["cybersecurity", "cyber security", "information security", "infosec", "security+"],
    "Networking": ["networking", "tcp/ip", "network administration", "ccna"], "IT support": ["help desk", "helpdesk", "it support", "technical support", "troubleshooting"],
    "Web development": ["web development", "web developer", "front-end", "frontend", "back-end", "backend", "full stack", "full-stack"],
    "MATLAB": ["matlab"], "CAD": ["cad", "autocad", "solidworks", "fusion 360"],
    # office & business
    "Microsoft Office": ["microsoft office", "ms office", "office 365", "microsoft 365", "microsoft word", "ms word", "outlook", "microsoft access"],
    "PowerPoint": ["powerpoint", "presentations", "slide decks"],
    "Google Workspace": ["google workspace", "google docs", "google sheets", "g suite", "gsuite"],
    "Scheduling": ["scheduling", "calendar management", "appointment setting"],
    "Project management": ["project management", "asana", "trello", "jira", "agile", "scrum"],
    "Bookkeeping": ["bookkeeping", "quickbooks", "accounts payable", "accounts receivable", "invoicing", "reconciliation"],
    "Accounting": ["accounting", "gaap", "general ledger", "financial statements", "audit"],
    "Financial modeling": ["financial modeling", "financial analysis", "valuation", "dcf", "forecasting", "budgeting"],
    "Salesforce": ["salesforce", "crm"], "HubSpot": ["hubspot"],
    "Sales": ["sales", "selling", "lead generation", "cold calling", "business development"],
    "Customer service": ["customer service", "customer support", "client service", "guest service", "customer experience"],
    "Cash handling": ["cash handling", "cashier", "point of sale", "pos system", "cash register"],
    "Inventory": ["inventory", "stocking", "warehouse", "shipping and receiving", "forklift", "logistics"],
    "Event planning": ["event planning", "event coordination", "events"],
    # marketing & creative
    "Social media": ["social media", "instagram", "tiktok", "facebook", "linkedin marketing", "content calendar"],
    "Marketing": ["marketing", "digital marketing", "brand", "campaigns", "market research"],
    "SEO": ["seo", "search engine optimization", "sem", "google ads"],
    "Email marketing": ["email marketing", "mailchimp", "newsletters"],
    "Content writing": ["content writing", "copywriting", "blog", "blogging", "writing", "editing", "proofreading"],
    "Graphic design": ["graphic design", "adobe illustrator", "illustrator", "indesign", "canva", "figma", "photoshop"],
    "Video editing": ["video editing", "premiere pro", "final cut", "after effects", "davinci resolve"],
    "Photography": ["photography", "photo editing", "lightroom"],
    "UX design": ["ux", "ui/ux", "user research", "wireframes", "prototyping", "usability testing"],
    # research, health, education
    "Research": ["research", "literature review", "research assistant"],
    "Lab skills": ["laboratory", "lab techniques", "pcr", "cell culture", "pipetting", "wet lab"],
    "Patient care": ["patient care", "cna", "medical assistant", "vital signs", "clinical"],
    "HIPAA": ["hipaa"], "CPR/First aid": ["cpr", "first aid", "bls certification"],
    "Tutoring": ["tutoring", "tutor", "teaching", "mentoring", "instruction", "lesson planning"],
    "Childcare": ["childcare", "child care", "babysitting", "camp counselor"],
    # people skills and languages
    "Communication": ["communication skills", "written communication", "verbal communication", "public speaking"],
    "Leadership": ["leadership", "team lead", "supervised", "managed a team", "president", "officer"],
    "Teamwork": ["teamwork", "collaboration", "cross-functional"],
    "Problem solving": ["problem solving", "problem-solving", "critical thinking", "analytical skills"],
    "Time management": ["time management", "organization skills", "organizational skills", "multitasking", "detail oriented", "detail-oriented"],
    "Spanish": ["spanish", "bilingual"], "French": ["french"], "Mandarin": ["mandarin", "chinese"], "Portuguese": ["portuguese"],
    "Food service": ["food service", "barista", "restaurant server", "serving", "food handling", "restaurant", "kitchen"],
    "Driving": ["driver's license", "drivers license", "valid license", "delivery driver"],
}

# Skills shown as quick picks in profile setup.
POPULAR = ["Excel", "SQL", "Python", "Microsoft Office", "Google Workspace", "Customer service", "Communication",
           "Social media", "Marketing", "Content writing", "Graphic design", "Data analysis", "Research",
           "Tutoring", "Sales", "Leadership", "Teamwork", "Time management", "Spanish", "Event planning",
           "JavaScript", "HTML/CSS", "Tableau", "Bookkeeping", "Video editing", "Cash handling", "Project management",
           "Problem solving"]

CATEGORY_WORDS: dict[str, list[str]] = {
    "Data & Analytics": ["data", "analytics", "analyst", "sql", "excel", "tableau", "power bi", "statistics", "dashboard"],
    "Software & IT": ["software", "developer", "engineer", "programming", "coding", "it ", "help desk", "web", "cyber", "tech"],
    "Admin & Office": ["admin", "administrative", "office", "receptionist", "front desk", "clerical", "assistant"],
    "Customer Service": ["customer service", "customer support", "call center", "guest"],
    "Sales": ["sales", "business development", "account"],
    "Marketing": ["marketing", "social media", "brand", "content", "seo", "communications", "pr "],
    "Finance & Accounting": ["finance", "accounting", "bookkeeping", "tax", "audit", "banking", "financial"],
    "Research": ["research", "lab", "study", "laboratory"],
    "Education & Tutoring": ["tutor", "tutoring", "teaching", "education", "mentor", "camp"],
    "Healthcare": ["health", "medical", "patient", "clinic", "nurse", "pharmacy", "hospital"],
    "Creative & Design": ["design", "graphic", "video", "photo", "creative", "art", "writer", "writing"],
    "Hospitality & Food": ["restaurant", "barista", "server", "hospitality", "hotel", "food", "catering"],
    "Operations & Warehouse": ["warehouse", "operations", "logistics", "delivery", "driver", "inventory"],
    "Campus Jobs": ["on campus", "on-campus", "campus", "university", "federal work study", "work-study", "ops student"],
}

CATEGORIES = list(CATEGORY_WORDS) + ["Other"]
WORK_TYPES = ["remote", "hybrid", "on-site"]
JOB_KINDS = ["internship", "part-time", "full-time", "on-campus"]

MAJOR_HINTS: list[tuple[tuple[str, ...], list[str]]] = [
    (("computer science", "software", "computer engineering", "information technology", "cyber", "information science"), ["Software & IT", "Data & Analytics"]),
    (("statistic", "math", "data science", "actuarial"), ["Data & Analytics", "Research", "Finance & Accounting"]),
    (("finance", "accounting", "economics", "real estate", "risk management"), ["Finance & Accounting", "Data & Analytics"]),
    (("marketing", "advertising", "public relations", "communication", "media", "journalism"), ["Marketing", "Creative & Design", "Sales"]),
    (("business", "management", "entrepreneur", "supply chain", "hospitality"), ["Admin & Office", "Sales", "Operations & Warehouse", "Hospitality & Food"]),
    (("biology", "chemistry", "biochem", "neuroscience", "physics", "psychology", "exercise", "nutrition", "public health"), ["Research", "Healthcare"]),
    (("nursing", "health", "pre-med", "premed", "kinesiology"), ["Healthcare", "Research"]),
    (("education", "teaching", "english", "history", "philosophy"), ["Education & Tutoring", "Creative & Design"]),
    (("art", "design", "film", "music", "theatre", "theater", "studio", "graphic"), ["Creative & Design", "Marketing"]),
    (("engineering",), ["Software & IT", "Research"]),
]

WORK_TYPE_WORDS = {"remote": ["remote", "from home", "wfh", "online", "virtual"],
                   "hybrid": ["hybrid"],
                   "on-site": ["on-site", "onsite", "in person", "in-person", "near campus", "on campus", "tallahassee"]}
KIND_WORDS = {"internship": ["intern", "internship", "co-op"], "part-time": ["part-time", "part time", "flexible hours", "evenings", "weekends"],
              "full-time": ["full-time", "full time", "new grad", "entry-level", "entry level"], "on-campus": ["on campus", "on-campus", "work-study", "work study"]}

_STOP = set("""a an the and or for to of in on at with from by i im i'm me my we our you your find show get looking look want need
jobs job any some something that this those these is are be can could would like please roles role position positions work working
opportunities opportunity near around under over about good best new latest open openings hiring help me what which who where how
do does using use used also just really kind type sort some part time full remote hybrid onsite on-site person campus internship internships intern interns""".split())


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for canon, phrases in SKILLS.items():
        alts = sorted({p.lower() for p in phrases + [canon.lower()] if p}, key=len, reverse=True)
        if canon in ("R", "Go"):
            alts = [a for a in alts if a not in ("r", "go")]
        body = "|".join(re.escape(a) for a in alts)
        out.append((canon, re.compile(r"(?<![\w+#.])(?:" + body + r")(?![\w+#])", re.IGNORECASE)))
    return out


def extract_skills(text: str) -> list[str]:
    """Canonical skills found in text, in order of first appearance."""
    text = text or ""
    found = []
    for canon, pat in _patterns():
        m = pat.search(text)
        if m:
            found.append((m.start(), canon))
    return [c for _, c in sorted(found)]


def normalize_skill(value: str) -> str | None:
    """A typed skill -> canonical name when we know it, else the cleaned text (title-cased lightly)."""
    v = re.sub(r"\s+", " ", (value or "").strip())[:40]
    if not v:
        return None
    hits = extract_skills(v)
    if hits and len(v) <= 30:
        return hits[0]
    return v


def categories_for_major(major: str) -> list[str]:
    m = (major or "").lower()
    out: list[str] = []
    for keys, cats in MAJOR_HINTS:
        if any(k in m for k in keys):
            out += [c for c in cats if c not in out]
    return out


def profile_skillset(profile: dict | None) -> set[str]:
    if not profile:
        return set()
    skills = {s for s in (profile.get("skills") or []) if isinstance(s, str)}
    skills |= set(extract_skills(profile.get("resume_text", "")))
    skills |= set(extract_skills(profile.get("headline", "") + " " + profile.get("bio", "")))
    return skills


def parse_query(text: str) -> dict:
    """What someone typed to the assistant -> filters. Keeps it literal and predictable."""
    t = " " + (text or "").lower() + " "
    work_type = next((wt for wt, words in WORK_TYPE_WORDS.items() if any(w in t for w in words)), "")
    kinds = [k for k, words in KIND_WORDS.items() if any(w in t for w in words)]
    category = ""
    best = 0
    for cat, words in CATEGORY_WORDS.items():
        n = sum(1 for w in words if w in t)
        if n > best:
            best, category = n, cat
    skills = extract_skills(text)
    words = [w for w in re.findall(r"[a-z][a-z+#.\-]{1,30}", t) if w not in _STOP]
    return {"work_type": work_type, "kinds": kinds, "category": category, "skills": skills, "keywords": words[:8]}


def _days_old(created_at: str) -> float:
    import datetime as dt
    try:
        then = dt.datetime.fromisoformat(created_at[:19])
    except (ValueError, TypeError):
        return 999
    return max(0.0, (dt.datetime.utcnow() - then).total_seconds() / 86400)


def rank_jobs(jobs: list[dict], profile: dict | None = None, query: str = "", limit: int = 10,
              strict_query: bool = True) -> list[dict]:
    """Score each job 0-100 for this person and query. Returns the best `limit`, each with reasons."""
    user_skills = profile_skillset(profile)
    interests = set((profile or {}).get("interests") or [])
    major_cats = set(categories_for_major((profile or {}).get("major", "")))
    pref_types = set((profile or {}).get("work_types") or [])
    pref_kinds = set((profile or {}).get("job_kinds") or [])
    q = parse_query(query) if query.strip() else None

    out = []
    for j in jobs:
        text = f"{j.get('title', '')}\n{j.get('description', '')}"
        low = " " + text.lower() + " "
        title_low = (j.get("title") or "").lower()
        job_skills = extract_skills(text)
        matched = [s for s in job_skills if s in user_skills]
        missing = [s for s in job_skills if s not in user_skills]
        reasons: list[str] = []
        score = 0.0

        if job_skills and user_skills:
            ratio = len(matched) / max(3, len(job_skills))
            score += 45 * min(1.0, ratio * 1.25)
            if matched:
                reasons.append("Uses your skills: " + ", ".join(matched[:4]))
        elif user_skills:
            score += 6
        if j.get("category") in interests:
            score += 15
            reasons.append(f"In {j['category']}, one of your interests")
        elif j.get("category") in major_cats:
            score += 8
            reasons.append(f"Fits your major ({profile.get('major')})")
        if pref_types and j.get("work_type") in pref_types:
            score += 10
            reasons.append(f"{j['work_type'].title()}, as you prefer")
        for kind in pref_kinds:
            if any(w in low for w in KIND_WORDS.get(kind, [])):
                score += 6
                reasons.append(f"{kind.replace('-', ' ').title()} role")
                break

        if q:
            hit_terms = []
            for w in q["keywords"]:
                if w in title_low:
                    score += 9; hit_terms.append(w)
                elif f" {w}" in low:
                    score += 3; hit_terms.append(w)
            for s in q["skills"]:
                if s in job_skills and s.lower() not in hit_terms:
                    score += 8; hit_terms.append(s)
            if q["category"] and j.get("category") == q["category"]:
                score += 10; hit_terms.append(q["category"])
            if q["work_type"]:
                if j.get("work_type") == q["work_type"]:
                    score += 10; hit_terms.append(q["work_type"])
                elif strict_query:
                    continue
            wrong_kind = False
            for kind in q["kinds"]:
                if any(w in low for w in KIND_WORDS[kind]):
                    score += 8; hit_terms.append(kind)
                elif strict_query and kind == "internship":
                    wrong_kind = True            # asked for internships; this isn't one
            if wrong_kind:
                continue
            if strict_query and (q["keywords"] or q["skills"] or q["category"]) and not hit_terms:
                continue
            if hit_terms:
                reasons.insert(0, "Matches “" + ", ".join(dict.fromkeys(hit_terms[:3])) + "”")

        score += 3 if j.get("scam_status") == "clear" else -4
        score += max(0.0, 5 - _days_old(j.get("created_at", "")) / 6)
        out.append({"job": j, "score": max(0, min(100, round(score))), "reasons": reasons[:3],
                    "matched": matched, "missing": missing[:6]})

    out.sort(key=lambda r: (r["score"], r["job"].get("created_at", "")), reverse=True)
    if profile and (profile.get("skills") or profile.get("resume_text") or profile.get("items")):
        # The whole-profile fit score (fit.py) is what students see; with no search words it also sets the order.
        import fit as _fit
        for r in out:
            f = _fit.fit_score(r["job"], profile)
            r["fit"] = {"score": f["score"], "label": f["label"]}
        if not q:
            out.sort(key=lambda r: (r["fit"]["score"], r["score"], r["job"].get("created_at", "")), reverse=True)
    return out[:limit]


def keyword_gap(resume_text: str, job_text: str) -> dict:
    """Which skills the job asks for that the resume shows, and which it doesn't."""
    job = extract_skills(job_text)
    have = set(extract_skills(resume_text))
    present = [s for s in job if s in have]
    missing = [s for s in job if s not in have]
    pct = round(100 * len(present) / len(job)) if job else 0
    return {"job_skills": job, "present": present, "missing": missing, "match_pct": pct}
