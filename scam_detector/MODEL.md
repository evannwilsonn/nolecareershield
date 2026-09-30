# The learned layer

The rules (`rulepack/`, `rules.py`, `scorer.py`) are still the detector. On top of them sits a small
machine-learning model that reads the same evidence a reviewer would and asks: does this look like the
scams we've labeled?

## How it works

- **Model:** logistic regression over two kinds of input: which rules fired (plus their total score), and
  the words and two-word phrases in the posting (TF-IDF). It learns how much each rule should really count,
  and, as the data grows, wording that no rule covers yet.
- **Training:** `python -m scam_detector.tools.train_model`. It needs scikit-learn (`requirements-dev.txt`).
  The site itself doesn't: `ml.py` does the inference in plain Python from one JSON file,
  `models/scam_model.json`.
- **Data:** every labeled corpus in `data/` except the frozen holdout, plus the synthetic scams at half
  weight, plus reviewer decisions: `python export_labeled.py --db jobs.db -o labeled.jsonl`, then
  `train_model --extra labeled.jsonl`. Near-copies of the same template share one example's weight.

## What it is allowed to do

It only escalates, and only when the rules were quiet (band `clear` or `caution`):

| Where | What the model can do |
|---|---|
| A listing submitted to the board | Status `clear` → `flagged`, with the note "Worth a second look" |
| Public listing check | "No known scam signs" → "Be careful" |

It never lowers a rule verdict, never rejects or blocks anything, and always says why: the rules and
phrases that pushed it up. Switch it off with `SCAM_MODEL=off`. With no model file, the site runs on rules
alone.

**Messages are out of scope for now.** Every legit example it has learned from is a job listing, so it has
never seen a real recruiter email. The message check stays rules-only until legit messages are labeled.

**Collection leftovers are stripped** before any text reaches it: redaction placeholders, email header
labels like "From:" and "Subject:", and URL schemes. Otherwise it learns "archived email = scam".

## When a model ships

`train_model` writes the model only if all of these hold:

1. On the frozen holdouts (`data/field_2026_09_holdout.jsonl` and `field_2026_10_holdout.jsonl`, never trained on), rules + model catch more
   scams than the rules alone, and no fewer than the model currently shipped.
2. There are no new false alarms: no legit listing the rules leave alone gets flagged, on the holdout or on
   the hard-legit set (`data/stress_legit.jsonl`, also never trained on).

The threshold comes from cross-validation on the training rows, never below 0.5. Every run writes
`models/TRAINING_REPORT.md`.

## Status (Sept 30, 2026): shipped, version in models/scam_model.json

| Run | Training rows | Holdout scams caught (rules alone: 15/28) | New false alarms | Gate |
|---|---|---|---|---|
| 1 | 115 | 13/14 on the Sept holdout | camp counselor job | refused |
| 2 | 207 (+ October field batch) | 19/28 | none | shipped |
| 3 | 306 (+ 99 LinkedIn/Indeed/ZipRecruiter/Glassdoor listings) | 19/28 | none | **shipped (current)** |

- **Run 1** had learned "weekly pay alone = scam". It was fixed with 29 real weekly-pay jobs; see
  `data/FIELD_TEST_2026_10.md`.
- **Run 3** first raised its threshold to 0.90 and caught fewer scams, so the gate refused it. The cause
  was a real rule bug: `personal_channel` fired on an Indeed employer's anti-scam disclaimer, and the
  model learned to distrust the rule. After the rule fix (see `data/BOARDS_2026_10.md`) it passed at
  threshold 0.70. Cross-validation over 306 rows: 73/88 scams, with the only legit flag coming from the
  rules.

Where the gain comes from: mostly learned weights on the rules. Combinations of weak signals that add up to
less than the rules' review threshold are still scams. The phrase features count for little until there
are a few hundred more scam rows. Live job boards yield almost no scams (they're removed fast), so
reviewer decisions from the board and scam archives stay the main scam sources.
