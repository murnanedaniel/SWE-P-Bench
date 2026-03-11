#!/usr/bin/env python3
"""
SWE-P-Bench — End-to-End Demo

Demonstrates the full benchmark pipeline on one issue-PR pair from a
Python HEP repo (default: scikit-hep/awkward):

  1. SCRAPE   — find the first valid issue-PR pair (uses scraper/acts.py logic).
  2. GENERATE — write N oracle tests with GPT-5-mini (knows the gold patch).
  3. SOLVE    — generate a predicted patch with GPT-5-mini (sees issue only).
  4. EVALUATE — run pytest before/after the predicted patch.
  5. BONUS    — also evaluate the gold patch to sanity-check the oracle tests.

Results are saved under data/demo/.

Usage:
    python run_demo.py [--repo OWNER/NAME] [--n-tests N] [--skip-eval]

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

# Local imports
from scraper.acts import (
    GITHUB_API,
    _Cache,
    _get,
    _find_closing_prs,
    _fetch_pr_diff,
    _has_src_changes,
    _paginate,
    _session,
    _split_diff,
)
from test_writer.generator import generate_oracle_tests
from evaluator.python_harness import evaluate_python_instance

load_dotenv()

# ---------------------------------------------------------------------------
# Python-specific solver prompt (the existing solver/gpt5_mini.py is ACTS/C++)
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
- If you cannot determine exact file paths, make your best guess based on the \
  issue description and common Python project conventions (src/ layout, etc.).
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
        max_completion_tokens=8000,  # reasoning model: budget covers reasoning+output
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Quick single-instance scraper (stops at first valid instance)
# ---------------------------------------------------------------------------

def scrape_first_instance(
    repo: str,
    token: str | None = None,
    cache_dir: str = ".scraper_cache",
    max_issues: int = 300,
) -> dict | None:
    """
    Scan closed issues (most-recently-updated first) and return the first
    instance that has a merged PR with source-file changes.
    Checks at most *max_issues* issues to stay fast.
    """
    session = _session(token)
    cache = _Cache(cache_dir)
    owner, name = repo.split("/")

    print(f"Scanning {repo} for a valid issue-PR pair …", file=sys.stderr)
    url = f"{GITHUB_API}/repos/{repo}/issues"
    checked = 0

    for item in _paginate(
        session, url,
        {"state": "closed", "sort": "updated", "direction": "desc"},
    ):
        if checked >= max_issues:
            break
        if item.get("pull_request"):
            continue   # issues endpoint also returns PRs
        checked += 1

        issue_num = item["number"]
        issue_title = item.get("title", "")

        # --- timeline: find closing PRs ---
        ck_tl = f"timeline_{owner}_{name}_{issue_num}"
        closing_prs: list[int] | None = cache.get(ck_tl)
        if closing_prs is None:
            closing_prs = _find_closing_prs(session, repo, issue_num)
            cache.set(ck_tl, closing_prs)
        if not closing_prs:
            continue

        pr_num = closing_prs[0]

        # --- diff ---
        ck_diff = f"diff_{owner}_{name}_{pr_num}"
        diff: str | None = cache.get(ck_diff)
        if diff is None:
            diff = _fetch_pr_diff(session, repo, pr_num)
            cache.set(ck_diff, diff or "")
        if not diff or not _has_src_changes(diff):
            continue

        code_patch, test_patch = _split_diff(diff)
        if not code_patch.strip():
            continue

        # --- PR metadata ---
        ck_pr = f"pr_{owner}_{name}_{pr_num}"
        pr_meta: dict | None = cache.get(ck_pr)
        if pr_meta is None:
            pr_meta = _get(session, f"{GITHUB_API}/repos/{repo}/pulls/{pr_num}") or {}
            cache.set(ck_pr, pr_meta)
        if not pr_meta.get("merged_at"):
            continue

        # --- hints (issue comments before the PR) ---
        pr_created = pr_meta.get("created_at", "")
        ck_hints = f"hints_{owner}_{name}_{issue_num}_{pr_created[:10]}"
        hints: str | None = cache.get(ck_hints)
        if hints is None:
            texts = [
                c["body"] or ""
                for c in _paginate(
                    session,
                    f"{GITHUB_API}/repos/{repo}/issues/{issue_num}/comments",
                )
                if c.get("created_at", "") < pr_created
            ]
            hints = "\n\n".join(texts)
            cache.set(ck_hints, hints)

        instance_id = f"{owner}__{name}-{issue_num}"
        problem_statement = f"{item['title']}\n\n{item.get('body') or ''}".strip()

        print(
            f"  Found: #{issue_num} '{issue_title}' -> PR #{pr_num}",
            file=sys.stderr,
        )
        return {
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": pr_meta.get("base", {}).get("sha", ""),
            "problem_statement": problem_statement,
            "hints_text": hints,
            "patch": code_patch,
            "test_patch": test_patch,
            "FAIL_TO_PASS": [],
            "PASS_TO_PASS": [],
            "created_at": item.get("created_at", ""),
            "pr_number": pr_num,
            "issue_number": issue_num,
            "pr_url": pr_meta.get("html_url", ""),
            "issue_url": item.get("html_url", ""),
            "labels": [lb["name"] for lb in item.get("labels", [])],
            "pr_additions": pr_meta.get("additions", 0),
            "pr_deletions": pr_meta.get("deletions", 0),
            "pr_changed_files": pr_meta.get("changed_files", 0),
        }

    print(
        f"  No valid instance in first {max_issues} issues.",
        file=sys.stderr,
    )
    return None


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def run_demo(
    repo: str = "scikit-hep/awkward",
    n_tests: int = 3,
    skip_eval: bool = False,
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
                "WARNING: GITHUB_TOKEN not set — scraping rate-limited to 60 req/hr.",
                file=sys.stderr,
            )
        instance = scrape_first_instance(repo, token=token)
        if instance is None:
            print("ERROR: Could not find a valid instance.", file=sys.stderr)
            sys.exit(1)
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
    print("STEP 2 — GENERATING ORACLE TESTS (GPT-5-mini)")
    print(sep)

    oracle_file = demo_dir / "oracle_tests.py"
    if oracle_file.exists():
        print(f"Loading cached oracle tests from {oracle_file}")
        oracle_code = oracle_file.read_text()
        test_names = re.findall(r"^def (test_\w+)", oracle_code, re.MULTILINE)
    else:
        oracle_code, test_names = generate_oracle_tests(
            instance, n=n_tests, model="gpt-5-mini"
        )
        oracle_file.write_text(oracle_code)

    print(f"\nGenerated functions: {test_names}")
    print(f"\nOracle test code:\n{'-'*40}")
    print(oracle_code)
    print("-" * 40)

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
    print(
        "This clones the repo, pip-installs it, then runs pytest before/after."
    )

    pred_result = evaluate_python_instance(instance, oracle_code, predicted_patch)
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

    # ------------------------------------------------------------------ 5
    print(f"\n{sep}")
    print("STEP 5 — EVALUATING GOLD PATCH (sanity check)")
    print(sep)
    print("Verifying that the oracle tests correctly detect the gold fix.")

    gold_result = evaluate_python_instance(instance, oracle_code, instance["patch"])
    (demo_dir / "eval_gold.json").write_text(json.dumps(gold_result, indent=2))

    print(f"\n--- Gold patch results ---")
    print(f"Resolved   : {gold_result['resolved']}")
    print(f"FAIL→PASS  : {gold_result['FAIL_TO_PASS']}")
    print(f"Before     : {gold_result['before_results']}")
    print(f"After      : {gold_result['after_results']}")
    if gold_result.get("error"):
        print(f"Error      : {gold_result['error']}")

    # ------------------------------------------------------------------ summary
    print(f"\n{sep}")
    print("SUMMARY")
    print(sep)
    oracle_quality = (
        "✓ GOOD (gold patch resolves oracle tests)"
        if gold_result["resolved"]
        else "✗ POOR (gold patch does NOT resolve oracle tests — tests may be wrong)"
    )
    solver_quality = (
        "✓ RESOLVED" if pred_result["resolved"] else "✗ NOT RESOLVED"
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
    args = ap.parse_args()

    run_demo(repo=args.repo, n_tests=args.n_tests, skip_eval=args.skip_eval)


if __name__ == "__main__":
    main()
