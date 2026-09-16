"""
The scorer: combine text rules and enrichment into one auditable result.

Enrichment findings are added with deliberately modest weights, because a
lookup result is context, not proof:
  - a brand-new domain (< 90 days) on a claimed established employer is worth
    flagging, but startups have new domains too
  - a missing MX record on a recruiter's domain is a small note
  - pay well above the national median is a warning, not a conviction

The text rules stay the heaviest signals, because "asked me to deposit a check"
is far more diagnostic than "domain is 60 days old". Every weight here is a
starting hypothesis to be corrected by tools/evaluate.py against real labels.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import List, Optional

from .rules import Finding, run_text_rules, check_email_domains, extract_domains
from .enrichment.domain_age import lookup_domain_age
from .enrichment.mx_check import check_mx
from .enrichment.compensation import check_compensation
from .enrichment.url_flow import analyze_url_chain


@dataclass
class ScoreResult:
    score: int
    band: str                       # "block" | "review" | "caution" | "clear"
    verdict: str
    findings: List[dict] = field(default_factory=list)
    enrichment: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "score": self.score, "band": self.band, "verdict": self.verdict,
            "findings": self.findings, "enrichment": self.enrichment,
        }


def _band(score: int, has_critical: bool) -> tuple[str, str]:
    if has_critical or score >= 65:
        return "block", "Treat this as a scam. Don't send money, documents, or banking details."
    if score >= 35:
        return "review", "Several things don't add up. Verify the employer independently before replying."
    if score >= 15:
        return "caution", "A few things are worth checking. Confirm the company and role exist."
    return "clear", "Nothing matched a known pattern. Still verify the employer through their own site."


def _enrichment_findings(title: str, description: str, company: str,
                         full_text: str, run_network: bool) -> tuple[list[Finding], dict]:
    findings: List[Finding] = []
    enrichment: dict = {"domains": {}, "compensation": None}

    # Compensation is local (no network) — always run it.
    comp = check_compensation(title, description)
    enrichment["compensation"] = comp.as_dict()
    if comp.status == "flagged":
        findings.append(Finding(
            "pay_anomaly", "warning", 17, "The stated pay is out of band",
            comp.detail + ". Figures far above market for the described work are the hook.",
            [comp.detail],
        ))

    domains = extract_domains(full_text)
    if run_network and domains:
        # Run domain-age and MX lookups concurrently; they're independent network I/O.
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            age_futs = {pool.submit(lookup_domain_age, d): d for d in domains}
            mx_futs = {pool.submit(check_mx, d): d for d in domains}
            ages = {age_futs[f]: f.result() for f in concurrent.futures.as_completed(age_futs)}
            mxs = {mx_futs[f]: f.result() for f in concurrent.futures.as_completed(mx_futs)}

        for d in domains:
            age, mx = ages[d], mxs[d]
            enrichment["domains"][d] = {"age": age.as_dict(), "mx": mx.as_dict()}

            if age.status == "ok" and age.age_days is not None and age.age_days < 90:
                findings.append(Finding(
                    "new_domain", "warning", 16, "The contact domain is very new",
                    f"{d} was registered {age.age_days} days ago. Impersonation domains are "
                    f"registered cheaply and used quickly; a brand-new domain on a supposedly "
                    f"established employer is worth checking.",
                    [f"{d}: {age.detail}"],
                ))
            elif age.status == "ok" and age.age_days is None and "unregistered" in age.detail:
                findings.append(Finding(
                    "unregistered_domain", "warning", 20, "The contact domain isn't registered",
                    f"{d} does not appear in the domain registry at all — unusual for a real employer's link.",
                    [f"{d}: {age.detail}"],
                ))

            if mx.status in ("no_mx", "nxdomain"):
                findings.append(Finding(
                    "no_mail", "note", 8, "The contact domain can't receive email",
                    f"{d} {mx.detail}. A real employer's domain normally accepts mail.",
                    [f"{d}: {mx.detail}"],
                ))

    return findings, enrichment


CONTEXT_FLAGS = {
    # --- Connection / relationship signals ---
    "poster_distant_connection": ("note", 8, "Poster is a distant/no connection",
        "You reported the poster is a 2nd/3rd-degree or non-connection. Scam recruiters "
        "mass-contact strangers; weak alone, but it adds up with other signals."),

    # --- Account age and activity signals ---
    "recruiter_new_account": ("warning", 14, "Recruiter account looks new",
        "You reported the recruiter's account appears newly created. Fresh accounts are "
        "spun up in bulk for these operations."),
    "very_low_connections": ("warning", 18, "Recruiter has very few connections (under ~10)",
        "You reported the recruiter has almost no connections. A real professional -- even "
        "one who barely uses LinkedIn -- accumulates dozens from school, past jobs, and "
        "colleagues. Single-digit connections means the account was just created for this."),
    "low_connections": ("note", 8, "Recruiter has a thin connection count (under ~50)",
        "You reported the recruiter has relatively few connections. Not damning alone -- "
        "some real people are light LinkedIn users -- but it reduces the trust you'd "
        "normally give a recruiter profile."),

    # --- Profile quality signals ---
    "no_profile_photo": ("warning", 12, "No profile photo (default silhouette)",
        "You reported the recruiter has the default grey silhouette instead of a real "
        "photo. Legitimate recruiters almost always have a headshot -- their job depends "
        "on being approachable. A missing photo on a recruiter account is unusual."),
    "stock_photo_face": ("warning", 14, "Profile photo looks like a stock image or AI-generated",
        "You reported the profile photo looks fake -- overly polished, AI-generated, or "
        "a stock headshot. Scam operations use generated faces to create accounts in bulk."),
    "thin_profile": ("warning", 11, "Profile has very little content",
        "You reported the recruiter's profile is bare -- no about section, no posts, "
        "minimal or no experience listed. A real recruiter's livelihood depends on their "
        "profile being filled out; an empty one signals an account created for a single purpose."),
    "no_activity_history": ("note", 9, "No posts, comments, or activity visible",
        "You reported the account has no visible activity -- no posts, no comments, "
        "no engagement. Real professionals accumulate some trail over time; a completely "
        "blank activity section suggests the account exists only to send messages."),

    # --- Company verification signals ---
    "no_company_page": ("warning", 12, "No real company page",
        "You reported the named employer has no or a thin company page. Real employers "
        "have an established presence."),
    "no_company_insights": ("warning", 13, "LinkedIn shows no quality data on the company",
        "You reported LinkedIn's Premium insights panel said there is not enough data on "
        "this company yet (fewer than 30 member profiles). Legitimate employers with real "
        "employees generate this data naturally."),
    "company_insights_present": ("note", -5, "LinkedIn shows full company insights",
        "You reported LinkedIn's insights panel has real hiring trends, employee count, "
        "and school data for this company. That is hard to fake and is a positive signal."),

    # --- Behavioral signals ---
    "name_company_mismatch": ("warning", 13, "Recruiter name doesn't match the company",
        "You reported the recruiter's name doesn't match the company they claim to "
        "represent -- common when one operation runs many fake recruiter accounts."),
    "dodged_verification": ("warning", 16, "Dodged a request to verify the employer",
        "You reported that when you asked for the official posting or company page, they "
        "evaded and pushed to move forward. Real recruiters can verify themselves."),
    "same_script_seen_before": ("warning", 18, "Identical message seen from other accounts",
        "You reported this exact message from other accounts/companies. A shared copy-paste "
        "script across different employers is a coordinated scam operation."),
    "duplicate_accounts": ("warning", 16, "Multiple accounts appear to be the same person or operation",
        "You reported that several recruiter accounts share the same script, employer "
        "name, or profile patterns. Coordinated account clusters are a hallmark of "
        "scam operations running at scale."),
}


def _context_flag_findings(flags):
    out = []
    for flag in flags:
        spec = CONTEXT_FLAGS.get(flag)
        if spec:
            sev, weight, title, why = spec
            out.append(Finding("ctx_" + flag, sev, weight, title, why, ["user-observed"]))
    return out


def score_posting(title: str, description: str, company: str = "",
                  run_network: bool = True, context_flags: list = None,
                  url_chain: list = None) -> ScoreResult:
    full_text = f"{title}\n{description}"

    findings = run_text_rules(full_text)
    findings += check_email_domains(full_text, company)
    enr_findings, enrichment = _enrichment_findings(title, description, company, full_text, run_network)
    findings += enr_findings

    # Combination boost: the money-mule recruitment scam is far more dangerous when
    # its parts appear together (banking/ID ask + off-platform pivot + recruitment
    # framing) than any single phrase. When two or more of these fire, add a
    # critical finding — the cluster is the signal, not the individual words.
    fired = {f.rule_id for f in findings}
    mule_parts = {"banking_pii", "mule_recruitment", "off_platform"}
    if len(fired & mule_parts) >= 2:
        findings.append(Finding(
            "mule_combo", "critical", 28,
            "Combined pattern: recruitment + banking/ID + off-platform",
            "This message combines a recruitment pitch, a request for banking or identity details, "
            "and a push to an outside app. Together these are the money-mule hiring scam — walk away.",
            ["multiple money-mule signals present together"],
        ))

    # Context flags the USER observed on the platform (not scraped). Each is a small
    # signal on its own; they raise suspicion, they don't convict alone.
    findings += _context_flag_findings(context_flags or [])

    # URL/flow signals from a chain the user actually followed (see enrichment/url_flow.py).
    findings += analyze_url_chain(url_chain or [], company)

    order = {"critical": 0, "warning": 1, "note": 2}
    findings.sort(key=lambda f: (order[f.severity], -f.weight))

    score = min(100, sum(f.weight for f in findings))
    has_critical = any(f.severity == "critical" for f in findings)
    band, verdict = _band(score, has_critical)

    return ScoreResult(
        score=score, band=band, verdict=verdict,
        findings=[f.as_dict() for f in findings], enrichment=enrichment,
    )
