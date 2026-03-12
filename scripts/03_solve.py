"""
Thin wrapper around solver.gpt5_mini.solve_dataset() for production use.

Generates predicted patches for each instance in a dataset. Idempotent:
solve_dataset() already skips instances whose output patch files exist.

Usage:
    python scripts/03_solve.py \
        --dataset data/scikit-hep/awkward/candidates.jsonl \
        --solver gpt5_mini \
        [--only-valid-oracles]   # skip instances with missing/invalid oracles
        [--max-instances 10]     # useful for quick tests
        [--out-dir results/]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _filter_valid_oracles(
    instances: list[dict],
    oracle_dir: Path,
) -> list[dict]:
    """Return only instances that have a valid oracle meta.json."""
    valid = []
    for inst in instances:
        meta_path = oracle_dir / f"{inst['instance_id']}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("is_valid"):
                    valid.append(inst)
            except Exception:
                pass
    return valid


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench solver wrapper")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to candidates.jsonl",
    )
    parser.add_argument(
        "--solver",
        default="gpt5_mini",
        help="Solver name (must match a solver.{name} module, default: gpt5_mini)",
    )
    parser.add_argument(
        "--only-valid-oracles",
        action="store_true",
        help="Skip instances that do not have a valid oracle",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Max instances to solve (0 = all)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Root results directory (default: results/)",
    )
    parser.add_argument(
        "--repos-yml",
        default="repos.yml",
        help="Path to repos.yml (default: repos.yml)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"ERROR: dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    instances = load_jsonl(str(dataset_path))
    if not instances:
        print("No instances found in dataset.", file=sys.stderr)
        sys.exit(1)

    # Optionally filter to valid-oracle instances only
    if args.only_valid_oracles:
        oracle_dir = dataset_path.parent / "oracles"
        before = len(instances)
        instances = _filter_valid_oracles(instances, oracle_dir)
        print(
            f"--only-valid-oracles: {len(instances)}/{before} instances "
            f"have valid oracles",
            flush=True,
        )

    if not instances:
        print("No instances to solve after filtering.", flush=True)
        return

    # Determine output directory: results/{solver}/{owner}/{name}/
    # Parse repo from first instance
    repo = instances[0].get("repo", "unknown/unknown")
    owner, name = (repo.split("/", 1) + ["unknown"])[:2]
    out_dir = Path(args.out_dir) / args.solver / owner / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import the solver module dynamically
    import importlib

    try:
        solver_mod = importlib.import_module(f"solver.{args.solver}")
    except ImportError as exc:
        print(f"ERROR: cannot import solver.{args.solver}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not hasattr(solver_mod, "solve_dataset"):
        print(
            f"ERROR: solver.{args.solver} has no solve_dataset() function.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Solving {len(instances)} instance(s) with {args.solver} → {out_dir}",
        flush=True,
    )

    solver_mod.solve_dataset(
        dataset_path=str(dataset_path),
        out_dir=str(out_dir),
        max_instances=args.max_instances,
        repos_yml=args.repos_yml,
    )

    # Count patches written
    patches = list(out_dir.glob("*.patch"))
    repo_slug = f"{owner}/{name}"
    print(f"{repo_slug}: {len(patches)} patch file(s) in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
