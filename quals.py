"""Employer-chosen qualifications: what a listing asks for, item by item.

Each item is {"kind", "label", "must"}; kind is one of skill, major, cert, standing, gradyear, gpa.
They feed fit.fit_score, so the match percentage and the "N of M met" checklist use exactly what
the employer chose (plus whatever the description parses to), never a guess about the person.
"""
from __future__ import annotations

import json
import re

KINDS = {"skill": "Skill", "major": "Major", "cert": "Certification", "standing": "Class standing",
         "gradyear": "Graduation year", "gpa": "Minimum GPA"}
STANDINGS = ["freshman", "sophomore", "junior", "senior", "graduate"]
MAX_ITEMS = 10
LABEL_LEN = 60
# Protected or demographic terms never belong in a qualification (also enforced on the free-text fields).
_BLOCKED = re.compile(r"\b(citizen(ship)?|visa|sponsorship|green ?card|age|years? old|young|gender|male|female|race|racial|ethnic\w*|"
                      r"religio\w*|christian|muslim|jewish|married|pregnan\w*|disabilit\w*|national origin|sexual|lgbt\w*)\b", re.IGNORECASE)


class QualError(ValueError):
    pass


def clean(raw) -> list[dict]:
    """Validate a list of items (or a JSON string) from a form. Raises QualError on anything not allowed."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    out, seen = [], set()
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "skill")
        label = re.sub(r"\s+", " ", str(it.get("label") or "")).strip()
        if not label:
            continue
        if kind not in KINDS:
            raise QualError("Unknown qualification type.")
        if len(label) > LABEL_LEN:
            raise QualError(f"Keep each qualification under {LABEL_LEN} characters.")
        if _BLOCKED.search(label):
            raise QualError("Qualifications can't ask about citizenship, age, gender, race, religion or similar. Keep them to skills, education and experience.")
        if kind == "standing":
            label = label.lower().rstrip("s")
            if label not in STANDINGS:
                raise QualError("Class standing must be freshman, sophomore, junior, senior or graduate.")
        elif kind == "gradyear":
            if not re.fullmatch(r"20\d\d", label):
                raise QualError("Graduation year must look like 2027.")
        elif kind == "gpa":
            try:
                label = f"{float(label):.1f}"
            except ValueError:
                raise QualError("GPA must be a number like 3.0.")
            if not 0 < float(label) <= 4.0:
                raise QualError("GPA must be between 0 and 4.0.")
        key = (kind, label.lower())
        if key in seen:
            continue
        seen.add(key)
        must = it.get("must") in (True, 1, "1", "on", "must", "true")
        out.append({"kind": kind, "label": label, "must": must})
    if len(out) > MAX_ITEMS:
        raise QualError(f"Up to {MAX_ITEMS} qualifications.")
    return out


def of(job) -> list[dict]:
    """The stored qualifications for a job row/dict ([] when none)."""
    raw = job.get("requirements") if hasattr(job, "get") else None
    if not raw:
        try:
            raw = job["requirements"]
        except (KeyError, IndexError, TypeError):
            raw = None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    return [q for q in (raw or []) if isinstance(q, dict) and q.get("kind") in KINDS and q.get("label")]


def describe(q: dict) -> str:
    k, l = q["kind"], q["label"]
    return {"major": f"{l} major", "standing": f"{l.title()} standing", "gradyear": f"Graduating {l}", "gpa": f"{l}+ GPA"}.get(k, l)
