"""
Text rule engine.

These are transparent, human-readable heuristics — the same signals from the
browser v1, ported to Python so the backend and any evaluation harness share one
source of truth. Each rule that fires produces a Finding with a severity, a short
title, an explanation, and the phrases that matched, so every score is auditable.

Weights are judgment, not evidence, until measured against a labeled corpus.
That measurement is the whole point of tools/evaluate.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Finding:
    rule_id: str
    severity: str      # "critical" | "warning" | "note"
    weight: int
    title: str
    why: str
    matched: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "severity": self.severity, "weight": self.weight,
            "title": self.title, "why": self.why, "matched": self.matched,
        }


# (rule_id, severity, weight, title, why, [phrases])
SIGNALS = [
    ("advance_fee", "critical", 30, "You're asked to pay something",
     "Legitimate employers never charge you to start work. The single most reliable scam marker.",
     ["training fee", "registration fee", "application fee", "processing fee", "onboarding fee",
      "background check fee", "starter kit", "pay for your own equipment", "purchase the equipment",
      "buy the software", "refundable deposit", "security deposit", "administrative fee", "certification fee",
      "check to purchase", "check for equipment", "check to buy", "funds to purchase", "money for equipment"]),
    ("money_mule", "critical", 34, "The job involves moving money or packages",
     "Depositing checks and forwarding funds, or reshipping parcels, is how stolen money and goods get laundered.",
     ["deposit the check", "cash the check", "cashier's check", "cashiers check", "forward the funds",
      "transfer the remaining", "wire the balance", "process payments on behalf", "receive packages",
      "reship", "package forwarding", "mystery shopper", "secret shopper", "money transfer agent"]),
    ("banking_pii", "critical", 26, "Banking or identity details wanted up front",
     "Account and identity details come after a signed offer, through payroll — never over chat during screening.",
     ["routing number", "bank account number", "voided check", "social security number", "your ssn",
      "driver's license number", "drivers license number", "copy of your id", "photo of your id",
      "direct deposit form"]),
    ("irreversible_pay", "critical", 24, "Payment through irreversible channels",
     "Gift cards, crypto, and peer-to-peer apps can't be reversed or traced. No payroll uses them.",
     ["bitcoin", "btc wallet", "usdt", "crypto wallet", "cryptocurrency", "gift card", "gift cards",
      "zelle", "cash app", "cashapp", "venmo", "western union", "moneygram"]),
    ("off_platform", "warning", 17, "Pushed onto a messaging app",
     "Moving to an unmonitored app right away avoids platform fraud detection and leaves no record.",
     ["telegram", "whatsapp", "google hangouts", "signal app", "wickr", "skype id",
      "add me on", "message me at", "text me at", "dm me on",
      "microsoft teams", "teams contact", "teams email", "provide your teams",
      "teams app", "teams for direct communication", "teams for communication"]),
    ("text_interview", "warning", 15, "Interview by text only",
     "Scam operations avoid live video because they're using a stolen or invented identity.",
     ["chat interview", "text interview", "no video call", "interview through telegram",
      "interview via whatsapp", "written interview only"]),
    ("instant_hire", "warning", 16, "Hired with no real process",
     "An offer without an interview means nobody is assessing you. The goal is to reach the payment step fast.",
     ["you have been hired", "congratulations you are hired", "no interview required", "immediate hire",
      "hired on the spot", "your resume was selected", "we found your resume", "start immediately",
      "begin work today"]),
    ("pressure", "warning", 11, "Pressure to decide now",
     "Urgency is there to stop you checking. Real hiring runs on weeks, not hours.",
     ["limited positions", "limited slots", "act fast", "respond within 24 hours", "within the next hour",
      "first come first served", "offer expires", "urgent hiring", "urgently needed"]),
    ("too_good", "warning", 13, "High pay for very little",
     "Pay well above market for a role needing no experience is bait, not an opportunity.",
     ["no experience necessary", "no experience required", "no skills required", "anyone can do this",
      "work only 2 hours", "flexible hours high pay", "easy money", "guaranteed income", "earn while you learn"]),
    ("pay_to_work", "warning", 20, "The 'job' requires paying for training first",
     "A real internship or job pays you. If you must buy a course or 'training with a fee' to get the "
     "role, it's a course sale dressed as a job — the position is bait for the payment.",
     ["training with a fee", "training fee", "enroll in the program", "enroll for the program",
      "enroll here", "program fee", "paid training program", "training and internship program",
      "internship certificate", "letter of recommendation", "personal branding session",
      "resume building session"]),
    ("mule_recruitment", "warning", 22, "Bank account and ID wanted to 'receive payment'",
     "Being asked for a U.S. bank account and SSN to 'receive salary' before you know the job, company, "
     "or pay is the money-mule recruitment pattern — your account is used to move stolen funds.",
     ["bank account for payment", "receive salary payments", "receive payments through",
      "salary payments through a u.s. bank", "valid u.s. bank account", "us bank account for",
      "ssn for employment", "social security number for employment", "for employment eligibility",
      "assisting with its recruitment", "assisting with our recruitment", "recruitment process",
      "on behalf of our partner company", "not eligible to apply", "reply yes or apply",
      "reply i'm interested", "part-time recruiter"]),
    ("vague_employer", "note", 9, "The employer stays vague",
     "A real posting names the company and a real person. Anonymity here is deliberate.",
     ["confidential company", "our client is seeking", "a leading company", "reputable company seeking",
      "well known firm", "undisclosed company"]),
]

FREE_MAIL = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "protonmail.com",
    "proton.me", "mail.com", "yandex.com", "gmx.com", "icloud.com", "live.com", "msn.com",
}


def _escape(p: str) -> str:
    return re.escape(p).replace(r"\ ", r"\s+")


def run_text_rules(text: str) -> List[Finding]:
    findings: List[Finding] = []
    low = text
    for rule_id, sev, weight, title, why, phrases in SIGNALS:
        matched = []
        for p in phrases:
            if re.search(r"\b" + _escape(p) + r"\b", low, re.IGNORECASE):
                matched.append(p)
        if matched:
            findings.append(Finding(rule_id, sev, weight, title, why, sorted(set(matched))[:5]))
    return findings


def check_email_domains(text: str, company: str) -> List[Finding]:
    """Flag free-mail addresses used by a named corporate employer."""
    findings: List[Finding] = []
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text, re.IGNORECASE))
    domains = {e.split("@")[1].lower().rstrip(".,;:") for e in emails}
    free = sorted(d for d in domains if d in FREE_MAIL)
    if free and company.strip():
        findings.append(Finding(
            "personal_email", "warning", 18, "Recruiter writing from a personal address",
            f"Corporate hiring comes from the company's own domain. Nothing here comes from a "
            f"{company.strip()} address.",
            ["@" + d for d in free],
        ))
    return findings


def extract_domains(text: str) -> List[str]:
    """All distinct domains from emails and URLs, for enrichment lookups."""
    domains = set()
    for e in re.findall(r"[\w.+-]+@([\w-]+\.[\w.-]+)", text, re.IGNORECASE):
        domains.add(e.lower().rstrip(".,;:"))
    for u in re.findall(r"https?://(?:www\.)?([\w-]+\.[\w.-]+)", text, re.IGNORECASE):
        domains.add(u.lower().rstrip("/.,;:"))
    return sorted(d for d in domains if d not in FREE_MAIL)
