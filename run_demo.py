#!/usr/bin/env python3
"""
SWE-P-Bench — End-to-End Demo

Demonstrates the full benchmark pipeline on one issue-PR pair from a
Python HEP repo (default: scikit-hep/awkward):

  1. SCRAPE    — find the first valid issue-PR pair (scraper/generic.py).
  2. GENERATE  — write N oracle tests with GPT-5-mini, validate them against
                 the gold patch (fail→pass), retry up to 3× with feedback.
  3. SOLVE     — generate a predicted patch with GPT-5-mini (sees issue only).
  4. EVALUATE  — run pytest before/after the predicted patch.

Results are saved under data/demo/.

Usage:
    python run_demo.py [--repo OWNER/NAME] [--n-tests N] [--skip-eval]
                       [--max-validate-attempts N]

Environment:
    GITHUB_TOKEN     GitHub PAT — strongly recommended for scraping.
    OPENAI_API_KEY   Required for test generation and solving.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from scraper.generic import load_repo_config, scrape
from test_writer.validator import generate_and_validate
from evaluator.python_harness import evaluate_python_instance
from solver.gpt5_mini import _normalize_patch

load_dotenv()

# ---------------------------------------------------------------------------
# Python solver (inline)
# ---------------------------------------------------------------------------

_SOLVER_SYSTEM = """\
You are an expert Python software engineer working on scientific / HEP Python libraries.

Your task: given a GitHub issue description, produce a minimal unified diff patch \
(git diff format) that resolves the issue in the described repository.

Rules:
- Output ONLY the raw unified diff, nothing else.
- Do not include explanations, prose, or code fences.
- The diff must apply cleanly with `git apply` or `patch -p1`.
- Keep changes minimal — fix only what the issue describes.
- Match the existing code style.
- File paths MUST follow the actual modern layout of the repo.
  Most scientific Python packages use the `src/<package>/` layout.
  Derive paths from the issue text and API name (e.g. `ak.from_buffers` →
  `src/awkward/operations/ak_from_buffers.py`).
  Never invent legacy `_v2/` or `_v3/` subpaths.
"""

_SOLVER_USER = """\
## Repository
{repo}

## Issue
{problem_statement}

{hints_section}

## Task
Produce a unified diff patch that resolves this issue.
Output only the raw diff, no explanations.
"""


def _solve_python(client: OpenAI, instance: dict, model: str = "gpt-5-mini") -> str:
    """Call GPT-5-mini to generate a predicted patch (no gold patch shown)."""
    hints = instance.get("hints_text", "").strip()
    hints_section = f"## Hints / Discussion\n\n{hints}" if hints else ""
    user_msg = _SOLVER_USER.format(
        repo=instance.get("repo", ""),
        problem_statement=instance.get("problem_statement", ""),
        hints_section=hints_section,
    ).strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SOLVER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_completion_tokens=8000,
    )
    raw = response.choices[0].message.content or ""
    return _normalize_patch(raw)


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def run_demo(
    repo: str = "scikit-hep/awkward",
    n_tests: int = 3,
    skip_eval: bool = False,
    max_validate_attempts: int = 3,
) -> None:
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=openai_key)
    demo_dir = Path("data/demo")
    demo_dir.mkdir(parents=True, exist_ok=True)

    sep = "=" * 60

    # ------------------------------------------------------------------ 1
    print(f"\n{sep}")
    print("STEP 1 — SCRAPING")
    print(sep)

    instance_file = demo_dir / "instance.json"
    if instance_file.exists():
        print(f"Loading cached instance from {instance_file}")
        instance = json.loads(instance_file.read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print(
                "WARNING: GITHUB_TOKEN not set — rate-limited to 60 req/hr "
                "(will abort on first hit).",
                file=sys.stderr,
            )
        repo_cfg = load_repo_config(repo)
        instances = scrape(
            repo=repo,
            token=token,
            cache_dir=".scraper_cache",
            max_instances=1,
            config=repo_cfg,
        )
        if not instances:
            print("ERROR: Could not find a valid instance.", file=sys.stderr)
            sys.exit(1)
        instance = instances[0]
        instance_file.write_text(json.dumps(instance, indent=2))

    print(f"\nInstance  : {instance['instance_id']}")
    print(f"Issue URL : {instance['issue_url']}")
    print(f"PR URL    : {instance['pr_url']}")
    print(
        f"Patch     : +{instance['pr_additions']} / -{instance['pr_deletions']}"
        f" in {instance['pr_changed_files']} file(s)"
    )
    print(f"\nProblem statement (first 400 chars):")
    print(instance["problem_statement"][:400])

    # ------------------------------------------------------------------ 2
    print(f"\n{sep}")
    print("STEP 2 — GENERATING + VALIDATING ORACLE TESTS (GPT-5-mini)")
    print(sep)
    print(f"Generating {n_tests} tests, up to {max_validate_attempts} attempts.")

    oracle_file = demo_dir / "oracle_tests.py"
    val_result_file = demo_dir / "validation_result.json"

    if oracle_file.exists() and val_result_file.exists():
        print(f"Loading cached oracle tests from {oracle_file}")
        oracle_code = oracle_file.read_text()
        val_result = json.loads(val_result_file.read_text())
    else:
        repo_cfg = load_repo_config(repo)
        oracle_code, val_result = generate_and_validate(
            instance,
            n=n_tests,
            max_attempts=max_validate_attempts,
            model="gpt-5-mini",
            repo_config=repo_cfg,
        )
        oracle_file.write_text(oracle_code)
        val_result_file.write_text(json.dumps(val_result, indent=2))

    test_names = re.findall(r"^def (test_\w+)", oracle_code, re.MULTILINE)
    print(f"\nGenerated functions : {test_names}")
    print(f"Validation passed   : {val_result['is_valid']}")
    print(f"FAIL_TO_PASS        : {val_result['FAIL_TO_PASS']}")
    print(f"Before results      : {val_result['before_results']}")
    print(f"After results       : {val_result['after_results']}")
    if val_result.get("error"):
        print(f"Validation error    : {val_result['error']}")
    print(f"\nOracle test code:\n{'-'*40}")
    print(oracle_code)
    print("-" * 40)

    if not val_result["is_valid"]:
        print(
            "\nWARNING: Oracle tests did not validate (gold patch does not make them pass). "
            "Continuing with evaluation anyway for diagnostic purposes.",
            file=sys.stderr,
        )

    # Update the instance with populated FAIL_TO_PASS / PASS_TO_PASS
    instance["FAIL_TO_PASS"] = val_result["FAIL_TO_PASS"]
    instance["PASS_TO_PASS"] = val_result["PASS_TO_PASS"]

    # ------------------------------------------------------------------ 3
    print(f"\n{sep}")
    print("STEP 3 — SOLVING (GPT-5-mini, issue description only)")
    print(sep)

    patch_file = demo_dir / "predicted_patch.patch"
    if patch_file.exists():
        print(f"Loading cached prediction from {patch_file}")
        predicted_patch = patch_file.read_text()
    else:
        print("Calling GPT-5-mini solver (no gold patch shown) …")
        predicted_patch = _solve_python(client, instance)
        patch_file.write_text(predicted_patch)

    print(f"\nPredicted patch ({len(predicted_patch)} chars):\n{'-'*40}")
    print(predicted_patch[:1200])
    if len(predicted_patch) > 1200:
        print("… [truncated]")
    print("-" * 40)

    if skip_eval:
        print("\n[--skip-eval] Skipping evaluation steps.")
        return

    # ------------------------------------------------------------------ 4
    print(f"\n{sep}")
    print("STEP 4 — EVALUATING PREDICTED PATCH")
    print(sep)
    print("This clones the repo, pip-installs it, then runs pytest before/after.")

    repo_cfg = load_repo_config(repo)
    pred_result = evaluate_python_instance(
        instance, oracle_code, predicted_patch, repo_config=repo_cfg
    )
    (demo_dir / "eval_predicted.json").write_text(
        json.dumps(pred_result, indent=2)
    )

    print(f"\n--- Predicted patch results ---")
    print(f"Resolved   : {pred_result['resolved']}")
    print(f"Install OK : {pred_result['install_ok']}")
    print(f"FAIL→PASS  : {pred_result['FAIL_TO_PASS']}")
    print(f"PASS→PASS  : {pred_result['PASS_TO_PASS']}")
    print(f"Before     : {pred_result['before_results']}")
    print(f"After      : {pred_result['after_results']}")
    if pred_result.get("error"):
        print(f"Error      : {pred_result['error']}")

    # ------------------------------------------------------------------ summary
    print(f"\n{sep}")
    print("SUMMARY")
    print(sep)
    oracle_quality = (
        "VALID (gold patch makes tests fail→pass)"
        if val_result["is_valid"]
        else "INVALID (oracle tests did not validate against gold patch)"
    )
    solver_quality = (
        "RESOLVED" if pred_result["resolved"] else "NOT RESOLVED"
    )
    print(f"Oracle tests  : {oracle_quality}")
    print(f"GPT-5-mini    : {solver_quality}")
    print(f"\nArtifacts saved in {demo_dir}/")


def main() -> None:
    ap = argparse.ArgumentParser(description="SWE-P-Bench end-to-end demo")
    ap.add_argument(
        "--repo", default="scikit-hep/awkward",
        help="GitHub repo slug (default: scikit-hep/awkward)",
    )
    ap.add_argument(
        "--n-tests", type=int, default=3,
        help="Number of oracle tests to generate (default: 3)",
    )
    ap.add_argument(
        "--skip-eval", action="store_true",
        help="Skip the pytest evaluation steps (useful for quick smoke tests)",
    )
    ap.add_argument(
        "--max-validate-attempts", type=int, default=3,
        help="Max test generation+validation retries (default: 3)",
    )
    args = ap.parse_args()

    run_demo(
        repo=args.repo,
        n_tests=args.n_tests,
        skip_eval=args.skip_eval,
        max_validate_attempts=args.max_validate_attempts,
    )


if __name__ == "__main__":
    main()
