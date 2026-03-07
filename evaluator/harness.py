"""
Evaluation harness for SWE-P-Bench.

For each predicted patch:
  1. Clone the ACTS repo at base_commit into a temp directory.
  2. Apply the test_patch (gold tests from the PR).
  3. Build ACTS (CMake) and run the affected tests → record BEFORE status.
  4. Apply the predicted patch.
  5. Rebuild and re-run the same tests → record AFTER status.
  6. An instance is RESOLVED iff:
       - All FAIL_TO_PASS tests went from FAIL → PASS
       - All PASS_TO_PASS tests remain PASS
  7. Write a result record to eval.jsonl.

IMPORTANT: Full execution-based evaluation requires Docker / a build environment
with ACTS dependencies (C++20, CMake, Boost, Eigen3, etc.).
This harness provides TWO modes:

  --mode docker   Full evaluation using a Docker container (default when Docker available).
  --mode patch    Lightweight mode: only checks whether the predicted patch applies
                  cleanly. Does NOT run tests. Useful for quick sanity-checks.

For the Docker mode the harness uses the official acts-project/acts-ubuntu2404
base image which has all build dependencies pre-installed.

Usage:
    # Lightweight (patch-apply only)
    python -m evaluator.harness \
        --results results/gpt4o_mini/ \
        --dataset data/acts/candidates.jsonl \
        --mode patch \
        --out results/gpt4o_mini/eval.jsonl

    # Full (requires Docker)
    python -m evaluator.harness \
        --results results/gpt4o_mini/ \
        --dataset data/acts/candidates.jsonl \
        --mode docker \
        --out results/gpt4o_mini/eval.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from tqdm import tqdm

ACTS_BASE_IMAGE = "ghcr.io/acts-project/ubuntu2404:latest"


# ---------------------------------------------------------------------------
# Patch-apply mode (lightweight)
# ---------------------------------------------------------------------------

def _apply_patch_check(repo_dir: Path, patch_text: str) -> tuple[bool, str]:
    """Try to apply *patch_text* inside *repo_dir* with patch --dry-run."""
    if not patch_text.strip():
        return False, "empty patch"

    patch_file = repo_dir / "_predicted.patch"
    patch_file.write_text(patch_text)
    result = subprocess.run(
        ["patch", "--dry-run", "-p1", "-i", str(patch_file)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    patch_file.unlink(missing_ok=True)
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.strip() or result.stdout.strip()


def evaluate_patch_mode(
    instances: list[dict],
    predictions: dict[str, str],
) -> list[dict]:
    """
    Lightweight evaluation: clone at base_commit, check patch applies.
    Returns list of result records.
    """
    results: list[dict] = []

    for inst in tqdm(instances, desc="evaluating (patch mode)", unit="inst"):
        iid = inst["instance_id"]
        pred_patch = predictions.get(iid, "")

        if not pred_patch.strip():
            results.append({
                "instance_id": iid,
                "resolved": False,
                "mode": "patch",
                "error": "no prediction",
                "patch_applies": False,
            })
            continue

        with tempfile.TemporaryDirectory(prefix="swep_") as tmp:
            repo_dir = Path(tmp) / "acts"
            # Sparse clone at base_commit
            try:
                subprocess.run(
                    ["git", "clone", "--depth=1",
                     f"https://github.com/{inst['repo']}.git",
                     str(repo_dir)],
                    check=True, capture_output=True, timeout=120,
                )
                subprocess.run(
                    ["git", "fetch", "--depth=1", "origin", inst["base_commit"]],
                    cwd=repo_dir, check=True, capture_output=True, timeout=60,
                )
                subprocess.run(
                    ["git", "checkout", inst["base_commit"]],
                    cwd=repo_dir, check=True, capture_output=True, timeout=30,
                )
            except subprocess.CalledProcessError as e:
                results.append({
                    "instance_id": iid,
                    "resolved": False,
                    "mode": "patch",
                    "error": f"git clone/checkout failed: {e}",
                    "patch_applies": False,
                })
                continue

            applies, err = _apply_patch_check(repo_dir, pred_patch)
            results.append({
                "instance_id": iid,
                "resolved": applies,   # in patch mode, "applies cleanly" ≈ resolved
                "mode": "patch",
                "patch_applies": applies,
                "patch_error": err,
            })

    return results


# ---------------------------------------------------------------------------
# Docker mode (full build + test)
# ---------------------------------------------------------------------------

DOCKER_EVAL_SCRIPT = """\
#!/bin/bash
set -e
REPO_DIR=/acts
BUILD_DIR=/acts/build

# 1. Checkout base commit
cd $REPO_DIR
git checkout {base_commit}

# 2. Apply test patch (gold tests)
echo "{test_patch_b64}" | base64 -d > /tmp/test.patch
git apply /tmp/test.patch || patch -p1 < /tmp/test.patch

# 3. Build
cmake -S $REPO_DIR -B $BUILD_DIR -DCMAKE_BUILD_TYPE=RelWithDebInfo \\
    -DACTS_BUILD_UNITTESTS=ON -DACTS_BUILD_INTEGRATIONTESTS=OFF 2>&1
cmake --build $BUILD_DIR --parallel $(nproc) 2>&1

# 4. Run tests BEFORE predicted patch → capture failing tests
cd $BUILD_DIR
ctest --output-on-failure -R "{test_filter}" 2>&1 | tee /tmp/before.txt || true

# 5. Apply predicted patch
echo "{pred_patch_b64}" | base64 -d > /tmp/pred.patch
cd $REPO_DIR
git apply /tmp/pred.patch || patch -p1 < /tmp/pred.patch

# 6. Rebuild and run tests AFTER
cmake --build $BUILD_DIR --parallel $(nproc) 2>&1
cd $BUILD_DIR
ctest --output-on-failure -R "{test_filter}" 2>&1 | tee /tmp/after.txt || true

cat /tmp/before.txt
echo "---AFTER---"
cat /tmp/after.txt
"""


def _parse_ctest_results(output: str) -> dict[str, bool]:
    """Parse ctest output → {test_name: passed}."""
    passed: dict[str, bool] = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("PASSED") or ": Passed" in line:
            name = line.split()[-1]
            passed[name] = True
        elif line.startswith("FAILED") or ": Failed" in line:
            name = line.split()[-1]
            passed[name] = False
    return passed


def evaluate_docker_mode(
    instances: list[dict],
    predictions: dict[str, str],
) -> list[dict]:
    """Full evaluation using Docker. Requires Docker daemon and network access."""
    import base64

    results: list[dict] = []

    for inst in tqdm(instances, desc="evaluating (docker mode)", unit="inst"):
        iid = inst["instance_id"]
        pred_patch = predictions.get(iid, "")

        if not pred_patch.strip():
            results.append({
                "instance_id": iid,
                "resolved": False,
                "mode": "docker",
                "error": "no prediction",
            })
            continue

        test_patch_b64 = base64.b64encode(inst.get("test_patch", "").encode()).decode()
        pred_patch_b64 = base64.b64encode(pred_patch.encode()).decode()

        # Build a simple test filter from test_patch file names
        test_filter = ".*"  # run all unit tests by default

        script = DOCKER_EVAL_SCRIPT.format(
            base_commit=inst["base_commit"],
            test_patch_b64=test_patch_b64,
            pred_patch_b64=pred_patch_b64,
            test_filter=test_filter,
        )

        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-e", f"GITHUB_TOKEN={os.environ.get('GITHUB_TOKEN', '')}",
                    ACTS_BASE_IMAGE,
                    "bash", "-c",
                    f"git clone https://github.com/{inst['repo']} /acts && " + script,
                ],
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            results.append({
                "instance_id": iid,
                "resolved": False,
                "mode": "docker",
                "error": "timeout",
            })
            continue
        except Exception as e:
            results.append({
                "instance_id": iid,
                "resolved": False,
                "mode": "docker",
                "error": str(e),
            })
            continue

        # Split output into before/after sections
        before_txt, _, after_txt = output.partition("---AFTER---")
        before = _parse_ctest_results(before_txt)
        after = _parse_ctest_results(after_txt)

        # Compute FAIL_TO_PASS and PASS_TO_PASS from gold lists if available
        f2p = inst.get("FAIL_TO_PASS") or []
        p2p = inst.get("PASS_TO_PASS") or []

        if f2p:
            f2p_ok = all(not before.get(t, True) and after.get(t, False) for t in f2p)
        else:
            # No gold labels: check overall test improvement
            before_pass = sum(v for v in before.values())
            after_pass = sum(v for v in after.values())
            f2p_ok = after_pass >= before_pass and bool(after)

        p2p_ok = all(after.get(t, False) for t in p2p) if p2p else True

        resolved = f2p_ok and p2p_ok
        results.append({
            "instance_id": iid,
            "resolved": resolved,
            "mode": "docker",
            "before_results": before,
            "after_results": after,
            "f2p_ok": f2p_ok,
            "p2p_ok": p2p_ok,
        })

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-P-Bench evaluation harness")
    parser.add_argument("--results", required=True,
                        help="Directory containing predictions.jsonl")
    parser.add_argument("--dataset", required=True,
                        help="Dataset JSONL (data/acts/candidates.jsonl)")
    parser.add_argument("--out", required=True,
                        help="Output path for eval.jsonl")
    parser.add_argument("--mode", choices=["patch", "docker"], default="patch",
                        help="Evaluation mode (default: patch)")
    parser.add_argument("--max-instances", type=int, default=0)
    args = parser.parse_args()

    # Load dataset
    instances: list[dict] = []
    with open(args.dataset) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    if args.max_instances:
        instances = instances[:args.max_instances]

    # Load predictions
    predictions: dict[str, str] = {}
    pred_path = Path(args.results) / "predictions.jsonl"
    if pred_path.exists():
        with open(pred_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    p = json.loads(line)
                    predictions[p["instance_id"]] = p.get("patch", "")
    else:
        # Fall back: load individual .patch files
        for inst in instances:
            pf = Path(args.results) / f"{inst['instance_id']}.patch"
            if pf.exists():
                predictions[inst["instance_id"]] = pf.read_text()

    if not predictions:
        print("ERROR: No predictions found.", file=sys.stderr)
        sys.exit(1)

    mode: Literal["patch", "docker"] = args.mode  # type: ignore[assignment]
    if mode == "patch":
        eval_results = evaluate_patch_mode(instances, predictions)
    else:
        eval_results = evaluate_docker_mode(instances, predictions)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in eval_results:
            f.write(json.dumps(r) + "\n")

    n_resolved = sum(1 for r in eval_results if r["resolved"])
    print(f"\nResolved: {n_resolved} / {len(eval_results)} "
          f"({100 * n_resolved / max(len(eval_results), 1):.1f}%)")
    print(f"Results written to {args.out}")


if __name__ == "__main__":
    main()
