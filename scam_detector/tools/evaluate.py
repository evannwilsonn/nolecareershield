"""
Evaluation harness — the point of the whole project.

Runs the scorer against a labeled corpus and reports precision, recall, F1, and
a confusion matrix at a chosen decision band. This is the number that tells you
whether the detector works. Everything else is scaffolding around this.

Usage:
    python -m scam_detector.tools.evaluate data/labeled_seed.jsonl
    python -m scam_detector.tools.evaluate data/labeled_seed.jsonl --threshold review

Corpus format: JSON Lines, one posting per line:
    {"label": "scam"|"legit", "title": "...", "company": "...", "description": "..."}

The seed corpus shipped with this repo is tiny (20 items) and hand-written to be
obvious. It exists to prove the harness runs and to be REPLACED. Real numbers
require real postings — a few hundred, hand-labeled, from actual job boards and
scam-report sources (r/scams, BBB Scam Tracker, FTC complaint narratives).
A great F1 on the seed corpus means nothing; a measured F1 on real data is the
product.

Network lookups are OFF by default here so evaluation is fast and deterministic.
Turn them on with --network to measure the enrichment signals too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..scorer import score_posting


# Which bands count as "predicted scam" at each threshold setting.
THRESHOLDS = {
    "block":   {"block"},
    "review":  {"block", "review"},
    "caution": {"block", "review", "caution"},
}


def load_corpus(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"skipping malformed line {i}: {e}", file=sys.stderr)
            continue
        if row.get("label") not in ("scam", "legit", "lead_gen"):
            print(f"skipping line {i}: label must be 'scam', 'lead_gen', or 'legit'", file=sys.stderr)
            continue
        rows.append(row)
    return rows


# Labels that the detector SHOULD flag (i.e. "not a safe direct job").
# scam = fraud; lead_gen = data-harvesting aggregator wrapping a real job.
# Both should be flagged, but they're caught by different signals, so we
# track them separately in the report.
FLAG_LABELS = {"scam", "lead_gen"}


def evaluate(corpus: list[dict], threshold: str, run_network: bool) -> dict:
    scam_bands = THRESHOLDS[threshold]
    tp = fp = tn = fn = 0
    misses = []
    # per-category recall: how many of each flag-worthy label did we catch?
    caught = {"scam": 0, "lead_gen": 0}
    total = {"scam": 0, "lead_gen": 0}

    for row in corpus:
        url_field = row.get("url", "")
        url_chain = [u.strip() for u in url_field.split("->")] if url_field else []
        result = score_posting(
            title=row.get("title", ""),
            description=row.get("description", ""),
            company=row.get("company", ""),
            run_network=run_network,
            url_chain=url_chain,
        )
        predicted_flag = result.band in scam_bands
        should_flag = row["label"] in FLAG_LABELS

        if should_flag:
            total[row["label"]] += 1
            if predicted_flag:
                caught[row["label"]] += 1

        if predicted_flag and should_flag:
            tp += 1
        elif predicted_flag and not should_flag:
            fp += 1
            misses.append(("FALSE POSITIVE", row, result))
        elif not predicted_flag and not should_flag:
            tn += 1
        else:
            fn += 1
            misses.append(("MISSED (" + row["label"] + ")", row, result))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "n": len(corpus), "threshold": threshold,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "caught": caught, "total": total,
        "misses": misses,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the scam detector against labeled data.")
    ap.add_argument("corpus", type=Path, help="path to a JSONL labeled corpus")
    ap.add_argument("--threshold", choices=list(THRESHOLDS), default="review",
                    help="decision band that counts as 'scam' (default: review)")
    ap.add_argument("--network", action="store_true", help="run live domain/MX lookups")
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    if not corpus:
        print("no valid rows in corpus", file=sys.stderr)
        sys.exit(1)

    r = evaluate(corpus, args.threshold, args.network)

    print(f"\nCorpus: {r['n']} postings   Threshold: flag if band in {sorted(THRESHOLDS[args.threshold])}")
    print("  (flag-worthy = scam OR lead_gen; both should be flagged)")
    print("=" * 62)
    print(f"                   predicted flag   predicted safe")
    print(f"  should flag           {r['tp']:>4}             {r['fn']:>4}")
    print(f"  should be safe        {r['fp']:>4}             {r['tn']:>4}")
    print("=" * 62)
    print(f"  Precision: {r['precision']:.3f}   (of flagged, how many should have been)")
    print(f"  Recall:    {r['recall']:.3f}   (of flag-worthy, how many we caught)")
    print(f"  F1:        {r['f1']:.3f}")

    # Per-category recall — where the detector's blind spots actually are.
    print("\n  Recall by category:")
    for cat in ("scam", "lead_gen"):
        if r["total"][cat]:
            print(f"    {cat:9} {r['caught'][cat]}/{r['total'][cat]} caught")
        else:
            print(f"    {cat:9} (none in corpus)")

    if r["misses"]:
        print(f"\n  {len(r['misses'])} misclassified:")
        for kind, row, result in r["misses"]:
            print(f"    [{kind}] score {result.score} ({result.band}) — {row.get('title','')!r}")
    else:
        print("\n  No misclassifications on this corpus.")

    print("\nNote: replace the seed corpus with real, hand-labeled postings")
    print("before trusting any of these numbers.\n")


if __name__ == "__main__":
    main()
