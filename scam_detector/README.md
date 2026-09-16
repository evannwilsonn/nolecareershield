# Job Scam Detector

A job-posting scam detector that does the small honest version of the job:
transparent text rules plus real, legally-obtained enrichment, with an
evaluation harness so every claim about accuracy is a measured number.

No Kafka, no GPU, no honeypots, no scraping. One Python service you can run on a
laptop. It scales to the volume a job-scam tool actually sees, which is small.

## What it checks

**Text rules** (`rules.py`) — transparent phrase heuristics for the signals that
actually predict scams: advance fees, money-mule work, banking/PII requests up
front, irreversible payment channels, off-platform redirects, instant hires,
pressure tactics. Every rule that fires is reported with the phrase it matched,
so no score is a black box.

**Domain age** (`enrichment/domain_age.py`) — RDAP lookup (the modern JSON
successor to WHOIS). A brand-new domain on a supposedly established employer is
worth flagging. A failed lookup returns `unknown`, never `suspicious` — a
registrar timeout is not evidence of fraud.

**MX records** (`enrichment/mx_check.py`) — whether the contact domain can
receive mail at all. A small signal, weighted lightly.

**Compensation** (`enrichment/compensation.py`) — advertised pay vs. the BLS
national median for the occupation. `$45/hr` for data entry is ~2.5x median;
that ratio is the bait in most scams. National figures only, so this flags
"well above national median," not "above local market" — stated honestly in the
output.

## Run it

```bash
pip install -r requirements.txt

# HTTP API
uvicorn scam_detector.api:app --reload
curl -X POST http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"title":"Remote Data Entry","description":"Earn $45/hr...","company":"Acme"}'

# Evaluate against labeled data — THIS is the important command
python -m scam_detector.tools.evaluate data/labeled_seed.jsonl --threshold review
```

## The one thing that matters

The seed corpus (`data/labeled_seed.jsonl`) is 20 hand-written, deliberately
obvious examples. It scores a perfect F1, and that means **nothing** — the scam
examples contain the exact phrases the rules look for.

A real accuracy number requires real postings you did not write. See
`BUILDING_A_CORPUS.md`. Until you have that corpus and a measured
false-positive rate, you do not know whether this works, and neither does anyone
you'd pitch it to. That number is the whole product.

## What this is not

It is not a platform trust-and-safety system. It only uses what a job seeker can
see — posting text and public DNS/registry data. It has no access to account
histories, login IPs, or device fingerprints, so it can't do account-takeover or
graph analysis. That's a deliberate scope choice: this is a consumer-side tool
you can build, ship, and stand behind alone.
