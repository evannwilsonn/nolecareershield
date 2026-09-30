# Field test, September 2026

**Question:** how does the detector do on real listings it has never seen, and what should it learn from them?

## Method
1. **Collected 108 real listings:**
   - 26 job scams that universities published verbatim in their phishing archives (Cornell, Syracuse, Brown, VCU, Ohio U., UCLA)
   - 16 scam messages quoted by news and security sites
   - 10 aggregator listings from a job-search site
   - 30 postings from real companies found through job boards (remote AI training, staffing agencies, campus jobs, internships, fintech/crypto)
   - 26 Craigslist posts from Florida (Tallahassee, Tampa and nearby)
2. **Labeled every listing by hand before running the detector**, following `LABELING_RUBRIC.md`. Each row's `notes` holds the verdict and the reason. Five were dropped: three duplicate templates and two that couldn't be decided.
   - **Result:** 103 rows. 42 scam, 12 lead_gen, 49 legit.
   - **Frozen:** `field_2026_09.jsonl.sha256` records the file before any detector run.
3. **Split 2/3 tune, 1/3 holdout**, stratified by label. Rules were written from the reasons in the notes and checked only against the tune set. The holdout was scored once at the end.
4. **Every change went through `tools/regress.py`**: no new false positives and no recall drop on any existing corpus.

## Results (flag = review/block band for scams; lead-gen axis or fraud band for lead-gen)

| Set | Scams caught | Lead-gen flagged | Legit left alone |
|---|---|---|---|
| All 103, before | 4/42 | 1/12 | 47/49 |
| All 103, after | **35/42** | **10/12** | **49/49** |
| Holdout only (34, never tuned on), before | 2/14 | 0/4 | 16/16 |
| Holdout only, after | **11/14** | **3/4** | **16/16** |

## What changed
**Fixed a false positive.** `irreversible_pay` flagged small gigs that pay the worker through PayPal, Venmo or Cash App: a real store-audit gig and a real promoter job. It now flags only money the applicant sends through those apps, and pay in gift cards, crypto or wire services.

**Widened `too_good`.** It now also catches "no prerequisite training or experience needed".

**Added 15 rules**, all written from the labeling reasons:

| Rule | Behavior it catches |
|---|---|
| `preselected_offer` | An offer "approved for you" that you never applied for |
| `weekly_stipend` | A flat weekly sum for part-time work |
| `personal_channel` | "Use your alternative email", "text your name", Instagram-only contact |
| `any_department` | A research assistant job open to any department |
| `student_hardship_bait` | "Won't interfere with your academics" |
| `reship_home` | Receiving and re-shipping packages at home |
| `fake_check_funds` | A check or funds to buy equipment, supplies or gifts |
| `app_boost_task` | App-download and play-count task scams |
| `brand_recruiter_text` | "Sorry to interrupt, I'm from Indeed/TikTok HR" |
| `pet_sitter_relative` | A relative "moving to the area" who needs a pet sitter |
| `crypto_atm` | Crypto ATM tasks |
| `pii_upfront` | Student ID, date of birth or home address asked for in the first message |
| `startup_cost` | Money to start |
| `review_fraud` | Paid fake reviews |
| `income_claim` | Data-entry income claims like "$300/day" |

The negation guard is off for the behavior rules. For example, "reply from your alternative email and **not** your school email" is the scam itself, not a negation.

**Added text tells to the lead-gen axis:** boilerplate "fill out our application" pitches, survey or focus-group panels dressed up as jobs, "you'll get an email within 2 minutes" funnels, income or referral "opportunities", free-account signups, and scraped job IDs.

**Added this set to the regression gate** (`CORPORA` in `tools/regress.py`), so future rule changes can't lose these detections.

## Still missed, on purpose or for now
- **Very short one-liners:** "humanitarian job $500 weekly, see attachment", and a mass "JOB VACANCY" with only a link. There's too little text to act on without hurting precision.
- **Impersonation from a free email** (a "Career Center" asking for your Gmail) with no other strong signal.
- **"Your PERSONAL 'Email Address'"** in quotes, in the holdout set. It was left unfixed so the holdout number stays honest.
- **A reshipping lure that never mentions packages** ("Logistics Manager", paperwork).
- **Two lead-gen listings:** a writers' association funnel ($100/article) and a one-line product-panel ad.

## Limits
- **Skewed toward university templates.** The scam side is dominated by university email templates (26 of 42), several of which are near-copies across schools. Near-copies land in both tune and holdout, so the holdout number is somewhat optimistic for other kinds of scams.
- **Text may be lightly paraphrased.** Listings were retrieved through a page reader that sometimes shortens text.
- **Labels are one person's judgment.** University- and news-published scams are confirmed by the source. Craigslist and job-board labels are judgment from the text.
- **Network checks were off.** Domain age and MX checks didn't run during evaluation.
- **Small sample.** 103 listings is a real-world check, not a measured accuracy. Keep adding labeled reviewer decisions (see `ADAPTING.md`).
