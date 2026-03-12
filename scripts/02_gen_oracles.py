"""
Parallel oracle test generation and validation for SWE-P-Bench.

For each instance in a candidates.jsonl file, generates and validates oracle
tests using the LLM. Skips instances where the meta.json output already exists
(idempotent / safe to resume).

Output per instance:
  data/{owner}/{name}/oracles/{instance_id}.py        — oracle test code
  data/{owner}/{name}/oracles/{instance_id}.meta.json — validation result

Usage:
    python scripts/02_gen_oracles.py \
        --dataset data/scikit-hep/awkward/candidates.jsonl \
        [--workers 4] [--n-tests 3] [--max-attempts 3] \
        [--model gpt-5-mini]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.generic import load_repo_config
from test_writer.validator import generate_and_validate


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _process_one(
    instance: dict,
    oracle_dir: str,
    n: int,
    max_attempts: int,
    model: str,
) -> tuple[str, bool, str | None]:
    """Worker function: generate + validate oracle for one instance.

    Returns (instance_id, is_valid, error_or_None).
    Must be importable (top-level) for ProcessPoolExecutor.
    """
    instance_id = instance["instance_id"]
    oracle_dir_path = Path(oracle_dir)
    code_path = oracle_dir_path / f"{instance_id}.py"
    meta_path = oracle_dir_path / f"{instance_id}.meta.json"

    # Already done?
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            return instance_id, meta.get("is_valid", False), None
        except Exception:
            pass  # re-generate if meta is corrupt

    oracle_dir_path.mkdir(parents=True, exist_ok=True)

    repo_config = load_repo_config(instance.get("repo", ""))

    oracle_code, result = generate_and_validate(
        instance=instance,
        n=n,
        max_attempts=max_attempts,
        model=model,
        repo_config=repo_config,
    )

    # Write oracle code (even if invalid — useful for debugging)
    code_path.write_text(oracle_code)

    # Write meta
    meta_path.write_text(json.dumps(result, indent=2))

    is_valid = result.get("is_valid", False)
    error = result.get("error") if not is_valid else None
    return instance_id, is_valid, error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel oracle test generation for SWE-P-Bench"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to candidates.jsonl",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4)",
    )
    parser.add_argument(
        "--n-tests",
        type=int,
        default=3,
        help="Number of oracle tests to generate per instance (default: 3)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Max LLM retry attempts per instance (default: 3)",
    )
    parser.add_argument(
        "--model",
        default="gpt-5-mini",
        help="LLM model for oracle generation (default: gpt-5-mini)",
    )
    parser.add_argument(
        "--out-dir",
        default="data",
        help="Root data directory (default: data/)",
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

    # Derive oracle dir from dataset path
    # dataset path: data/{owner}/{name}/candidates.jsonl
    # oracle dir:   data/{owner}/{name}/oracles/
    oracle_dir = str(dataset_path.parent / "oracles")

    # Filter to only instances not yet processed
    pending = []
    already_done = 0
    for inst in instances:
        meta_path = Path(oracle_dir) / f"{inst['instance_id']}.meta.json"
        if meta_path.exists():
            already_done += 1
        else:
            pending.append(inst)

    print(
        f"Dataset: {dataset_path} — {len(instances)} instances "
        f"({already_done} already done, {len(pending)} to process)",
        flush=True,
    )

    if not pending:
        print("All instances already have oracle outputs. Nothing to do.")
        return

    valid_count = already_done  # start from what was already validated
    # Re-count valid from already done
    valid_count = 0
    for inst in instances:
        meta_path = Path(oracle_dir) / f"{inst['instance_id']}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("is_valid"):
                    valid_count += 1
            except Exception:
                pass

    errors: list[tuple[str, str]] = []

    workers = min(args.workers, len(pending))
    print(f"Processing {len(pending)} instances with {workers} worker(s) …", flush=True)

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_one,
                inst,
                oracle_dir,
                args.n_tests,
                args.max_attempts,
                args.model,
            ): inst["instance_id"]
            for inst in pending
        }

        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                instance_id, is_valid, error = future.result()
                if is_valid:
                    valid_count += 1
                elif error:
                    errors.append((instance_id, error))
                status = "✓" if is_valid else "✗"
                print(
                    f"  [{completed}/{len(pending)}] {status} {instance_id}",
                    flush=True,
                )
            except Exception as exc:
                iid = futures[future]
                errors.append((iid, str(exc)))
                print(f"  [{completed}/{len(pending)}] ERROR {iid}: {exc}", flush=True)

    total = len(instances)
    rate = valid_count / total * 100 if total else 0.0
    print(
        f"\nSummary: {valid_count}/{total} instances have valid oracles "
        f"({rate:.1f}%)",
        flush=True,
    )
    if errors:
        print(f"\n{len(errors)} instance(s) failed:", flush=True)
        for iid, err in errors[:10]:
            print(f"  {iid}: {err}", flush=True)
        if len(errors) > 10:
            print(f"  … and {len(errors) - 10} more.", flush=True)


if __name__ == "__main__":
    main()
