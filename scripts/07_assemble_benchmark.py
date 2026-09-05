"""
scripts/07_assemble_benchmark.py — Assemble final benchmark from reviewed instances.

Reads candidates_reviewed.jsonl from each repo, filters to quality-accepted
and gold-passing instances, attaches oracle test code, and selects the final
benchmark set with balanced repo representation.

Usage:
    python scripts/07_assemble_benchmark.py \
        --reviewed-files data/scikit-hep/pyhf/candidates_reviewed.jsonl,\
                         data/scikit-hep/awkward/candidates_reviewed.jsonl,\
                         data/scikit-hep/uproot5/candidates_reviewed.jsonl \
        [--results-dir results/] [--target-count 50] [--seed 42] \
        [--out data/benchmark_v1.jsonl]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble final SWE-P-Bench benchmark from reviewed instances"
    )
    parser.add_argument(
        "--reviewed-files",
        required=True,
        help="Comma-separated paths to candidates_reviewed.jsonl files",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Root results directory (default: results/)",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=50,
        help="Number of instances to select (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible selection (default: 42)",
    )
    parser.add_argument(
        "--out",
        default="data/benchmark_v1.jsonl",
        help="Output benchmark JSONL path (default: data/benchmark_v1.jsonl)",
    )
    args = parser.parse_args()

    reviewed_paths = [p.strip() for p in args.reviewed_files.split(",") if p.strip()]
    results_dir = Path(args.results_dir)

    # Collect all accepted, gold-passing instances
    accepted: list[dict] = []

    for reviewed_path in reviewed_paths:
        reviewed_path = Path(reviewed_path)
        if not reviewed_path.exists():
            print(f"WARNING: {reviewed_path} not found, skipping", file=sys.stderr)
            continue

        records = load_jsonl(str(reviewed_path))
        repo = records[0].get("repo", "unknown/unknown") if records else "unknown"
        owner, name = (repo.split("/", 1) + ["unknown"])[:2]

        gold_eval_dir = results_dir / "gold" / "evals" / owner / name
        oracle_dir = reviewed_path.parent / "oracles"

        for rec in records:
            iid = rec["instance_id"]

            # Must be quality-accepted
            if not rec.get("quality_accept"):
                continue

            # Must be gold-passing
            eval_path = gold_eval_dir / f"{iid}.json"
            if not eval_path.exists():
                continue
            eval_result = json.loads(eval_path.read_text())
            if not eval_result.get("resolved"):
                continue

            # Must have oracle code
            oracle_path = oracle_dir / f"{iid}.py"
            if not oracle_path.exists():
                continue

            rec["oracle_test_code"] = oracle_path.read_text()
            rec["benchmark_version"] = "v1"
            accepted.append(rec)

        print(
            f"{reviewed_path}: {len(records)} reviewed, "
            f"{sum(1 for r in records if r.get('quality_accept'))} accepted, "
            f"{len([a for a in accepted if a.get('repo') == repo])} with gold+oracle"
        )

    print(f"\nTotal accepted with gold+oracle: {len(accepted)}")

    if len(accepted) < args.target_count:
        print(
            f"WARNING: Only {len(accepted)} instances available, "
            f"target is {args.target_count}. Using all.",
            file=sys.stderr,
        )
        selected = accepted
    else:
        # Balanced selection: proportional to available per repo
        rng = random.Random(args.seed)
        by_repo: dict[str, list[dict]] = {}
        for rec in accepted:
            by_repo.setdefault(rec["repo"], []).append(rec)

        # Proportional allocation
        total = len(accepted)
        allocations: dict[str, int] = {}
        remaining = args.target_count
        repos_sorted = sorted(by_repo.keys())

        for i, repo in enumerate(repos_sorted):
            if i == len(repos_sorted) - 1:
                allocations[repo] = remaining
            else:
                share = round(args.target_count * len(by_repo[repo]) / total)
                share = min(share, len(by_repo[repo]), remaining)
                allocations[repo] = share
                remaining -= share

        selected = []
        for repo in repos_sorted:
            pool = by_repo[repo]
            # Sort by quality score descending, then sample
            pool.sort(key=lambda r: r.get("quality_avg", 0), reverse=True)
            n = min(allocations[repo], len(pool))
            selected.extend(pool[:n])

        # If rounding left us short, fill from remaining
        if len(selected) < args.target_count:
            used_ids = {r["instance_id"] for r in selected}
            remaining_pool = [r for r in accepted if r["instance_id"] not in used_ids]
            remaining_pool.sort(key=lambda r: r.get("quality_avg", 0), reverse=True)
            selected.extend(remaining_pool[: args.target_count - len(selected)])

        selected = selected[: args.target_count]

    # Write benchmark JSONL
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for rec in selected:
            f.write(json.dumps(rec) + "\n")

    # Write manifest
    manifest_path = out_path.with_suffix(".manifest.json")
    by_repo_counts = {}
    for rec in selected:
        repo = rec["repo"]
        by_repo_counts[repo] = by_repo_counts.get(repo, 0) + 1

    manifest = {
        "benchmark_version": "v1",
        "created_at": datetime.now().isoformat(),
        "total_instances": len(selected),
        "target_count": args.target_count,
        "seed": args.seed,
        "per_repo": by_repo_counts,
        "source_files": [str(p) for p in reviewed_paths],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nWrote {len(selected)} instances to {out_path}")
    print(f"Manifest: {manifest_path}")
    for repo, count in sorted(by_repo_counts.items()):
        print(f"  {repo}: {count}")


if __name__ == "__main__":
    main()
