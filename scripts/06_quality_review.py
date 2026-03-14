"""
scripts/06_quality_review.py — Quality review for gold-passing SWE-P-Bench instances.

For each instance where the gold patch passes oracle tests, calls Claude to
review the (issue, PR diff, oracle tests) triplet and scores it on three axes:
  - CAUSAL_CONNECTION: Does the PR directly fix what the issue describes?
  - TEST_RELEVANCE:    Do the tests test the behaviour from the issue?
  - TEST_ROBUSTNESS:   Are the tests deterministic and testing observable behaviour?

Instances with all scores >= 3 and average >= 3.5 are accepted.

Input:
  - candidates_filtered.jsonl (instances)
  - data/{owner}/{name}/oracles/{instance_id}.py (oracle code)
  - results/gold/evals/{owner}/{name}/{instance_id}.json (gold eval results)

Output:
  - data/{owner}/{name}/candidates_reviewed.jsonl

Usage:
    python scripts/06_quality_review.py \\
        --dataset data/scikit-hep/particle/candidates_filtered.jsonl \\
        [--model claude:sonnet] [--results-dir results/]

Idempotent: skips instances already present in the output file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# Ensure project root is on sys.path so ``llm`` package is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

_DEFAULT_MODEL = "claude:sonnet"

_REVIEW_SYSTEM = """\
You are a benchmark quality assessor for SWE-P-Bench, a software engineering \
benchmark. You will be shown a GitHub issue, the gold patch (PR diff) that \
resolved it, and a set of oracle test functions. Your job is to assess whether \
this triplet forms a high-quality benchmark instance.

Rate on three axes (1–5 each):

CAUSAL_CONNECTION: Does the PR directly fix what the issue describes?
  5 — PR is a precise fix for the issue, nothing more.
  3 — PR fixes the issue but includes unrelated changes.
  1 — PR is only loosely related to the issue.

TEST_RELEVANCE: Do the oracle tests actually test the behaviour described in the issue?
  5 — Tests directly exercise the exact bug/feature from the issue.
  3 — Tests are related but test adjacent behaviour or implementation details.
  1 — Tests are coincidental — they pass/fail for reasons unrelated to the issue.

TEST_ROBUSTNESS: Are the tests deterministic, self-contained, and testing observable behaviour?
  5 — Fully deterministic, no external dependencies, clear assertions on outputs.
  3 — Mostly good but relies on some implementation details or fragile comparisons.
  1 — Flaky, depends on timing/randomness/external state, or tests internal structure.

Output ONLY valid JSON in this exact format:
{
  "causal_connection": <int 1-5>,
  "test_relevance": <int 1-5>,
  "test_robustness": <int 1-5>,
  "accept": <bool>,
  "reason": "<one sentence explaining your decision>"
}

Set "accept" to true if ALL scores are >= 3 AND the average is >= 3.5.
"""

_REVIEW_TEMPLATE = """\
## Issue
{issue}

## Gold Patch (the merged fix)
```diff
{patch}
```

## Oracle Tests
```python
{oracle_code}
```

Assess this benchmark instance.
"""


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _review_instance(instance: dict, oracle_code: str, model: str) -> dict:
    """Call Claude to review the triplet and return quality scores."""
    issue = instance.get("problem_statement", "").strip()[:4000]
    patch = instance.get("patch", "")[:6000]

    prompt = _REVIEW_TEMPLATE.format(
        issue=issue, patch=patch, oracle_code=oracle_code
    )

    if model.startswith("claude:"):
        from llm.claude_cli import claude_chat

        raw = claude_chat(
            system_prompt=_REVIEW_SYSTEM,
            user_prompt=prompt,
            model=model.split(":", 1)[1],
        )
    else:
        import os

        from openai import OpenAI

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_completion_tokens=300,
        )
        raw = (response.choices[0].message.content or "").strip()

    # Parse JSON from response (may be wrapped in markdown fences)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {
            "causal_connection": 0,
            "test_relevance": 0,
            "test_robustness": 0,
            "accept": False,
            "reason": f"Failed to parse review response: {raw[:200]}",
        }

    try:
        result = json.loads(m.group())
    except json.JSONDecodeError:
        return {
            "causal_connection": 0,
            "test_relevance": 0,
            "test_robustness": 0,
            "accept": False,
            "reason": f"Invalid JSON in review response: {raw[:200]}",
        }

    # Validate and enforce acceptance criteria
    scores = [
        result.get("causal_connection", 0),
        result.get("test_relevance", 0),
        result.get("test_robustness", 0),
    ]
    avg = sum(scores) / len(scores) if scores else 0
    result["accept"] = all(s >= 3 for s in scores) and avg >= 3.5

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quality review for gold-passing SWE-P-Bench instances"
    )
    parser.add_argument(
        "--dataset", required=True, help="Path to candidates_filtered.jsonl"
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help="LLM model for review (default: claude:sonnet)",
    )
    parser.add_argument(
        "--results-dir",
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
        print("No instances found.", file=sys.stderr)
        sys.exit(1)

    repo = instances[0].get("repo", "unknown/unknown")
    owner, name = (repo.split("/", 1) + ["unknown"])[:2]

    oracle_dir = dataset_path.parent / "oracles"
    gold_eval_dir = Path(args.results_dir) / "gold" / "evals" / owner / name
    out_path = dataset_path.parent / "candidates_reviewed.jsonl"

    # Load already-reviewed instances (idempotency)
    reviewed: dict[str, dict] = {}
    if out_path.exists():
        for rec in load_jsonl(str(out_path)):
            reviewed[rec["instance_id"]] = rec

    # Filter to gold-passing instances with oracles
    to_review: list[tuple[dict, str]] = []  # (instance, oracle_code)
    skipped_no_oracle = 0
    skipped_not_resolved = 0

    for inst in instances:
        iid = inst["instance_id"]
        if iid in reviewed:
            continue

        # Check gold eval result
        eval_path = gold_eval_dir / f"{iid}.json"
        if not eval_path.exists():
            skipped_not_resolved += 1
            continue
        eval_result = json.loads(eval_path.read_text())
        if not eval_result.get("resolved"):
            skipped_not_resolved += 1
            continue

        # Load oracle code
        oracle_path = oracle_dir / f"{iid}.py"
        if not oracle_path.exists():
            skipped_no_oracle += 1
            continue

        to_review.append((inst, oracle_path.read_text()))

    print(
        f"{dataset_path}: {len(instances)} total, "
        f"{len(reviewed)} already reviewed, {len(to_review)} to review, "
        f"{skipped_not_resolved} not gold-resolved, {skipped_no_oracle} missing oracle"
    )

    if not to_review:
        print("Nothing to review.")
        return

    new_results: list[dict] = []
    for inst, oracle_code in tqdm(to_review, unit="instance"):
        iid = inst["instance_id"]
        try:
            quality = _review_instance(inst, oracle_code, args.model)
        except Exception as exc:
            print(f"  [error] {iid}: {exc}", file=sys.stderr)
            quality = {
                "causal_connection": 0,
                "test_relevance": 0,
                "test_robustness": 0,
                "accept": False,
                "reason": f"Review failed: {exc}",
            }

        rec = dict(inst)
        rec["quality_causal"] = quality["causal_connection"]
        rec["quality_relevance"] = quality["test_relevance"]
        rec["quality_robustness"] = quality["test_robustness"]
        rec["quality_accept"] = quality["accept"]
        rec["quality_reason"] = quality.get("reason", "")
        rec["quality_avg"] = round(
            (quality["causal_connection"] + quality["test_relevance"] + quality["test_robustness"]) / 3,
            2,
        )
        new_results.append(rec)

        status = "ACCEPT" if quality["accept"] else "REJECT"
        scores = f"C={quality['causal_connection']} R={quality['test_relevance']} B={quality['test_robustness']}"
        print(f"  {iid}: {status} ({scores}) — {quality.get('reason', '')}", file=sys.stderr)

    # Merge with previously reviewed and write
    all_reviewed = list(reviewed.values()) + new_results
    order = {inst["instance_id"]: i for i, inst in enumerate(instances)}
    all_reviewed.sort(key=lambda r: order.get(r["instance_id"], 9999))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for rec in all_reviewed:
            f.write(json.dumps(rec) + "\n")

    accepted = sum(1 for r in all_reviewed if r.get("quality_accept"))
    total = len(all_reviewed)
    print(
        f"\nWrote {total} reviewed instances to {out_path} "
        f"({accepted} accepted, {total - accepted} rejected)"
    )


if __name__ == "__main__":
    main()
