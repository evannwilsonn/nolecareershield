"""
The detector's defenses beyond wording: what scammers can't cheaply change, and early warning when tactics shift.

  * Identifier memory: emails, phone numbers, domains, Telegram/WhatsApp contacts, $cashtags and crypto wallets pulled
    from every sent-in check. Once a reviewer confirms a scam, any new message that reuses one is flagged at once,
    before any retrain. Identifiers are stored as keyed HMACs with a masked display form, never in the clear.
  * Scam rings: reports that share identifiers are joined (union-find), so a new report that attaches to a ring of
    confirmed scams inherits that context even when its text is new. Very common identifiers are ignored.
  * Peer sharing: with SHARE_HMAC_KEY set (a key shared only with partner schools), confirmed identifiers are
    published as HMACs at /api/indicators and partners' feeds (PEER_FEEDS) are imported daily.
  * Clone detection: a listing or message that near-copies an approved NoleCareerShield listing but changes how to
    apply is the "real job, swapped contact" scam. Board listings also carry an invisible per-listing fingerprint so a
    copy pasted back into the checker names its source.
  * Outside intelligence (scam_detector/intel): FSU and employer lookalike domains, domain age, SPF/DMARC, link
    shorteners, and optional URLhaus, Spamhaus DQS, Chainabuse and Twilio lookups (each off until its key is set).
    Network checks run only when INTEL_NETWORK=1 (default on in production), results cached in SQLite.
  * Drift alerts: confirmed scams the rules missed, waves the rules don't catch, AI-only and ask-only catches rising
    against their baseline, and new lookalike certificates. Shown on the reviewer Intel page.
  * Campus risk calendar: windows when student job scams peak (semester starts, tax season, internship season).
  * Outside archives: university phishing-archive RSS feeds (ARCHIVE_FEEDS) land in the label queue for review.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import store
from scam_detector.intel import domains as intel_domains
from scam_detector.intel.findings import intel_findings
from scam_detector.rules import FREE_MAIL

log = logging.getLogger("nolecareershield.defense")

SCHEMA = """
CREATE TABLE IF NOT EXISTS check_indicators (check_id INTEGER NOT NULL, hash TEXT NOT NULL, kind TEXT NOT NULL, shown TEXT NOT NULL,
    peer_hash TEXT, PRIMARY KEY (check_id, hash));
CREATE INDEX IF NOT EXISTS ix_check_indicators_hash ON check_indicators(hash);
CREATE TABLE IF NOT EXISTS job_indicators (job_id INTEGER NOT NULL, hash TEXT NOT NULL, kind TEXT NOT NULL, shown TEXT NOT NULL,
    peer_hash TEXT, PRIMARY KEY (job_id, hash));
CREATE TABLE IF NOT EXISTS peer_indicators (hash TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT '', source TEXT NOT NULL, seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS intel_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS detector_stats (day TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, metric));
CREATE TABLE IF NOT EXISTS risk_windows (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, start_md TEXT NOT NULL,
    end_md TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS ct_lookalikes (domain TEXT PRIMARY KEY, brand TEXT NOT NULL, reason TEXT NOT NULL, first_seen TEXT NOT NULL,
    found_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS feed_items (link TEXT PRIMARY KEY, source TEXT NOT NULL, fetched_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS defense_runs (job TEXT PRIMARY KEY, last_run REAL NOT NULL, detail TEXT NOT NULL DEFAULT '');
"""

# Rough windows when scams aimed at students peak. Month-day, recurring every year; reviewers can edit them.
DEFAULT_WINDOWS = [
    ("Fall semester start", "08-10", "09-20", "New campus jobs and first paychecks: fake assistant and 'boss' gift-card scams peak."),
    ("Spring semester start", "01-03", "02-05", "Returning students look for spring jobs and research positions."),
    ("Tax season", "01-15", "04-15", "Fake payroll and W-2 requests, 'direct deposit setup' identity grabs."),
    ("Internship search", "02-15", "05-15", "Summer internship offers without interviews; fake onboarding forms."),
    ("Winter break", "12-10", "01-05", "Remote 'holiday' gigs, reshipping and package-inspector jobs."),
]

COMMON_DOMAINS = set(FREE_MAIL) | {
    "google.com", "gmail.com", "zoom.us", "calendly.com", "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "joinhandshake.com", "microsoft.com", "outlook.com", "office.com", "teams.microsoft.com", "fsu.edu", "my.fsu.edu",
    "t.me", "wa.me", "whatsapp.com", "telegram.org", "bit.ly", "tinyurl.com", "docs.google.com", "forms.gle", "youtube.com",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "apple.com", "amazon.com", "paypal.com", "venmo.com",
    "cash.app", "zelle.com", "nolecareershield.com", "example.com", "example.org",
}
RING_MAX_DEGREE = 25              # an identifier shared by more reports than this is infrastructure, not a crew


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM risk_windows").fetchone()[0] == 0:
        conn.executemany("INSERT INTO risk_windows (name, start_md, end_md, note) VALUES (?,?,?,?)", DEFAULT_WINDOWS)


# ---------- keys ----------

def _local_key() -> bytes:
    k = os.environ.get("INDICATOR_KEY") or ("indicators:" + os.environ.get("SECRET_KEY", "dev-only-secret"))
    return k.encode()


def _share_key() -> bytes | None:
    k = os.environ.get("SHARE_HMAC_KEY", "")
    return k.encode() if k else None


def _h(key: bytes, kind: str, value: str) -> str:
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


# ---------- identifier extraction ----------

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+", re.I)
_PHONE = re.compile(r"(?<![\d$])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9-]{2,63}(?:\.[a-z0-9-]{2,63})*\.(?:com|net|org|io|co|info|biz|xyz|top|online|site|club|us|app|live|shop|work|jobs|careers)\b(?:/[^\s<>\"')\]]*)?", re.I)
_TELEGRAM = re.compile(r"\bt\.me/([A-Za-z0-9_]{4,32})|(?:telegram|tg)[^\n@]{0,40}@([A-Za-z0-9_]{4,32})", re.I)
_WHATSAPP = re.compile(r"\bwa\.me/\+?(\d{10,15})", re.I)
_CASHTAG = re.compile(r"(?:cash\.app/|cash\s*app[^\n$]{0,40})\$([A-Za-z][A-Za-z0-9_]{2,19})", re.I)
_ETH = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC_BECH = re.compile(r"\bbc1[ac-hj-np-z02-9]{25,62}\b")
_BTC_LEGACY = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
_TRON = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
_CRYPTO_CONTEXT = re.compile(r"bitcoin|btc|crypto|wallet|usdt|tether|coinbase|blockchain", re.I)


def _mask_email(e: str) -> str:
    local, _, dom = e.partition("@")
    return f"{local[:2]}***@{dom}"


def extract(text: str) -> list[dict]:
    """[{kind, value (normalized), shown (masked)}], de-duplicated. Common platforms and free-mail domains are skipped."""
    text = unicodedata.normalize("NFKC", text or "")[:20000]
    out: dict[tuple, dict] = {}

    def add(kind, value, shown):
        out.setdefault((kind, value), {"kind": kind, "value": value, "shown": shown})

    emails = [m.group(0).lower().rstrip(".") for m in _EMAIL.finditer(text)]
    for e in emails:
        if not e.startswith(("noreply@", "no-reply@", "donotreply@")):
            add("email", e, _mask_email(e))
    for m in _PHONE.finditer(text):
        d = "".join(m.groups())
        if d[:3] not in ("555",) and not d.startswith("800"):
            add("phone", "+1" + d, f"***-***-{d[-4:]}")
    for m in _WHATSAPP.finditer(text):
        d = m.group(1)[-10:]
        add("phone", "+1" + d if len(m.group(1)) <= 11 else "+" + m.group(1), f"***-***-{d[-4:]}")
    email_domains = {e.split("@", 1)[1] for e in emails}
    for m in _URL.finditer(text):
        raw = m.group(0).lower()
        host = re.sub(r"^(?:https?://)?(?:www\.)?", "", raw).split("/", 1)[0].split(":", 1)[0].strip(".")
        if not host or "@" in host:
            continue
        reg = intel_domains.registrable_domain(host)
        if reg and reg not in COMMON_DOMAINS and host not in COMMON_DOMAINS and not reg.endswith((".gov", ".mil", ".edu")):
            add("domain", reg, reg)
    for d in email_domains:
        reg = intel_domains.registrable_domain(d)
        if reg and reg not in COMMON_DOMAINS and not reg.endswith((".gov", ".mil", ".edu")):
            add("domain", reg, reg)
    for m in _TELEGRAM.finditer(text):
        h = (m.group(1) or m.group(2) or "").lower()
        if h:
            add("telegram", h, f"@{h[:3]}***")
    for m in _CASHTAG.finditer(text):
        h = m.group(1).lower()
        add("cashtag", h, f"${h[:2]}***")
    has_crypto_ctx = bool(_CRYPTO_CONTEXT.search(text))
    for rx, need_ctx in ((_ETH, False), (_BTC_BECH, False), (_TRON, True), (_BTC_LEGACY, True)):
        if need_ctx and not has_crypto_ctx:
            continue
        for m in rx.finditer(text):
            w = m.group(0)
            add("wallet", w, f"{w[:6]}…{w[-4:]}")
    return list(out.values())


def hashes(items: list[dict]) -> list[dict]:
    lk, sk = _local_key(), _share_key()
    return [{**i, "hash": _h(lk, i["kind"], i["value"]), "peer_hash": _h(sk, i["kind"], i["value"]) if sk else None} for i in items]


def index_check(conn, check_id: int, text: str) -> None:
    for i in hashes(extract(text)):
        conn.execute("INSERT OR IGNORE INTO check_indicators (check_id, hash, kind, shown, peer_hash) VALUES (?,?,?,?,?)",
                     (check_id, i["hash"], i["kind"], i["shown"], i["peer_hash"]))


def index_job(conn, job_id: int, text: str) -> None:
    for i in hashes(extract(text)):
        conn.execute("INSERT OR IGNORE INTO job_indicators (job_id, hash, kind, shown, peer_hash) VALUES (?,?,?,?,?)",
                     (job_id, i["hash"], i["kind"], i["shown"], i["peer_hash"]))


def _confirmed(conn) -> dict:
    """hash -> {kind, shown, scam, legit, peer_hash} from reviewer-confirmed sent-in checks and board listings."""
    out: dict = {}
    q = """SELECT ci.hash, ci.kind, ci.shown, ci.peer_hash, sc.review_label AS label FROM check_indicators ci
           JOIN submitted_checks sc ON sc.id = ci.check_id WHERE sc.review_label IN ('scam','legit')
           UNION ALL SELECT ji.hash, ji.kind, ji.shown, ji.peer_hash, j.review_label FROM job_indicators ji
           JOIN jobs j ON j.id = ji.job_id WHERE j.review_label IN ('scam','legit')"""
    for r in store.rows(conn, q):
        d = out.setdefault(r["hash"], {"kind": r["kind"], "shown": r["shown"], "scam": 0, "legit": 0, "peer_hash": r["peer_hash"]})
        d[r["label"]] += 1
    return out


def known_bad(conn, items: list[dict]) -> list[dict]:
    """Identifiers in `items` that reviewers have confirmed in scams (and never in a legit item)."""
    if not items:
        return []
    marks = ",".join("?" * len(items))
    rows = store.rows(conn, f"""SELECT ci.hash, SUM(sc.review_label = 'scam') AS scam, SUM(sc.review_label = 'legit') AS legit
                                 FROM check_indicators ci JOIN submitted_checks sc ON sc.id = ci.check_id
                                 WHERE ci.hash IN ({marks}) GROUP BY ci.hash""", tuple(i["hash"] for i in items))
    rows += store.rows(conn, f"""SELECT ji.hash, SUM(j.review_label = 'scam') AS scam, SUM(j.review_label = 'legit') AS legit
                                  FROM job_indicators ji JOIN jobs j ON j.id = ji.job_id
                                  WHERE ji.hash IN ({marks}) GROUP BY ji.hash""", tuple(i["hash"] for i in items))
    tally: dict = {}
    for r in rows:
        t = tally.setdefault(r["hash"], [0, 0])
        t[0] += r["scam"] or 0
        t[1] += r["legit"] or 0
    return [{**i, "scams": tally[i["hash"]][0]} for i in items if i["hash"] in tally and tally[i["hash"]][0] > 0 and tally[i["hash"]][1] == 0]


def peer_hits(conn, items: list[dict]) -> list[dict]:
    hs = [i for i in items if i.get("peer_hash")]
    if not hs:
        return []
    marks = ",".join("?" * len(hs))
    found = {r["hash"]: r["source"] for r in store.rows(conn, f"SELECT hash, source FROM peer_indicators WHERE hash IN ({marks})",
                                                          tuple(i["peer_hash"] for i in hs))}
    return [{**i, "source": found[i["peer_hash"]]} for i in hs if i["peer_hash"] in found]


# ---------- scam rings ----------

def rings(conn, days: int = 180) -> dict:
    """check_id -> ring id (smallest check id in the component), over reports that share identifiers."""
    rows = store.rows(conn, """SELECT ci.check_id, ci.hash FROM check_indicators ci JOIN submitted_checks sc ON sc.id = ci.check_id
                               WHERE sc.created_at > ?""", (time.time() - days * 86400,))
    by_hash: dict = {}
    for r in rows:
        by_hash.setdefault(r["hash"], set()).add(r["check_id"])
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for ids in by_hash.values():
        if 2 <= len(ids) <= RING_MAX_DEGREE:
            ids = sorted(ids)
            for other in ids[1:]:
                a, b = find(ids[0]), find(other)
                if a != b:
                    parent[max(a, b)] = min(a, b)
    comp: dict = {}
    for x in list(parent):
        comp.setdefault(find(x), []).append(x)
    return {x: min(members) for members in comp.values() if len(members) > 1 for x in members}


def ring_summary(conn, check_id: int, ring_map: dict | None = None) -> dict | None:
    rm = ring_map if ring_map is not None else rings(conn)
    rid = rm.get(check_id)
    if rid is None:
        return None
    members = [k for k, v in rm.items() if v == rid]
    marks = ",".join("?" * len(members))
    labels = {r[0]: r[1] for r in conn.execute(f"SELECT review_label, COUNT(*) FROM submitted_checks WHERE id IN ({marks}) "
                                                "AND review_label IS NOT NULL GROUP BY review_label", tuple(members))}
    return {"ring": rid, "size": len(members), "labels": labels}


# ---------- style links (weak: only between confirmed scams) ----------

_FUNCTION = ("kindly", "dear", "regards", "revert", "do the needful", "at your earliest", "urgently", "hello there",
             "good day", "god bless", "stay safe", "as soon as possible", "i will", "you will", "get back to me")


def style_vector(text: str) -> dict:
    t = re.sub(r"\s+", " ", (text or "").lower())[:4000]
    grams: dict = {}
    for i in range(len(t) - 3):
        g = t[i:i + 4]
        grams[g] = grams.get(g, 0) + 1
    for w in _FUNCTION:
        if w in t:
            grams["fw:" + w] = grams.get("fw:" + w, 0) + 3
    return grams


def cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# ---------- clones of approved listings, and listing fingerprints ----------

_ZW = {"0": "​", "1": "‌"}
_ZW_REV = {v: k for k, v in _ZW.items()}
_ZW_MARK = "⁠"
_ZW_FIND = re.compile("⁠([​‌]{8,40})⁠")


def fingerprint(job_id: int) -> str:
    """An invisible marker that names the listing, inserted into its public description (word joiner + zero-width bits)."""
    bits = format(int(job_id), "b").zfill(16)
    return _ZW_MARK + "".join(_ZW[b] for b in bits) + _ZW_MARK


def with_fingerprint(description: str, job_id: int) -> str:
    d = description or ""
    cut = d.find(". ")
    cut = cut + 1 if 0 < cut < 400 else min(len(d), 120)
    return d[:cut] + fingerprint(job_id) + d[cut:]


def read_fingerprint(text: str) -> int | None:
    m = _ZW_FIND.search(text or "")
    if not m:
        return None
    try:
        return int("".join(_ZW_REV[c] for c in m.group(1)), 2)
    except (KeyError, ValueError):
        return None


def strip_fingerprints(text: str) -> str:
    return _ZW_FIND.sub("", text or "")


def _shingles(text: str) -> set:
    t = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(t[i:i + 3]) for i in range(max(1, len(t) - 2))}


def _contacts(text: str) -> set:
    return {i["value"] for i in extract(text) if i["kind"] in ("email", "phone", "domain", "telegram")}


def clone_findings(conn, text: str, url: str = "", exclude_job: int | None = None) -> list[dict]:
    out = []
    fp = read_fingerprint(text)
    body = strip_fingerprints(text)
    sh = _shingles(body)
    if len(sh) < 12 and fp is None:
        return out
    theirs = _contacts(body + " " + (url or ""))
    best = None
    jobs = store.rows(conn, "SELECT id, title, company, description, apply_url, contact FROM jobs WHERE review_status = 'approved' "
                            "ORDER BY id DESC LIMIT 600")
    for j in jobs:
        if exclude_job and j["id"] == exclude_job:
            continue
        js = _shingles(j["description"])
        inter = len(sh & js)
        if not inter:
            continue
        sim = inter / min(len(sh), len(js))
        if sim >= 0.5 and (best is None or sim > best[0]):
            best = (sim, j)
    if fp is not None:
        j = next((x for x in jobs if x["id"] == fp), None) or store.row(conn, "SELECT id, title, company, description, apply_url, contact FROM jobs WHERE id = ?", (fp,))
        if j:
            best = (1.0, j)
    if best:
        j = best[1]
        real = _contacts(f"{j['description']} {j['apply_url'] or ''} {j['contact'] or ''}")
        swapped = theirs - real
        if swapped:
            out.append({"rule_id": "cloned_listing", "severity": "critical", "weight": 35,
                        "title": "A copy of a real listing with different contact details",
                        "why": (f"This matches the approved listing “{j['title']}” at {j['company']} on NoleCareerShield, but it tells you "
                                "to apply or reply somewhere else. Scammers copy real jobs and swap in their own contact. Apply only "
                                "through the original listing."),
                        "matched": sorted(s for s in swapped)[:3]})
        elif fp is not None:
            out.append({"rule_id": "copied_from_board", "severity": "note", "weight": 0,
                        "title": "Copied from a NoleCareerShield listing",
                        "why": f"This text came from the listing “{j['title']}” at {j['company']}. Apply through that listing.",
                        "matched": []})
    return out


# ---------- the extra findings every check gets ----------

class SqliteCache:
    """The intel cache, in the site's database (duck-typed like scam_detector.intel.cache.MemoryCache)."""

    def get(self, key):
        with store.db() as conn:
            r = conn.execute("SELECT value, expires FROM intel_cache WHERE key = ?", (key,)).fetchone()
        if r and r[1] > time.time():
            return json.loads(r[0])
        return None

    def set(self, key, value, ttl_seconds):
        with store.db() as conn:
            conn.execute("INSERT OR REPLACE INTO intel_cache (key, value, expires) VALUES (?,?,?)",
                         (key, json.dumps(value), time.time() + ttl_seconds))


def network_on() -> bool:
    v = os.environ.get("INTEL_NETWORK", "")
    if v:
        return v.lower() in ("1", "true", "yes", "on")
    return os.environ.get("ENV", "").lower() == "production"


def employer_domains(conn) -> list[str]:
    """Domains of approved employers, protected against lookalikes."""
    out = set()
    for r in store.rows(conn, "SELECT website, u.email FROM employer_profiles p JOIN users u ON u.id = p.user_id WHERE p.status = 'approved'"):
        for v in (r["website"] or "", (r["email"] or "").split("@")[-1]):
            host = re.sub(r"^(?:https?://)?(?:www\.)?", "", v.lower()).split("/", 1)[0]
            reg = intel_domains.registrable_domain(host) if host else ""
            if reg and reg not in COMMON_DOMAINS:
                out.add(reg)
    return sorted(out)


def extra_findings(text: str, *, sender: str = "", title: str = "", company: str = "", url: str = "",
                   exclude_job: int | None = None) -> list[dict]:
    """Findings from identifiers, clones and outside intelligence. Never raises."""
    full = "\n".join(x for x in (title, company, text, sender, url) if x)
    out: list[dict] = []
    try:
        items = hashes(extract(full))
        with store.db() as conn:
            bad = known_bad(conn, items)
            peers = peer_hits(conn, items) if _share_key() else []
            out += clone_findings(conn, full, url, exclude_job)
            protected = employer_domains(conn)
            watch = {r["domain"] for r in store.rows(conn, "SELECT domain FROM ct_lookalikes")}
        if bad:
            out.append({"rule_id": "known_scam_identifier", "severity": "critical", "weight": 40,
                        "title": "Uses contact details from confirmed scams",
                        "why": ("Our reviewers confirmed scams that used "
                                + ", ".join(f"this {b['kind']}" for b in bad[:3])
                                + ". Scammers rewrite their messages, but they reuse their numbers, addresses and wallets."),
                        "matched": [b["shown"] for b in bad[:4]]})
        if peers:
            out.append({"rule_id": "peer_reported_identifier", "severity": "warning", "weight": 25,
                        "title": "Reported as a scam at another school",
                        "why": "A partner school's confirmed scam reports include " + ", ".join(f"this {p['kind']}" for p in peers[:3]) + ".",
                        "matched": [p["shown"] for p in peers[:4]]})
        urls = [u for u in [url] if u]
        found = intel_findings(full, urls, sender, company, cache=SqliteCache(), protected_extra=tuple(protected), network=network_on())
        for f in found:
            if f["rule_id"] == "lookalike_domain" and any(m in watch for m in f.get("matched", [])):
                f["why"] += " It also appeared in public certificate logs we watch for FSU look-alikes."
        out += found
    except Exception:                                   # noqa: BLE001 - extra checks must never break a scam check
        log.exception("extra findings failed")
    return out


# ---------- counters, drift alerts and the campus calendar ----------

def bump(metric: str, n: int = 1) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        with store.db() as conn:
            conn.execute("INSERT INTO detector_stats (day, metric, n) VALUES (?,?,?) ON CONFLICT(day, metric) DO UPDATE SET n = n + ?",
                         (day, metric, n, n))
    except Exception:                                   # noqa: BLE001
        log.exception("stat bump failed")


def _stat(conn, metric: str, since_days: int, until_days: int = 0) -> int:
    a = time.strftime("%Y-%m-%d", time.gmtime(time.time() - since_days * 86400))
    b = time.strftime("%Y-%m-%d", time.gmtime(time.time() - until_days * 86400))
    return conn.execute("SELECT COALESCE(SUM(n), 0) FROM detector_stats WHERE metric = ? AND day > ? AND day <= ?", (metric, a, b)).fetchone()[0]


def active_windows(conn, when: float | None = None) -> list[dict]:
    md = time.strftime("%m-%d", time.gmtime(when or time.time()))
    out = []
    for r in store.rows(conn, "SELECT * FROM risk_windows ORDER BY start_md"):
        s, e = r["start_md"], r["end_md"]
        if (s <= md <= e) if s <= e else (md >= s or md <= e):
            out.append(dict(r))
    return out


def alerts(conn) -> list[dict]:
    """What a reviewer should know this week: signs the detector is falling behind a new tactic."""
    out = []
    missed = store.rows(conn, """SELECT id, title, body FROM submitted_checks WHERE review_label = 'scam' AND band IN ('clear','caution','')
                                 AND reviewed_at > ? ORDER BY reviewed_at DESC""", (time.time() - 14 * 86400,))
    if len(missed) >= 3:
        out.append({"level": "bad", "title": f"{len(missed)} confirmed scams got past the rules in the last two weeks",
                    "detail": "That's usually a new tactic. Read them together and draft a rule "
                              "(python -m scam_detector.tools.mine_candidates), then run the regression gate.",
                    "ids": [m["id"] for m in missed[:10]]})
    waves = store.rows(conn, """SELECT COALESCE(campaign, id) AS w, COUNT(*) AS n, MIN(title) AS title, MIN(body) AS body
                                FROM submitted_checks WHERE created_at > ? AND band IN ('clear','caution','')
                                GROUP BY COALESCE(campaign, id) HAVING n >= 3 ORDER BY n DESC""", (time.time() - 30 * 86400,))
    for w in waves[:3]:
        out.append({"level": "warn", "title": f"A wave of {w['n']} near-copies that the rules call safe or only 'careful'",
                    "detail": (w["title"] or w["body"] or "")[:160], "ids": []})
    for metric, label in (("ai_only_scam", "the AI called a scam but no rule did"),
                          ("ask_only_scam", "a money ask was found but no rule fired"),
                          ("known_identifier", "reused a confirmed scammer's contact details")):
        recent, base = _stat(conn, metric, 7), _stat(conn, metric, 35, 7) / 4
        if recent >= 3 and recent >= 2 * max(base, 1):
            out.append({"level": "warn", "title": f"{recent} checks this week where {label} (usual: about {base:.0f} a week)",
                        "detail": "Rising counts here mean scammers are using wording the rules don't know yet.", "ids": []})
    unc_recent, checks_recent = _stat(conn, "model_uncertain", 7), _stat(conn, "listing_checks", 7)
    unc_base, checks_base = _stat(conn, "model_uncertain", 35, 7), _stat(conn, "listing_checks", 35, 7)
    if checks_recent >= 20 and checks_base >= 40:
        r1, r0 = unc_recent / checks_recent, unc_base / checks_base
        if r1 >= 0.15 and r1 >= 2 * r0:
            out.append({"level": "warn", "title": f"The model is unsure about {r1:.0%} of listings this week (usual {r0:.0%})",
                        "detail": "More uncertain cases usually means the kind of listings being checked has changed.", "ids": []})
    ct = store.rows(conn, "SELECT domain, brand FROM ct_lookalikes WHERE found_at > ? ORDER BY found_at DESC LIMIT 5", (time.time() - 7 * 86400,))
    if ct:
        out.append({"level": "bad", "title": f"{len(ct)} new look-alike domain{'s' if len(ct) != 1 else ''} in certificate logs",
                    "detail": ", ".join(f"{c['domain']} ({c['brand']})" for c in ct), "ids": []})
    for w in active_windows(conn):
        out.append({"level": "info", "title": f"Scam season: {w['name']}", "detail": w["note"], "ids": []})
    return out


# ---------- scheduled jobs: certificate watch, peer feeds, archive feeds ----------

def _due(conn, job: str, hours: float) -> bool:
    r = conn.execute("SELECT last_run FROM defense_runs WHERE job = ?", (job,)).fetchone()
    return not r or time.time() - r[0] >= hours * 3600


def _ran(job: str, detail: str) -> None:
    with store.db() as conn:
        conn.execute("INSERT OR REPLACE INTO defense_runs (job, last_run, detail) VALUES (?,?,?)", (job, time.time(), detail[:500]))


def ct_watch_job(fetch=None) -> str:
    from scam_detector.intel.ct_watch import find_new_lookalike_certs
    with store.db() as conn:
        extra = employer_domains(conn)
        last = conn.execute("SELECT MAX(found_at) FROM ct_lookalikes").fetchone()[0] or time.time() - 14 * 86400
    res = find_new_lookalike_certs(["fsu", "seminole", "noles", "floridastate"], last - 86400, fetch=fetch, extra=tuple(extra))
    new = 0
    with store.db() as conn:
        for d in res.get("domains", []):
            cur = conn.execute("INSERT OR IGNORE INTO ct_lookalikes (domain, brand, reason, first_seen, found_at) VALUES (?,?,?,?,?)",
                               (d["domain"], d.get("brand", ""), d.get("reason", ""), str(d.get("first_seen", "")), time.time()))
            new += cur.rowcount
    return f"{res.get('status')}: {new} new"


def peer_feed_job(client=None) -> str:
    feeds = [f for f in os.environ.get("PEER_FEEDS", "").split(",") if "|" in f]
    if not feeds or not _share_key():
        return "disabled"
    import httpx
    n = 0
    for f in feeds:
        url, key = f.split("|", 1)
        try:
            r = (client or httpx).get(url.strip(), headers={"X-Share-Key": key.strip()}, timeout=10)
            data = r.json() if r.status_code == 200 else {}
        except Exception:                               # noqa: BLE001
            continue
        with store.db() as conn:
            for it in (data.get("indicators") or [])[:20000]:
                h = str(it.get("hash", ""))
                if re.fullmatch(r"[0-9a-f]{64}", h):
                    conn.execute("INSERT OR REPLACE INTO peer_indicators (hash, kind, source, seen) VALUES (?,?,?,?)",
                                 (h, str(it.get("kind", ""))[:20], data.get("source", url)[:80], time.time()))
                    n += 1
    return f"{n} peer indicators"


def share_feed(conn) -> dict:
    items = [{"hash": d["peer_hash"], "kind": d["kind"]} for d in _confirmed(conn).values() if d["scam"] and not d["legit"] and d["peer_hash"]]
    return {"source": os.environ.get("SHARE_SOURCE_NAME", "NoleCareerShield (FSU)"), "generated": int(time.time()),
            "hash": "HMAC-SHA256(SHARE_HMAC_KEY, kind:value)", "indicators": items}


def _rss_items(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.split("}")[-1] == name), None)
        title = strip((get("title").text if get("title") is not None else ""))
        link_el = get("link")
        link = (link_el.get("href") or link_el.text or "") if link_el is not None else ""
        body_el = get("encoded") or get("description") or get("content") or get("summary")
        body = strip(body_el.text if body_el is not None else "")
        if link and body:
            out.append({"title": title[:200], "link": link.strip()[:500], "body": body[:8000]})
    return out


_JOBBY = re.compile(r"\b(job|position|hiring|assistant|weekly|salary|intern|employment|recruit|remote work|part[- ]time)\b", re.I)


def archive_feed_job(fetch=None) -> str:
    feeds = [f.strip() for f in os.environ.get("ARCHIVE_FEEDS", "").split(",") if f.strip()]
    if not feeds:
        return "disabled"
    import httpx
    import learning
    added = 0
    for url in feeds:
        try:
            text = fetch(url) if fetch else httpx.get(url, timeout=10, headers={"User-Agent": "NoleCareerShield archive reader"}).text
        except Exception:                               # noqa: BLE001
            continue
        for it in _rss_items(text):
            if not _JOBBY.search(it["title"] + " " + it["body"]):
                continue
            with store.db() as conn:
                if conn.execute("INSERT OR IGNORE INTO feed_items (link, source, fetched_at) VALUES (?,?,?)",
                                (it["link"], url[:200], time.time())).rowcount:
                    learning.add_submission(conn, body=it["body"], title=it["title"], kind="message", source="archive",
                                            url=it["link"], band="")
                    added += 1
    return f"{added} new archive items"


def daily_jobs() -> None:
    """Called by the maintenance loop; network jobs run in a background thread and at most once a day each."""
    if not (network_on() or os.environ.get("PEER_FEEDS") or os.environ.get("ARCHIVE_FEEDS")):
        return                                          # nothing configured: no thread at all

    def run():
        try:
            with store.db() as conn:
                ensure_schema(conn)
        except Exception:                               # noqa: BLE001
            log.exception("defense schema")
            return
        for job, hours, fn in (("ct_watch", 24, ct_watch_job), ("peer_feeds", 24, peer_feed_job), ("archives", 24 * 7, archive_feed_job)):
            try:
                with store.db() as conn:
                    if not _due(conn, job, hours):
                        continue
                if job == "ct_watch" and not network_on():
                    continue
                _ran(job, fn())
            except Exception as e:                      # noqa: BLE001
                log.exception("defense job %s failed", job)
                _ran(job, f"error: {e}")
    threading.Thread(target=run, daemon=True).start()
