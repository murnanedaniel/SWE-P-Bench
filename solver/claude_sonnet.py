"""
Claude Sonnet file-context solver for SWE-P-Bench.

Uses the ``claude`` CLI (subscription-based, no API key) instead of the
OpenAI SDK.  Reuses prompt templates, source-context fetching, and patch
normalisation from ``solver.gpt5_mini``.

Usage:
    python scripts/03_solve.py \\
        --dataset data/scikit-hep/particle/candidates_filtered.jsonl \\
        --solver claude_sonnet --attempts 1 --workers 1

Output:
    results/claude_sonnet_1shot/{owner}/{name}/{instance_id}.patch

No environment variables required — authenticates via your Claude Code
subscription.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

from llm.claude_cli import claude_chat
from solver.gpt5_mini import (
    _SYSTEM_PROMPTS,
    _SYSTEM_PYTHON,
    _normalize_patch,
    build_prompt,
    fetch_source_context,
)

MODEL = "sonnet"  # claude CLI alias


def solve_instance(
    instance: dict,
    repo_config: dict | None = None,
    max_attempts: int = 1,
    model: str = MODEL,
) -> str:
    """Call Claude via CLI and return the predicted patch string (normalised).

    Fetches source files at base_commit for context. Degrades gracefully
    to zero-context if fetching fails.
    """
    lang = (repo_config or {}).get("language", "python")
    system = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PYTHON)

    ctx = fetch_source_context(instance)
    user_prompt = build_prompt(instance, source_context=ctx)

    for attempt in range(1, max_attempts + 1):
        try:
            raw = claude_chat(
                system_prompt=system,
                user_prompt=user_prompt,
                model=model,
            )
            patch = _normalize_patch(raw)
            if patch.strip():
                return patch
            if attempt < max_attempts:
                print(
                    f"  [attempt {attempt}/{max_attempts}] empty patch, retrying…",
                    file=sys.stderr,
                )
        except Exception as exc:
            if attempt == max_attempts:
                raise
            print(
                f"  [attempt {attempt}/{max_attempts}] error: {exc}, retrying…",
                file=sys.stderr,
            )

    return ""


def solve_dataset(
    dataset_path: str,
    out_dir: str,
    max_instances: int = 0,
    repos_yml: str = "repos.yml",
    max_attempts: int = 1,
    workers: int = 1,
) -> None:
    """Solve all instances sequentially using Claude CLI.

    workers parameter is accepted for interface compatibility with
    03_solve.py but concurrency > 1 is not recommended for subscription
    CLI calls.
    """
    from scraper.generic import load_repo_config

    if workers > 1:
        print(
            f"  [warning] Claude CLI solver works best with workers=1 "
            f"(got {workers}). Running sequentially.",
            file=sys.stderr,
        )

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

    # Skip already-solved instances
    instances = [i for i in instances if not (out / f"{i['instance_id']}.patch").exists()]

    print(f"Solving {len(instances)} instances with Claude {MODEL}…")

    with open(predictions_path, "a") as pred_f:
        for inst in tqdm(instances, unit="instance"):
            iid = inst["instance_id"]

            repo_cfg = load_repo_config(inst.get("repo", ""), config_path=repos_yml)

            try:
                patch = solve_instance(
                    inst, repo_config=repo_cfg, max_attempts=max_attempts
                )
            except Exception as e:
                print(f"  [error] {iid}: {e}", file=sys.stderr)
                patch = ""

            patch_file = out / f"{iid}.patch"
            patch_file.write_text(patch)

            pred_f.write(
                json.dumps({
                    "instance_id": iid,
                    "model": f"claude-{MODEL}",
                    "patch": patch,
                })
                + "\n"
            )
            pred_f.flush()

    print(f"Predictions written to {predictions_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Sonnet solver for SWE-P-Bench")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", default="results/claude_sonnet_1shot/")
    parser.add_argument("--max-instances", type=int, default=0)
    parser.add_argument("--repos-yml", default="repos.yml")
    parser.add_argument("--model", default=MODEL,
                        help="Claude model alias (sonnet, opus, haiku)")
    args = parser.parse_args()

    solve_dataset(
        dataset_path=args.dataset,
        out_dir=args.out,
        max_instances=args.max_instances,
        repos_yml=args.repos_yml,
    )


if __name__ == "__main__":
    main()
