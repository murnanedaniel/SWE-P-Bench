"""
GPT-5-mini baseline solver for SWE-P-Bench.

Given a dataset of benchmark instances, this solver asks OpenAI's
gpt-5-mini model to produce a unified diff patch that resolves the
described issue, using only the problem statement (and optionally hints).

The prompt strategy is deliberately minimal (no retrieval, no repository
context beyond what's in the issue) so it establishes a true zero-context
baseline. Future solvers can add RAG, repo browsing, agentic tool-use, etc.

Language-aware: uses `repos.yml` (via `scraper.generic.load_repo_config`) to
detect whether the repo is Python or C++ and selects the appropriate system
prompt. Defaults to Python if no config is found.

Usage:
    python -m solver.gpt5_mini \\
        --dataset data/scikit-hep/awkward/candidates.jsonl \\
        --out results/gpt5_mini/

Output:
    results/gpt5_mini/<instance_id>.patch   — raw predicted patch
    results/gpt5_mini/predictions.jsonl     — structured predictions

Environment:
    OPENAI_API_KEY  OpenAI API key
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
from tqdm import tqdm

load_dotenv()

MODEL = "gpt-5-mini"

# ---------------------------------------------------------------------------
# Language-aware system prompts
# ---------------------------------------------------------------------------

_SYSTEM_PYTHON = """\
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

_SYSTEM_CPP = """\
You are an expert C++ software engineer working on the ACTS project \
(A Common Tracking Software for high-energy physics experiments).

Your task: given a GitHub issue description, produce a minimal unified diff \
patch (git diff format) that resolves the issue in the ACTS codebase.

Rules:
- Output ONLY the raw unified diff, nothing else.
- Do not include explanations, prose, or code fences.
- The diff must apply cleanly with `git apply` or `patch -p1`.
- Keep changes minimal — fix only what the issue describes.
- Match the existing code style (C++17/20, camelCase, ACTS conventions).
- If you cannot determine the exact file paths, make your best guess based \
  on the issue description and ACTS project conventions.
"""

_SYSTEM_PROMPTS: dict[str, str] = {
    "python": _SYSTEM_PYTHON,
    "cpp": _SYSTEM_CPP,
}

USER_TEMPLATE = """\
## Repository
{repo}

## Issue

{problem_statement}

{hints_section}

## Task

Produce a unified diff patch that resolves this issue. Output only the raw diff.
"""


# ---------------------------------------------------------------------------
# "*** Begin Patch" normaliser (Issue #18)
# ---------------------------------------------------------------------------

def _normalize_patch(patch: str) -> str:
    """
    Convert the OpenAI reasoning-model "*** Begin Patch" format to standard
    unified diff, if necessary.  Returns *patch* unchanged if it is already
    in unified diff format or in an unrecognised format.

    The "*** Begin Patch" format looks like::

        *** Begin Patch
        *** Update File: path/to/file.py
        @@@ line_number
         context
        -removed
        +added
         context
        *** End Patch

    We convert each ``*** Update File`` section into a ``diff --git`` header
    followed by ``--- a/…`` / ``+++ b/…`` lines and the hunk(s) verbatim.
    """
    stripped = patch.strip()
    if not stripped.startswith("*** Begin Patch"):
        return patch  # already standard unified diff (or empty)

    lines = stripped.splitlines()
    out: list[str] = []
    current_file: str | None = None
    in_hunk = False

    for line in lines:
        if line.startswith("*** Begin Patch") or line.startswith("*** End Patch"):
            continue
        if line.startswith("*** Update File:"):
            current_file = line[len("*** Update File:"):].strip()
            out.append(f"diff --git a/{current_file} b/{current_file}")
            out.append(f"--- a/{current_file}")
            out.append(f"+++ b/{current_file}")
            in_hunk = False
            continue
        if line.startswith("*** Add File:"):
            current_file = line[len("*** Add File:"):].strip()
            out.append(f"diff --git a/{current_file} b/{current_file}")
            out.append("new file mode 100644")
            out.append(f"--- /dev/null")
            out.append(f"+++ b/{current_file}")
            in_hunk = False
            continue
        if line.startswith("*** Delete File:"):
            current_file = line[len("*** Delete File:"):].strip()
            out.append(f"diff --git a/{current_file} b/{current_file}")
            out.append("deleted file mode 100644")
            out.append(f"--- a/{current_file}")
            out.append("+++ /dev/null")
            in_hunk = False
            continue
        if line.startswith("@@@"):
            # Convert "@@@" hunk marker to standard "@@ … @@"
            # The format is "@@@" optionally followed by line number info
            # We emit a generic hunk header; git apply is tolerant of line offsets.
            rest = line[3:].strip()
            if rest:
                out.append(f"@@ -{rest},0 +{rest},0 @@")
            else:
                out.append("@@ -1 +1 @@")
            in_hunk = True
            continue
        if current_file is not None:
            # Pass diff lines through; lines not starting with +/-/space get a space
            if line and line[0] not in ("+", "-", " ", "\\"):
                out.append(" " + line)
            else:
                out.append(line)

    return "\n".join(out) + "\n" if out else patch


# ---------------------------------------------------------------------------
# Core solver
# ---------------------------------------------------------------------------

def build_prompt(instance: dict) -> str:
    hints = instance.get("hints_text", "").strip()
    hints_section = f"## Hints / Discussion\n\n{hints}" if hints else ""
    return USER_TEMPLATE.format(
        repo=instance.get("repo", ""),
        problem_statement=instance["problem_statement"],
        hints_section=hints_section,
    ).strip()


def solve_instance(
    client: OpenAI,
    instance: dict,
    repo_config: dict | None = None,
) -> str:
    """Call the model and return the predicted patch string (normalised)."""
    lang = (repo_config or {}).get("language", "python")
    system = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PYTHON)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": build_prompt(instance)},
        ],
        max_completion_tokens=8000,  # reasoning model: budget covers reasoning+output
    )
    raw = response.choices[0].message.content or ""
    return _normalize_patch(raw)


def solve_dataset(
    dataset_path: str,
    out_dir: str,
    max_instances: int = 0,
    repos_yml: str = "repos.yml",
) -> None:
    from scraper.generic import load_repo_config

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    predictions_path = out / "predictions.jsonl"

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

            if patch_file.exists():
                continue

            repo_cfg = load_repo_config(inst.get("repo", ""), config_path=repos_yml)

            try:
                patch = solve_instance(client, inst, repo_config=repo_cfg)
            except Exception as e:
                print(f"  [error] {iid}: {e}", file=sys.stderr)
                patch = ""

            patch_file.write_text(patch)

            pred_f.write(json.dumps({
                "instance_id": iid,
                "model": MODEL,
                "patch": patch,
            }) + "\n")
            pred_f.flush()

    print(f"Predictions written to {predictions_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GPT-5-mini solver for SWE-P-Bench")
    parser.add_argument("--dataset", required=True,
                        help="Path to JSONL dataset of instances")
    parser.add_argument("--out", default="results/gpt5_mini/")
    parser.add_argument("--max-instances", type=int, default=0,
                        help="Limit instances solved (0 = all)")
    parser.add_argument("--repos-yml", default="repos.yml",
                        help="Path to repos.yml config (default: repos.yml)")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    solve_dataset(
        dataset_path=args.dataset,
        out_dir=args.out,
        max_instances=args.max_instances,
        repos_yml=args.repos_yml,
    )


if __name__ == "__main__":
    main()
