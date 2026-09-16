# Building a real labeled corpus

This is the actual work. Everything else in this repo is ready; the corpus is
what turns it from a plausible-looking tool into a measured one. Budget a few
focused days, not a sprint.

## Target

Aim for ~150 scam and ~150 legitimate postings to start. Balanced classes,
real text, hand-labeled by you. That's enough to get a first honest
precision/recall number and to see where the detector fails. You can grow it
later; you cannot skip it.

## Where to get scam examples (all legal, all public)

- **r/scams and r/jobscams** — victims post full scam messages, screenshots, and
  transcripts voluntarily and publicly. This is the single best free source of
  current tactics, including the exact phrasing scammers use this year.
- **BBB Scam Tracker** (bbb.org/scamtracker) — searchable, filterable by
  "Employment" category, includes narrative descriptions.
- **FTC Consumer Sentinel** narratives and the FTC's published scam alerts.
- **Your own inbox / LinkedIn / Indeed messages** — if you're job searching,
  you're probably receiving these. Save them.

Copy the *text*. Do not scrape at volume, and don't save personal data of the
people who posted (redact victim names/emails).

## Where to get legitimate examples

- Real postings from company careers pages and job boards, across the same
  occupations your scam examples impersonate (data entry, admin, customer
  service, bookkeeping, warehouse). Match the distribution — if half your scams
  are "remote data entry," you need real remote-data-entry postings too, or the
  model just learns "remote data entry = scam."
- Include the hard cases on purpose: legitimate remote roles, legitimate roles
  with above-average pay, legitimate staffing-agency postings. These are where
  false positives come from, and finding them now is the point.

## Format

One JSON object per line in a `.jsonl` file, matching the seed:

```json
{"label": "scam", "title": "...", "company": "...", "description": "..."}
```

`label` is `scam` or `legit`. `company` can be empty. Put the full posting or
message text in `description`.

## Then measure

```bash
python -m scam_detector.tools.evaluate data/your_real_corpus.jsonl --threshold review
```

Read the misclassifications it prints. Each false positive is a rule that's too
aggressive; each false negative is a tactic you're missing. Adjust weights and
phrases in `rules.py`, re-run, repeat. Keep the corpus fixed while you tune, or
you're just fitting to noise.

## What a good result looks like

Don't chase a perfect score — that means you're overfitting or your corpus is
too easy. On real data, expect to start somewhere unimpressive and climb.
What matters most is a **low false-positive rate**: flagging a real job as a
scam costs a job seeker an opportunity, so precision on the "scam" call is the
number to protect. Decide your acceptable false-positive rate first, then tune
recall as high as it goes without crossing it.

## Only after this

Once you have a measured baseline from the rules, *then* it's worth asking
whether a trained classifier (fine-tuned transformer on your corpus) beats it,
and by how much, at what false-positive cost. Not before. The corpus makes that
an answerable question instead of a guess.
