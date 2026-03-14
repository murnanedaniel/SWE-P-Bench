"""
scripts/01b_filter.py — Quality filter for scraped SWE-P-Bench instances.

Reads a ``candidates.jsonl`` produced by ``01_scrape.py`` and outputs a
``candidates_filtered.jsonl`` that excludes instances likely to produce
unfair or unresolvable benchmark tasks.

Two filters are applied in order:

Filter A — Data-entry (free, heuristic):
    Discards instances where the gold patch is primarily bulk data additions
    (e.g. adding rows to a CSV). These tasks require authoritative external
    data that no LLM can infer from the issue description.

    Signal: (fraction of changed files that are data files > 0.4) AND
            (added lines / total changed lines > 0.85)

Filter B — LLM relevance score (one call per instance):
    Discards instances where the merged PR addresses something substantially
    different from what the issue describes (e.g. issue says "add tests" but
    PR fixes an unrelated bug; issue says "add docs" but PR also renames a
    public attribute).

    Score 0–10; instances scoring < ``--min-score`` (default 6) are discarded.

    Supports two backends:
      - OpenAI API (models: gpt-5.4, etc.) — requires OPENAI_API_KEY
      - Claude CLI (models: claude:sonnet, claude:opus) — uses subscription

Usage:
    python scripts/01b_filter.py \\
        --dataset data/scikit-hep/particle/candidates.jsonl \\
        [--out data/scikit-hep/particle/candidates_filtered.jsonl] \\
        [--min-score 6] [--model claude:sonnet]

The output JSONL has the same fields as the input plus three extra fields
per record:
    filter_data_entry:      bool  — True if the data-entry heuristic fired
    filter_relevance_score: int   — 0–10 relevance score (−1 if not scored)
    filter_pass:            bool  — True if the instance passes both filters

Idempotent: if the output file already exists, only instances not yet scored
(by instance_id) are processed and the results are merged back.

Environment:
    OPENAI_API_KEY  Required for Filter B (OpenAI backend only)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# Ensure project root is on sys.path so ``llm`` package is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Filter A — data-entry heuristic
# ---------------------------------------------------------------------------

_DATA_EXTS = {".csv", ".json", ".fwf", ".tsv", ".txt", ".yaml", ".yml"}


def _data_entry_score(patch: str) -> bool:
    """Return True if the patch looks like a bulk data-entry task."""
    changed_files = re.findall(r"^diff --git a/(\S+)", patch, re.MULTILINE)
    if not changed_files:
        return True  # empty patch — nothing to solve

    data_files = [f for f in changed_files if Path(f).suffix in _DATA_EXTS]
    data_frac = len(data_files) / len(changed_files)

    added = len(re.findall(r"^\+(?!\+\+)", patch, re.MULTILINE))
    removed = len(re.findall(r"^-(?!--)", patch, re.MULTILINE))
    total = added + removed or 1
    addition_ratio = added / total

    return data_frac > 0.4 and addition_ratio > 0.85


# ---------------------------------------------------------------------------
# Filter B — LLM relevance score
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "claude:sonnet"

_RELEVANCE_SYSTEM = (
    "You are a benchmark quality assessor. "
    "Your job is to rate how directly a merged diff addresses a stated GitHub issue."
)

_RELEVANCE_TEMPLATE = """\
Below is a GitHub issue and a summary of the diff that was merged to resolve it.

## Issue
{issue}

## Diff summary (changed files and net line counts)
{diff_summary}

Rate on a scale of 0–10 how directly this diff addresses the stated issue.

Scoring guide:
  10 — Diff changes exactly what the issue describes, nothing more or less.
   7 — Diff fixes the issue plus minor cleanup (e.g. formatting, unrelated typo).
   5 — Diff fixes the issue but also makes unrelated changes (refactor, rename,
       feature bundled alongside the fix).
   2 — Diff is only loosely related (e.g. issue says "add tests", diff fixes a bug).
   0 — Diff is unrelated to the issue entirely.

Output ONLY a single integer 0–10. No explanation, no prose.
"""


def _make_diff_summary(patch: str) -> str:
    """Compact per-file summary: 'path (+N/-M)' per changed file."""
    sections = re.split(r"^diff --git ", patch, flags=re.MULTILINE)
    lines = []
    for sec in sections[1:]:  # skip preamble
        header = sec.splitlines()[0]
        path_m = re.match(r"a/(\S+) b/", header)
        path = path_m.group(1) if path_m else header
        added = len(re.findall(r"^\+(?!\+\+)", sec, re.MULTILINE))
        removed = len(re.findall(r"^-(?!--)", sec, re.MULTILINE))
        lines.append(f"  {path}  (+{added}/-{removed})")
    return "\n".join(lines) if lines else "(no files changed)"


def _score_relevance(instance: dict, model: str) -> int:
    """Call the LLM and return a 0–10 relevance integer (−1 on failure)."""
    issue = instance.get("problem_statement", "").strip()[:3000]  # cap for cost
    diff_summary = _make_diff_summary(instance.get("patch", ""))

    prompt = _RELEVANCE_TEMPLATE.format(issue=issue, diff_summary=diff_summary)
    try:
        if model.startswith("claude:"):
            from llm.claude_cli import claude_chat

            raw = claude_chat(
                system_prompt=_RELEVANCE_SYSTEM,
                user_prompt=prompt,
                model=model.split(":", 1)[1],
            )
        else:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _RELEVANCE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_completion_tokens=10,
            )
            raw = (response.choices[0].message.content or "").strip()

        m = re.search(r"\d+", raw)
        return int(m.group()) if m else -1
    except Exception as exc:
        print(f"  [warning] relevance score failed for {instance.get('instance_id')}: {exc}",
              file=sys.stderr)
        return -1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_filter(
    dataset_path: str,
    out_path: str,
    min_score: int = 6,
    model: str = _DEFAULT_MODEL,
) -> None:
    use_claude = model.startswith("claude:")
    if not use_claude and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            f"Model '{model}' requires OPENAI_API_KEY. "
            "Set the env var or use --model claude:sonnet"
        )

    # Load all instances
    instances: list[dict] = []
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    # Load already-scored instances for idempotency.
    # Check candidates_scored.jsonl first (has ALL results including failures),
    # then fall back to the filtered output file.
    scored: dict[str, dict] = {}
    out = Path(out_path)
    scored_path = out.parent / "candidates_scored.jsonl"
    for cache_file in [scored_path, out]:
        if cache_file.exists():
            with open(cache_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        iid = rec.get("instance_id")
                        if iid and iid not in scored:
                            scored[iid] = rec

    to_process = [i for i in instances if i["instance_id"] not in scored]
    print(
        f"{dataset_path}: {len(instances)} total, "
        f"{len(scored)} already filtered, {len(to_process)} to process"
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out_scored = out.parent / "candidates_scored.jsonl"

    # Append each result to candidates_scored.jsonl as we go, so progress
    # survives interruptions.
    for inst in tqdm(to_process, unit="instance"):
        iid = inst["instance_id"]
        patch = inst.get("patch", "")

        # Filter A
        is_data = _data_entry_score(patch)

        # Filter B (only call LLM if not already discarded by A)
        if is_data:
            score = -1  # skip LLM for clear data-entry cases
        else:
            score = _score_relevance(inst, model)

        passes = (not is_data) and (score == -1 or score >= min_score)

        rec = dict(inst)
        rec["filter_data_entry"] = is_data
        rec["filter_relevance_score"] = score
        rec["filter_pass"] = passes
        scored[iid] = rec

        # Append immediately so we don't lose progress on interruption
        with open(out_scored, "a") as f:
            f.write(json.dumps(rec) + "\n")

        status = "PASS" if passes else f"FAIL(data={is_data},score={score})"
        print(f"  {iid}: {status}", file=sys.stderr)

    # Final write: deduplicated scored file + filtered-only file
    all_results = list(scored.values())
    order = {inst["instance_id"]: i for i, inst in enumerate(instances)}
    all_results.sort(key=lambda r: order.get(r["instance_id"], 9999))

    # Rewrite scored file (deduped and ordered)
    with open(out_scored, "w") as f:
        for rec in all_results:
            f.write(json.dumps(rec) + "\n")

    # Write ONLY passing instances to candidates_filtered.jsonl
    # (downstream scripts read this file and assume all instances are valid)
    passing = [r for r in all_results if r.get("filter_pass")]
    with open(out, "w") as f:
        for rec in passing:
            f.write(json.dumps(rec) + "\n")

    print(
        f"\nWrote {len(passing)} passing to {out_path}  "
        f"({len(all_results) - len(passing)} discarded → {out_scored})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Quality filter for SWE-P-Bench candidates")
    parser.add_argument("--dataset", required=True,
                        help="Path to candidates.jsonl")
    parser.add_argument("--out", default=None,
                        help="Output path (default: candidates_filtered.jsonl alongside input)")
    parser.add_argument("--min-score", type=int, default=6,
                        help="Minimum relevance score to keep (0–10, default 6)")
    parser.add_argument("--model", default=_DEFAULT_MODEL,
                        help="LLM model for relevance scoring (default: claude:sonnet)")
    args = parser.parse_args()

    out = args.out or str(Path(args.dataset).parent / "candidates_filtered.jsonl")
    run_filter(args.dataset, out, min_score=args.min_score, model=args.model)


if __name__ == "__main__":
    main()
