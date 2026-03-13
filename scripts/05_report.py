"""
Aggregated results reporter for SWE-P-Bench.

Reads summary.jsonl files produced by scripts/04_evaluate.py and prints a
comparison table (solver × repo rows) across solvers and repos.

Usage:
    # Single dataset (original style):
    python scripts/05_report.py \\
        --solvers gold,gpt5_mini_1shot,gpt54_1shot \\
        [--dataset-dir data/] [--results-dir results/]

    # Multiple datasets:
    python scripts/05_report.py \\
        --solvers gold,gpt54_1shot \\
        --datasets data/scikit-hep/particle/candidates_filtered.jsonl,\\
                   data/scikit-hep/pyhf/candidates_filtered.jsonl \\
        [--results-dir results/]

Output (per-repo rows per solver):

    ================================================================
      SWE-P-Bench Results
    ================================================================
      Solver              Repo                    Instances  Resolved    Rate
    ----------------------------------------------------------------
      gold                scikit-hep/particle            10         8   80.0%
      gold                scikit-hep/pyhf                12        11   91.7%
      gold                scikit-hep/iminuit              8         7   87.5%
                          TOTAL                          30        26   86.7%
    ----------------------------------------------------------------
      gpt54_1shot         scikit-hep/particle            10         3   30.0%
      ...
    ================================================================
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


def _count_valid_oracles_from_dirs(oracle_dirs: list[Path]) -> tuple[int, int]:
    """Return (valid, total) oracle count across the given oracle directories."""
    total = valid = 0
    for d in oracle_dirs:
        for meta_file in d.glob("*.meta.json"):
            total += 1
            try:
                meta = json.loads(meta_file.read_text())
                if meta.get("is_valid"):
                    valid += 1
            except Exception:
                pass
    return valid, total


def _count_valid_oracles(dataset_dir: Path) -> tuple[int, int]:
    """Return (valid, total) oracle count, searching recursively under dataset_dir."""
    dirs = list(dataset_dir.glob("**/oracles"))
    return _count_valid_oracles_from_dirs(dirs) if dirs else (0, 0)


def print_comparison_table(
    solver_results: list[tuple[str, list[dict]]],
    oracle_dirs: list[Path],
) -> None:
    valid_oracles, total_oracles = _count_valid_oracles_from_dirs(oracle_dirs)
    oracle_pct = valid_oracles / total_oracles * 100 if total_oracles else 0.0

    w = 72
    s_col, r_col, i_col, res_col, rate_col = 20, 30, 9, 9, 8
    header = (
        f"  {'Solver':<{s_col}} {'Repo':<{r_col}} "
        f"{'Instances':>{i_col}} {'Resolved':>{res_col}} {'Rate':>{rate_col}}"
    )

    print("=" * w)
    print("  SWE-P-Bench Results")
    print("=" * w)
    if total_oracles:
        print(f"  Oracle validity: {valid_oracles}/{total_oracles} ({oracle_pct:.1f}%)")
        print("-" * w)

    print(header)
    print("-" * w)

    for solver, records in solver_results:
        if not records:
            print(f"  {solver:<{s_col}} {'(no data)'}")
            continue

        per_repo = compute_per_repo_metrics(records)
        first = True
        for repo_slug, m in sorted(per_repo.items()):
            slabel = solver if first else ""
            first = False
            print(
                f"  {slabel:<{s_col}} {repo_slug:<{r_col}} "
                f"{m['total']:>{i_col}} {m['resolved']:>{res_col}} "
                f"{m['resolve_rate'] * 100:>{rate_col}.1f}%"
            )

        # Totals row if more than one repo
        if len(per_repo) > 1:
            m_all = compute_metrics(records)
            print(
                f"  {'':<{s_col}} {'TOTAL':<{r_col}} "
                f"{m_all['total']:>{i_col}} {m_all['resolved']:>{res_col}} "
                f"{m_all['resolve_rate'] * 100:>{rate_col}.1f}%"
            )

        print("-" * w)

    print("=" * w)


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench results reporter")
    parser.add_argument(
        "--solvers",
        required=True,
        help="Comma-separated solver names (e.g. gold,gpt5_mini_1shot,gpt54_1shot)",
    )
    parser.add_argument(
        "--datasets",
        default=None,
        help=(
            "Comma-separated paths to candidates*.jsonl files. "
            "Oracle dirs are derived from their parent directories. "
            "If omitted, --dataset-dir is searched recursively."
        ),
    )
    parser.add_argument(
        "--dataset-dir",
        default="data",
        help="Root data directory used when --datasets is not given (default: data/)",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Root results directory (default: results/)",
    )
    args = parser.parse_args()

    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    results_dir = Path(args.results_dir)

    # Determine oracle directories
    if args.datasets:
        dataset_paths = [Path(p.strip()) for p in args.datasets.split(",") if p.strip()]
        oracle_dirs = [p.parent / "oracles" for p in dataset_paths]
    else:
        dataset_dir = Path(args.dataset_dir)
        oracle_dirs = list(dataset_dir.glob("**/oracles"))

    solver_results: list[tuple[str, list[dict]]] = []
    for solver in solvers:
        records = _load_all_eval_records(results_dir, solver)
        if not records:
            print(
                f"WARNING: no eval records found for solver '{solver}' in {results_dir}",
                file=sys.stderr,
            )
        solver_results.append((solver, records))

    print_comparison_table(solver_results, oracle_dirs)


if __name__ == "__main__":
    main()
