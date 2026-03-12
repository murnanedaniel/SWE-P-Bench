"""
Aggregated results reporter for SWE-P-Bench.

Reads summary.jsonl files produced by scripts/04_evaluate.py and prints a
comparison table across solvers and repos.

Usage:
    python scripts/05_report.py \
        --solvers gpt5_mini,gold \
        [--dataset-dir data/] [--results-dir results/]

Output example:

    ============================================================
      SWE-P-Bench Results
    ============================================================
      Solver             Instances  Valid Oracles  Resolved  Rate
    ------------------------------------------------------------
      gold                     245           221      201   91.0%
      gpt5_mini                245           221       67   30.3%
    ------------------------------------------------------------
      By repo (gpt5_mini):
        scikit-hep/awkward        47   31   66.0%
        scikit-hep/uproot5        38   19   50.0%
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from metrics.score import compute_metrics, compute_per_repo_metrics, compute_oracle_validity_rate


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _find_summary_files(results_dir: Path, solver: str) -> list[Path]:
    """Glob all summary.jsonl files for a solver."""
    return sorted(
        (results_dir / solver / "evals").glob("**/summary.jsonl")
    )


def _load_all_eval_records(results_dir: Path, solver: str) -> list[dict]:
    """Concatenate all summary.jsonl records for a solver."""
    records: list[dict] = []
    for f in _find_summary_files(results_dir, solver):
        records.extend(load_jsonl(str(f)))
    return records


def _count_valid_oracles(dataset_dir: Path) -> tuple[int, int]:
    """Return (valid_oracle_count, total_oracle_count) across all repos."""
    total = 0
    valid = 0
    for meta_file in dataset_dir.glob("**/oracles/*.meta.json"):
        total += 1
        try:
            meta = json.loads(meta_file.read_text())
            if meta.get("is_valid"):
                valid += 1
        except Exception:
            pass
    return valid, total


def print_comparison_table(
    solver_results: list[tuple[str, list[dict]]],
    dataset_dir: Path,
) -> None:
    valid_oracles, total_oracles = _count_valid_oracles(dataset_dir)
    oracle_pct = valid_oracles / total_oracles * 100 if total_oracles else 0.0

    w = 62
    print("=" * w)
    print("  SWE-P-Bench Results")
    print("=" * w)
    if total_oracles:
        print(
            f"  Oracle validity: {valid_oracles}/{total_oracles} ({oracle_pct:.1f}%)"
        )
        print("-" * w)
    print(
        f"  {'Solver':<20} {'Instances':>9} {'Resolved':>9} {'Rate':>8}"
    )
    print("-" * w)
    for solver, records in solver_results:
        if not records:
            print(f"  {solver:<20} {'(no data)':>9}")
            continue
        m = compute_metrics(records)
        print(
            f"  {solver:<20} {m['total']:>9} {m['resolved']:>9} "
            f"{m['resolve_rate'] * 100:>7.1f}%"
        )
    print("=" * w)


def print_per_repo_breakdown(solver: str, records: list[dict]) -> None:
    if not records:
        return
    per_repo = compute_per_repo_metrics(records)
    print(f"\n  By repo ({solver}):")
    print(f"  {'Repo':<35} {'Instances':>9} {'Resolved':>9} {'Rate':>8}")
    print("  " + "-" * 55)
    for repo_slug, m in sorted(per_repo.items()):
        print(
            f"  {repo_slug:<35} {m['total']:>9} {m['resolved']:>9} "
            f"{m['resolve_rate'] * 100:>7.1f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench results reporter")
    parser.add_argument(
        "--solvers",
        required=True,
        help="Comma-separated solver names (e.g. gpt5_mini,gold)",
    )
    parser.add_argument(
        "--dataset-dir",
        default="data",
        help="Root data directory (default: data/)",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Root results directory (default: results/)",
    )
    parser.add_argument(
        "--no-breakdown",
        action="store_true",
        help="Skip per-repo breakdown (print summary only)",
    )
    args = parser.parse_args()

    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    results_dir = Path(args.results_dir)
    dataset_dir = Path(args.dataset_dir)

    solver_results: list[tuple[str, list[dict]]] = []
    for solver in solvers:
        records = _load_all_eval_records(results_dir, solver)
        if not records:
            print(
                f"WARNING: no eval records found for solver '{solver}' in {results_dir}",
                file=sys.stderr,
            )
        solver_results.append((solver, records))

    print_comparison_table(solver_results, dataset_dir)

    if not args.no_breakdown:
        for solver, records in solver_results:
            print_per_repo_breakdown(solver, records)
        print()


if __name__ == "__main__":
    main()
