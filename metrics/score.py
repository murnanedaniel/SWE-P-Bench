"""
SWE-P-Bench scoring and reporting.

Reads eval.jsonl produced by evaluator/harness.py and prints a human-readable
benchmark report with the key metrics.

Metrics reported:
  - % Resolved            (primary SWE-bench metric)
  - % Patch applies       (patch-mode only: syntactic success)
  - Total instances
  - Resolved count
  - Error / no-prediction count

Usage:
    python -m metrics.score --eval results/gpt4o_mini/eval.jsonl [--dataset data/acts/candidates.jsonl]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_metrics(eval_records: list[dict]) -> dict:
    total = len(eval_records)
    resolved = [r for r in eval_records if r.get("resolved")]
    no_pred = [r for r in eval_records if r.get("error") == "no prediction"]
    errors = [r for r in eval_records if r.get("error") and r.get("error") != "no prediction"]

    # Patch-mode specific
    applies = [r for r in eval_records if r.get("patch_applies")]

    metrics: dict = {
        "total": total,
        "resolved": len(resolved),
        "resolve_rate": len(resolved) / total if total else 0.0,
        "no_prediction": len(no_pred),
        "errors": len(errors),
    }

    if any("patch_applies" in r for r in eval_records):
        metrics["patch_applies"] = len(applies)
        metrics["patch_apply_rate"] = len(applies) / total if total else 0.0

    return metrics


def print_report(metrics: dict, eval_path: str, dataset_path: str | None = None) -> None:
    w = 50
    print("=" * w)
    print("  SWE-P-Bench Results")
    print("=" * w)
    print(f"  Eval file  : {eval_path}")
    if dataset_path:
        print(f"  Dataset    : {dataset_path}")
    print("-" * w)
    print(f"  Total instances  : {metrics['total']}")
    print(f"  Resolved         : {metrics['resolved']}")
    print(f"  Resolve rate     : {metrics['resolve_rate'] * 100:.1f}%")
    if "patch_apply_rate" in metrics:
        print(f"  Patch applies    : {metrics['patch_applies']}")
        print(f"  Patch apply rate : {metrics['patch_apply_rate'] * 100:.1f}%")
    if metrics["no_prediction"]:
        print(f"  No prediction    : {metrics['no_prediction']}")
    if metrics["errors"]:
        print(f"  Errors           : {metrics['errors']}")
    print("=" * w)


def compute_per_repo_metrics(eval_records: list[dict]) -> dict[str, dict]:
    """Group eval records by repo slug and compute metrics per group.

    Returns a dict mapping repo_slug -> metrics dict (same shape as
    compute_metrics() output).
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in eval_records:
        repo = r.get("repo") or r.get("instance_id", "unknown/unknown").rsplit("-", 1)[0]
        groups[repo].append(r)
    return {repo: compute_metrics(records) for repo, records in groups.items()}


def compute_oracle_validity_rate(meta_records: list[dict]) -> dict:
    """Compute oracle validity statistics from a list of meta.json dicts.

    Each dict is the content of an oracles/{instance_id}.meta.json file,
    containing at least an ``is_valid`` boolean key.

    Returns a dict with keys:
      total         — number of meta records
      valid         — count with is_valid == True
      validity_rate — valid / total (float in [0, 1])
    """
    total = len(meta_records)
    valid = sum(1 for r in meta_records if r.get("is_valid"))
    return {
        "total": total,
        "valid": valid,
        "validity_rate": valid / total if total else 0.0,
    }


def compare_evals(paths: list[str]) -> None:
    """Print a side-by-side comparison table for multiple eval files."""
    rows: list[tuple[str, dict]] = []
    for p in paths:
        records = load_jsonl(p)
        m = compute_metrics(records)
        rows.append((Path(p).stem, m))

    # Header
    print(f"\n{'Model':<30} {'Total':>7} {'Resolved':>9} {'Rate':>8}")
    print("-" * 58)
    for name, m in rows:
        print(
            f"{name:<30} {m['total']:>7} {m['resolved']:>9} "
            f"{m['resolve_rate'] * 100:>7.1f}%"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench metric reporter")
    parser.add_argument("--eval", nargs="+", required=True,
                        help="One or more eval.jsonl paths")
    parser.add_argument("--dataset", default="",
                        help="Optional: dataset JSONL for additional context")
    parser.add_argument("--compare", action="store_true",
                        help="Print a comparison table when multiple --eval paths given")
    args = parser.parse_args()

    if len(args.eval) == 1:
        records = load_jsonl(args.eval[0])
        metrics = compute_metrics(records)
        print_report(metrics, args.eval[0], args.dataset or None)
    else:
        if args.compare:
            compare_evals(args.eval)
        else:
            for path in args.eval:
                records = load_jsonl(path)
                metrics = compute_metrics(records)
                print_report(metrics, path, args.dataset or None)
                print()


if __name__ == "__main__":
    main()
