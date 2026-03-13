"""
Parallel evaluator for SWE-P-Bench predictions.

Runs evaluate_python_instance() in parallel for all instances in a dataset.
Writes per-instance JSON result files and aggregates them into summary.jsonl.

Idempotent: skips instances whose output JSON already exists.

Output layout:
  results/{solver}/evals/{owner}/{name}/{instance_id}.json  — per-instance
  results/{solver}/evals/{owner}/{name}/summary.jsonl       — aggregated

Usage:
    python scripts/04_evaluate.py \
        --dataset data/scikit-hep/awkward/candidates.jsonl \
        --solver gpt5_mini \
        [--gold]           # evaluate gold patches (instance["patch"]) instead
        [--workers 8]
        [--out-dir results/]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluator.python_harness import evaluate_python_instance
from scraper.generic import load_repo_config


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _eval_one(
    instance: dict,
    oracle_code: str,
    predicted_patch: str,
    eval_out_path: str,
) -> dict:
    """Worker: evaluate one instance and write result JSON.

    Must be importable (top-level) for ProcessPoolExecutor.
    """
    out_path = Path(eval_out_path)
    if out_path.exists():
        # Already evaluated — return cached result
        return json.loads(out_path.read_text())

    repo_config = load_repo_config(instance.get("repo", ""))
    result = evaluate_python_instance(
        instance=instance,
        oracle_test_code=oracle_code,
        predicted_patch=predicted_patch,
        repo_config=repo_config,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    return result


def _write_summary(eval_dir: Path, summary_path: Path) -> int:
    """Concatenate all per-instance JSON files into summary.jsonl.

    Returns total count written.
    """
    records = []
    for json_file in sorted(eval_dir.glob("*.json")):
        try:
            records.append(json.loads(json_file.read_text()))
        except Exception:
            pass
    with open(summary_path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench parallel evaluator")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to candidates.jsonl",
    )
    parser.add_argument(
        "--solver",
        default="gpt5_mini",
        help="Solver name (used for patch + output paths, default: gpt5_mini)",
    )
    parser.add_argument(
        "--gold",
        action="store_true",
        help="Evaluate gold patches (instance['patch']) instead of solver predictions",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel worker processes (default: 8)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Root results directory (default: results/)",
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

    repo = instances[0].get("repo", "unknown/unknown")
    owner, name = (repo.split("/", 1) + ["unknown"])[:2]

    solver_label = "gold" if args.gold else args.solver
    eval_dir = Path(args.out_dir) / solver_label / "evals" / owner / name
    eval_dir.mkdir(parents=True, exist_ok=True)

    oracle_dir = dataset_path.parent / "oracles"
    patches_dir = (
        Path(args.out_dir) / args.solver / owner / name
        if not args.gold
        else None
    )

    # Build work list — skip already-evaluated instances
    work: list[tuple[dict, str, str, str]] = []  # (instance, oracle_code, patch, out_path)
    skipped = 0
    missing_oracle = 0
    missing_patch = 0

    for inst in instances:
        iid = inst["instance_id"]
        out_path = str(eval_dir / f"{iid}.json")

        if Path(out_path).exists():
            skipped += 1
            continue

        # Load oracle code
        oracle_path = oracle_dir / f"{iid}.py"
        if not oracle_path.exists():
            missing_oracle += 1
            continue
        oracle_code = oracle_path.read_text()

        # Load predicted patch
        if args.gold:
            predicted_patch = inst.get("patch", "")
            if not predicted_patch:
                missing_patch += 1
                continue
        else:
            patch_path = patches_dir / f"{iid}.patch"
            if not patch_path.exists():
                missing_patch += 1
                continue
            predicted_patch = patch_path.read_text()

        work.append((inst, oracle_code, predicted_patch, out_path))

    print(
        f"Dataset: {dataset_path} — {len(instances)} instances "
        f"({skipped} already evaluated, {len(work)} to run, "
        f"{missing_oracle} missing oracle, {missing_patch} missing patch)",
        flush=True,
    )

    if not work:
        print("Nothing to evaluate.", flush=True)
    else:
        workers = min(args.workers, len(work))
        print(f"Evaluating {len(work)} instance(s) with {workers} worker(s) …", flush=True)

        resolved = 0
        errors = 0

        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_eval_one, inst, oracle_code, patch, out_path): inst[
                    "instance_id"
                ]
                for inst, oracle_code, patch, out_path in work
            }

            completed = 0
            for future in as_completed(futures):
                completed += 1
                iid = futures[future]
                try:
                    result = future.result()
                    is_resolved = result.get("resolved", False)
                    if is_resolved:
                        resolved += 1
                    elif result.get("error"):
                        errors += 1
                    status = "✓" if is_resolved else "✗"
                    print(
                        f"  [{completed}/{len(work)}] {status} {iid}",
                        flush=True,
                    )
                except Exception as exc:
                    errors += 1
                    print(
                        f"  [{completed}/{len(work)}] ERROR {iid}: {exc}",
                        flush=True,
                    )

    # Write summary.jsonl
    summary_path = eval_dir / "summary.jsonl"
    total_written = _write_summary(eval_dir, summary_path)

    # Count resolved from all JSON files (includes previously skipped)
    all_results = load_jsonl(str(summary_path))
    total_resolved = sum(1 for r in all_results if r.get("resolved"))
    total_eval = len(all_results)
    rate = total_resolved / total_eval * 100 if total_eval else 0.0

    repo_slug = f"{owner}/{name}"
    print(
        f"\n{repo_slug} ({solver_label}): "
        f"{total_resolved}/{total_eval} resolved ({rate:.1f}%) "
        f"→ {summary_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
