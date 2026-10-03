# Field batch, October 2026 (collected Sept 30)

**Purpose:** real examples for the learned layer (see ../MODEL.md), especially legit jobs that quote weekly pay.
The first model had wrongly learned that weekly pay means scam.

## Collected
138 listings, all real and taken verbatim from the source page:
- **28 legit weekly-pay jobs:** summer camps, AmeriCorps/conservation corps, CDL drivers, travel nursing
  and allied health, internships with weekly stipends.
- **30 legit student-type jobs:** 12 have scam-like wording (remote, "no experience", mystery shopper,
  brand ambassador, research assistant, AI tutor). The rest are internships, campus jobs and Florida
  part-time jobs, from employer careers sites, university HR sites and LinkedIn.
- **37 scams:** published verbatim as scams by university phishing archives (Tulane, Toronto,
  UW-Madison, Syracuse, UMN, WashU, Pitt, Arizona, UVic, BU, Brown, UMich), the FTC, Nevada Consumer
  Affairs, the BBB, news sites and scam-tracking sites. Types: reshipping, fake check,
  mystery-shopper, car-wrap, task/app scams, fake recruiter texts, tutor overpayment and a Bitcoin-ATM
  "survey".
- **44 Craigslist and aggregator posts:** Florida Craigslist (19 legit, 5 scam) plus 20 lead-gen
  funnels (tracking redirects, "join for free", survey panels, commission-only pitches).

## Labeling
- Every row was labeled by hand against LABELING_RUBRIC.md before any detector run. Each row's `notes`
  holds the reason.
- One exact duplicate was dropped, leaving 138 rows: 77 legit, 42 scam, 19 lead-gen.
- Frozen in `field_2026_10.jsonl.sha256`.
- **Split:** 2/3 into `field_2026_10_tune.jsonl`, 1/3 into `field_2026_10_holdout.jsonl`, stratified
  by label, with near-copies (the three QY Shippers emails; the two Clubshop funnels) kept on one side.

## What the rules do on it (not tuned on it)

| | Rules alone |
|---|---|
| Scams caught | 16/42 |
| Legit wrongly flagged | 2/77 (GEICO customer service, KnowBe4 sales) |
| Lead-gen called scam | 0/19 |

That's much lower than the September batch's 35/42, which was measured after tuning on that batch.
16/42 is the honest generalization number for the rules on fresh text.

`weekly_stipend` fired on 18 legit jobs and 10 scams. It's a weak signal and shouldn't be weighted up.

**Not done here, on purpose:** rule changes. A rule round on the tune split, like September's, is the
next step for the rules. The two false alarms and the missed types (tutor overpayment, mystery-shopper
texts, account-lending, trading "analyst" with required purchases) are the obvious starting points.

## Limits
- **Uneven sourcing:** scams come mostly from archives and quoted texts, while legit rows come mostly
  from job pages. The model strips collection leftovers (headers, redaction marks) so it can't learn
  the source instead of the job.
- **Imbalance:** 13 of the 28 weekly-pay rows are outdoor or environmental education.
- **Truncation:** long listings were cut to their duties, pay, requirements and how to apply. Some join
  verbatim chunks with "[...]".

**Redacted 2026-10-03.** Personal email addresses (the part before the @) and phone numbers in this file were replaced with stand-ins (`personN@same-domain`, `555` numbers); role addresses like info@ were kept. Rule scores and bands are unchanged on every row and no model decision changed (probabilities moved by at most 0.003). The `.sha256` file now records the redacted file; the hash of the original, frozen before any detector run, was `a9d220a3344caea1358678ca961880c710ecce59e76a4c9cff1d58b39681727b`.
