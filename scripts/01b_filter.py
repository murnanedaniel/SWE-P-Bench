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

Filter B — LLM relevance score (one gpt-5.4 call per instance):
    Discards instances where the merged PR addresses something substantially
    different from what the issue describes (e.g. issue says "add tests" but
    PR fixes an unrelated bug; issue says "add docs" but PR also renames a
    public attribute).

    Score 0–10; instances scoring < ``--min-score`` (default 6) are discarded.

Usage:
    python scripts/01b_filter.py \\
        --dataset data/scikit-hep/particle/candidates.jsonl \\
        [--out data/scikit-hep/particle/candidates_filtered.jsonl] \\
        [--min-score 6]

The output JSONL has the same fields as the input plus three extra fields
per record:
    filter_data_entry:      bool  — True if the data-entry heuristic fired
    filter_relevance_score: int   — 0–10 relevance score (−1 if not scored)
    filter_pass:            bool  — True if the instance passes both filters

Idempotent: if the output file already exists, only instances not yet scored
(by instance_id) are processed and the results are merged back.

Environment:
    OPENAI_API_KEY  Required for Filter B
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

_RELEVANCE_MODEL = "gpt-5.4"

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


def _score_relevance(client: OpenAI, instance: dict) -> int:
    """Call gpt-5.4 and return a 0–10 relevance integer (−1 on failure)."""
    issue = instance.get("problem_statement", "").strip()[:3000]  # cap for cost
    diff_summary = _make_diff_summary(instance.get("patch", ""))

    prompt = _RELEVANCE_TEMPLATE.format(issue=issue, diff_summary=diff_summary)
    try:
        response = client.chat.completions.create(
            model=_RELEVANCE_MODEL,
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
) -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key) if api_key else None

    # Load all instances
    instances: list[dict] = []
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    # Load already-scored instances from output (for idempotency)
    scored: dict[str, dict] = {}
    out = Path(out_path)
    if out.exists():
        with open(out) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    scored[rec["instance_id"]] = rec

    to_process = [i for i in instances if i["instance_id"] not in scored]
    print(
        f"{dataset_path}: {len(instances)} total, "
        f"{len(scored)} already filtered, {len(to_process)} to process"
    )

    new_results: list[dict] = []
    for inst in tqdm(to_process, unit="instance"):
        iid = inst["instance_id"]
        patch = inst.get("patch", "")

        # Filter A
        is_data = _data_entry_score(patch)

        # Filter B (only call LLM if not already discarded by A and API key available)
        if is_data:
            score = -1  # skip LLM for clear data-entry cases
        elif client is None:
            print(
                "  [warning] OPENAI_API_KEY not set — skipping relevance filter",
                file=sys.stderr,
            )
            score = 10  # assume pass when no API key
        else:
            score = _score_relevance(client, inst)

        passes = (not is_data) and (score == -1 or score >= min_score)

        rec = dict(inst)
        rec["filter_data_entry"] = is_data
        rec["filter_relevance_score"] = score
        rec["filter_pass"] = passes
        new_results.append(rec)

        status = "PASS" if passes else f"FAIL(data={is_data},score={score})"
        print(f"  {iid}: {status}", file=sys.stderr)

    # Merge and write
    all_results = list(scored.values()) + new_results
    # Preserve input order
    order = {inst["instance_id"]: i for i, inst in enumerate(instances)}
    all_results.sort(key=lambda r: order.get(r["instance_id"], 9999))

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for rec in all_results:
            f.write(json.dumps(rec) + "\n")

    passed = sum(1 for r in all_results if r.get("filter_pass"))
    print(
        f"\nWrote {len(all_results)} records to {out_path}  "
        f"({passed} pass / {len(all_results) - passed} discard)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Quality filter for SWE-P-Bench candidates")
    parser.add_argument("--dataset", required=True,
                        help="Path to candidates.jsonl")
    parser.add_argument("--out", default=None,
                        help="Output path (default: candidates_filtered.jsonl alongside input)")
    parser.add_argument("--min-score", type=int, default=6,
                        help="Minimum relevance score to keep (0–10, default 6)")
    args = parser.parse_args()

    out = args.out or str(Path(args.dataset).parent / "candidates_filtered.jsonl")
    run_filter(args.dataset, out, min_score=args.min_score)


if __name__ == "__main__":
    main()
