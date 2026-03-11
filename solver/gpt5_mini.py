"""
GPT-5-mini baseline solver for SWE-P-Bench.

Given a dataset of benchmark instances, this solver asks OpenAI's
gpt-5-mini model to produce a unified diff patch that resolves the
described issue, using only the problem statement (and optionally hints).

The prompt strategy is deliberately minimal (no retrieval, no repository
context beyond what's in the issue) so it establishes a true zero-context
baseline. Future solvers can add RAG, repo browsing, agentic tool-use, etc.

Usage:
    python -m solver.gpt4o_mini \
        --dataset data/acts/candidates.jsonl \
        --out results/gpt4o_mini/

Output:
    results/gpt4o_mini/<instance_id>.patch   — raw predicted patch
    results/gpt4o_mini/predictions.jsonl     — structured predictions

Environment:
    OPENAI_API_KEY  OpenAI API key
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

load_dotenv()

MODEL = "gpt-5-mini"

SYSTEM_PROMPT = """\
You are an expert C++ software engineer working on the ACTS project \
(A Common Tracking Software for high-energy physics experiments).

Your task: given a GitHub issue description, produce a minimal unified diff \
patch (git diff format) that resolves the issue in the ACTS codebase.

Rules:
- Output ONLY the raw unified diff, nothing else.
- Do not include explanations, prose, or code fences.
- The diff must apply cleanly with `patch -p1`.
- Keep changes minimal — fix only what the issue describes.
- Match the existing code style (C++17/20, camelCase, ACTS conventions).
- If you cannot determine the exact file paths, make your best guess based \
  on the issue description and ACTS project conventions.
"""

USER_TEMPLATE = """\
## Issue

{problem_statement}

{hints_section}

## Task

Produce a unified diff patch that resolves this issue in the ACTS repository \
(https://github.com/acts-project/acts). Output only the raw diff.
"""


def build_prompt(instance: dict) -> str:
    hints = instance.get("hints_text", "").strip()
    hints_section = f"## Hints / Discussion\n\n{hints}" if hints else ""
    return USER_TEMPLATE.format(
        problem_statement=instance["problem_statement"],
        hints_section=hints_section,
    ).strip()


def solve_instance(client: OpenAI, instance: dict, temperature: float = 0.2) -> str:
    """Call the model and return the predicted patch string."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(instance)},
        ],
        max_completion_tokens=8000,  # reasoning model: budget covers reasoning+output
    )
    return response.choices[0].message.content or ""


def solve_dataset(
    dataset_path: str,
    out_dir: str,
    max_instances: int = 0,
    temperature: float = 0.2,
) -> None:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    predictions_path = out / "predictions.jsonl"

    # Load dataset
    instances: list[dict] = []
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    if max_instances:
        instances = instances[:max_instances]

    print(f"Solving {len(instances)} instances with {MODEL}…")

    with open(predictions_path, "a") as pred_f:
        for inst in tqdm(instances, unit="instance"):
            iid = inst["instance_id"]
            patch_file = out / f"{iid}.patch"

            # Skip if already solved
            if patch_file.exists():
                continue

            try:
                patch = solve_instance(client, inst, temperature=temperature)
            except Exception as e:
                print(f"  [error] {iid}: {e}", file=sys.stderr)
                patch = ""

            # Write individual patch file
            patch_file.write_text(patch)

            # Append to predictions JSONL
            pred_f.write(json.dumps({
                "instance_id": iid,
                "model": MODEL,
                "patch": patch,
            }) + "\n")
            pred_f.flush()

    print(f"Predictions written to {predictions_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GPT-4o-mini solver for SWE-P-Bench")
    parser.add_argument("--dataset", default="data/acts/candidates.jsonl")
    parser.add_argument("--out", default="results/gpt4o_mini/")
    parser.add_argument("--max-instances", type=int, default=0,
                        help="Limit instances solved (0 = all)")
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    solve_dataset(
        dataset_path=args.dataset,
        out_dir=args.out,
        max_instances=args.max_instances,
        temperature=args.temperature,
    )


if __name__ == "__main__":
    main()
