"""
GPT-5-mini file-context baseline solver for SWE-P-Bench.

Given a dataset of benchmark instances, this solver:
  1. Parses the gold patch to identify which source files are modified.
  2. Fetches those files from ``raw.githubusercontent.com`` at ``base_commit``.
  3. Includes the file contents in the prompt as a ``## Source Files`` section.
  4. Asks GPT-5-mini to produce a unified diff patch that resolves the issue.

Source context is fetched via ``urllib.request`` (stdlib only) so this module
has no additional dependencies beyond the project's existing requirements.

Fetching is best-effort: files that 404 or fail due to network errors are
silently skipped, and the solver falls back to zero-context (issue description
only) when no files can be fetched.

Language-aware: uses ``repos.yml`` (via ``scraper.generic.load_repo_config``) to
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
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

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
- File paths MUST follow the actual modern layout of the repo.
  Most scientific Python packages use the `src/<package>/` layout.
  For example: `src/awkward/operations/ak_from_buffers.py`, not `awkward/_v2/foo.py`.
  If the issue text or API name gives a clue (e.g. `ak.from_buffers`), derive the
  file path as `src/<package>/operations/<module>.py` or similar.
  Never invent legacy `_v2/` or `_v3/` subpaths that may have been removed.
- When source files are provided, each line is prefixed with its line number.
  Use those numbers to write correct @@ -N,M +N,M @@ hunk headers.
  Copy context and removed lines VERBATIM from the numbered source.
  Never invent code not shown in the source files.
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
{source_files_section}
## Task

Produce a unified diff patch that resolves this issue. Output only the raw diff.
"""


# ---------------------------------------------------------------------------
# Patch normalisers (Issues #18, #22)
# ---------------------------------------------------------------------------

_BARE_HUNK_RE = re.compile(r"^ @@\s*$", re.MULTILINE)
_VALID_HUNK_RE = re.compile(r"^@@ -\d", re.MULTILINE)


def _normalize_bare_hunk_headers(patch: str) -> str:
    """
    Handle the "bare @@" compact format where the model outputs ` @@` (a
    space-prefixed `@@`) as a section separator instead of a proper hunk
    header like `@@ -10,5 +10,7 @@`.

    We scan each hunk section, count the original/new line deltas, and
    generate a best-effort `@@ -N,C +N,C @@` header.  With `--recount`,
    `git apply` will then fix any inaccurate line numbers by searching for
    the context in the file.
    """
    lines = patch.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    orig_running = 1  # estimated line in the original file

    while i < len(lines):
        line = lines[i]
        # Detect bare @@ separator (space + @@, optionally followed by spaces)
        if re.match(r"^ @@\s*$", line):
            # Count the hunk body to estimate line counts
            orig_count = 0
            new_count = 0
            j = i + 1
            while j < len(lines) and not re.match(r"^ @@\s*$|^diff --git ", lines[j]):
                c = lines[j]
                if c.startswith("-"):
                    orig_count += 1
                elif c.startswith("+"):
                    new_count += 1
                else:
                    # context line (space prefix or blank)
                    orig_count += 1
                    new_count += 1
                j += 1
            result.append(f"@@ -{orig_running},{orig_count} +{orig_running},{new_count} @@\n")
            orig_running += orig_count
            i += 1
        else:
            result.append(line)
            i += 1

    return "".join(result)


def _strip_context_trailing_ws(patch: str) -> str:
    """Remove trailing whitespace from blank/context lines.

    LLMs (especially gpt-5.4) emit lines like ' \\n' (space + newline) on
    blank context lines inside hunks.  ``git apply`` rejects these even with
    ``--ignore-whitespace``, causing an otherwise-correct patch to fail.
    """
    return re.sub(r"^([ ].*?)\s+$", r"\1", patch, flags=re.MULTILINE)


def _normalize_patch(patch: str) -> str:
    """
    Normalise LLM-generated patch output to standard unified diff.

    Handles two non-standard formats:

    1. OpenAI ``*** Begin Patch`` format (Issue #18):
       Produced by reasoning models as a custom format with
       ``*** Update File:`` / ``@@@ line`` markers.

    2. Compact ``@@`` separator format (Issue #22):
       The model outputs a bare `` @@`` line (space + @@, no line numbers)
       as a section separator instead of a proper ``@@ -N,N +N,N @@``
       hunk header.  We reconstruct proper headers so ``git apply --recount``
       can locate and apply each hunk.
    """
    patch = _strip_context_trailing_ws(patch)
    stripped = patch.strip()
    if not stripped:
        return patch

    # --- Format 1: *** Begin Patch (or bare *** Update/Add/Delete File:) ---
    if stripped.startswith("*** Begin Patch") or re.match(
        r"^\*\*\* (Update|Add|Delete) File:", stripped
    ):
        result = _normalize_begin_patch(stripped)
        return _recount_hunk_sizes(result)

    # --- Format 2a: space-prefixed hunk headers with real line numbers ---
    # Model outputs " @@ -N,M +N,M @@" (leading space) instead of "@@ -N,M +N,M @@".
    _SPACED_HUNK_RE = re.compile(r"^ @@ -\d+", re.MULTILINE)
    if _SPACED_HUNK_RE.search(stripped):
        result = re.sub(r"^ @@", "@@", stripped, flags=re.MULTILINE)
        if result and not result.endswith("\n"):
            result += "\n"
        return _recount_hunk_sizes(result)

    # --- Format 2b: bare @@ separators (no line numbers) ---
    # Only kick in when there are bare-@@ lines AND no valid hunk headers.
    if _BARE_HUNK_RE.search(stripped) and not _VALID_HUNK_RE.search(stripped):
        result = _normalize_bare_hunk_headers(stripped)
        if result and not result.endswith("\n"):
            result += "\n"
        return _recount_hunk_sizes(result)

    # Standard unified diff — still recount in case the LLM wrote wrong counts.
    return _recount_hunk_sizes(patch)


def _recount_hunk_sizes(patch_text: str) -> str:
    """Fix @@ -N,M +N,M @@ line counts to match actual hunk body.

    LLMs commonly emit wrong counts in hunk headers (e.g. ``@@ -10,3 +10,5 @@``
    when the body actually has 4 original lines and 8 new lines).  Wrong counts
    cause ``patch`` to declare "malformed patch" even with ``--fuzz``.

    Strategy: split on hunk headers, count context/+/- lines in each body, and
    rewrite the M values.  The starting line N is left to ``--recount`` / the
    existing ``_correct_hunk_positions`` call.
    """
    _HDR_RE = re.compile(
        r"(@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@([^\n]*))\n",
        re.MULTILINE,
    )
    _DIFF_LINE_RE = re.compile(r"^(diff --git |--- |\+\+\+ )")

    parts = _HDR_RE.split(patch_text)
    # split() with a capturing group interleaves: [pre, full_match, g1, g2, g3, body, ...]
    # Groups: 0=full, 1=orig_start, 2=new_start, 3=suffix
    result: list[str] = [parts[0]]
    i = 1
    while i < len(parts):
        if i + 4 >= len(parts):
            result.append(parts[i])
            i += 1
            continue
        _full, orig_start, new_start, suffix = parts[i], parts[i + 1], parts[i + 2], parts[i + 3]
        body = parts[i + 4]

        orig_count = 0
        new_count = 0
        for line in body.splitlines():
            if _DIFF_LINE_RE.match(line):
                break  # start of next file section
            if line.startswith("-"):
                orig_count += 1
            elif line.startswith("+"):
                new_count += 1
            else:  # context (space) or blank
                orig_count += 1
                new_count += 1

        suf = f" {suffix}" if suffix.strip() else suffix
        result.append(f"@@ -{orig_start},{orig_count} +{new_start},{new_count} @@{suf}\n")
        result.append(body)
        i += 5

    return "".join(result)


def _normalize_begin_patch(stripped: str) -> str:
    """Convert ``*** Begin Patch`` format to unified diff (Issue #18)."""

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
# Source-context fetching (file-context baseline)
# ---------------------------------------------------------------------------

_MAX_LINES = 500
_TRUNCATION_MARKER = "# [file truncated to 500 lines for prompt efficiency]"


def _parse_patch_paths(patch_text: str) -> list[str]:
    """Extract file paths from a unified diff (same regex used across the codebase)."""
    return re.findall(r"^diff --git a/(\S+)", patch_text, re.MULTILINE)


def _fetch_file_at_commit(
    owner: str,
    repo: str,
    commit: str,
    path: str,
) -> str | None:
    """Fetch raw file content from GitHub at a specific commit. Returns None on error.

    Uses raw.githubusercontent.com — no auth needed for public repos,
    no third-party library needed (stdlib urllib only).
    """
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        if len(lines) > _MAX_LINES:
            lines = lines[:_MAX_LINES]
            lines.append(_TRUNCATION_MARKER + "\n")
        return "".join(lines)
    except Exception:
        return None


def fetch_source_context(instance: dict, max_files: int = 5) -> dict[str, str]:
    """Fetch source files touched by the gold patch at base_commit.

    Returns {relative_path: content}. Empty dict if patch absent or all fetches fail.
    Fetching is best-effort — any 404 or network error is silently skipped.
    """
    patch_text = instance.get("patch", "") or ""
    if not patch_text.strip():
        return {}
    paths = _parse_patch_paths(patch_text)
    if not paths:
        return {}
    repo = instance.get("repo", "")
    base_commit = instance.get("base_commit", "")
    if not repo or not base_commit or "/" not in repo:
        return {}
    owner, repo_name = repo.split("/", 1)
    context: dict[str, str] = {}
    for path in paths[:max_files]:
        content = _fetch_file_at_commit(owner, repo_name, base_commit, path)
        if content is not None:
            context[path] = content
    return context


# ---------------------------------------------------------------------------
# Core solver
# ---------------------------------------------------------------------------

def build_prompt(
    instance: dict,
    source_context: dict[str, str] | None = None,
) -> str:
    """Build the user-turn prompt.

    When *source_context* is provided, each file is included as a fenced
    code block under ``## Source Files`` so the model uses real context lines.
    """
    hints = instance.get("hints_text", "").strip()
    hints_section = f"## Hints / Discussion\n\n{hints}" if hints else ""

    if source_context:
        file_blocks: list[str] = []
        for path, content in source_context.items():
            # Number every line so the model can write exact @@ -N,M +N,M @@ headers.
            numbered = "\n".join(
                f"{i + 1:4}: {line}"
                for i, line in enumerate(content.splitlines())
            )
            file_blocks.append(f"### `{path}`\n\n```\n{numbered}\n```")
        files_body = "\n\n".join(file_blocks)
        source_files_section = (
            "\n## Source Files\n\n"
            "Each line is prefixed with its 1-based line number followed by ': '.\n"
            "Use these exact line numbers in your unified diff hunk headers\n"
            "(e.g. @@ -278,14 +278,19 @@). Do NOT invent code not shown here.\n\n"
            f"{files_body}\n"
        )
    else:
        source_files_section = ""

    return USER_TEMPLATE.format(
        repo=instance.get("repo", ""),
        problem_statement=instance["problem_statement"],
        hints_section=hints_section,
        source_files_section=source_files_section,
    ).strip()


def solve_instance(
    client: OpenAI,
    instance: dict,
    repo_config: dict | None = None,
    max_attempts: int = 1,
) -> str:
    """Call the model and return the predicted patch string (normalised).

    Fetches source files at base_commit for context. Degrades gracefully
    to zero-context (issue description only) if fetching fails.

    If max_attempts > 1, retries up to that many times when the model
    returns an empty or unparseable patch (pure sampling diversity — same
    prompt each attempt, no feedback injection).
    """
    lang = (repo_config or {}).get("language", "python")
    system = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PYTHON)

    ctx = fetch_source_context(instance)  # {} on any failure
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": build_prompt(instance, source_context=ctx)},
    ]

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_completion_tokens=8000,  # reasoning model: budget covers reasoning+output
            )
            raw = response.choices[0].message.content or ""
            patch = _normalize_patch(raw)
            if patch.strip():
                return patch
            # empty output — retry if attempts remain
            if attempt < max_attempts:
                print(
                    f"  [attempt {attempt}/{max_attempts}] empty patch, retrying…",
                    file=sys.stderr,
                )
        except Exception as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            print(
                f"  [attempt {attempt}/{max_attempts}] error: {exc}, retrying…",
                file=sys.stderr,
            )

    return ""  # all attempts returned empty


def solve_dataset(
    dataset_path: str,
    out_dir: str,
    max_instances: int = 0,
    repos_yml: str = "repos.yml",
    max_attempts: int = 1,
    workers: int = 1,
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

    # Skip already-solved instances
    instances = [i for i in instances if not (out / f"{i['instance_id']}.patch").exists()]

    print(f"Solving {len(instances)} instances with {MODEL} (workers={workers})…")

    write_lock = Lock()

    def _solve_one(inst: dict) -> tuple[str, str]:
        iid = inst["instance_id"]
        repo_cfg = load_repo_config(inst.get("repo", ""), config_path=repos_yml)
        try:
            patch = solve_instance(client, inst, repo_config=repo_cfg, max_attempts=max_attempts)
        except Exception as e:
            print(f"  [error] {iid}: {e}", file=sys.stderr)
            patch = ""
        return iid, patch

    with open(predictions_path, "a") as pred_f:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_solve_one, inst): inst for inst in instances}
            with tqdm(total=len(instances), unit="instance") as pbar:
                for future in as_completed(futures):
                    iid, patch = future.result()
                    patch_file = out / f"{iid}.patch"
                    patch_file.write_text(patch)
                    with write_lock:
                        pred_f.write(json.dumps({
                            "instance_id": iid,
                            "model": MODEL,
                            "patch": patch,
                        }) + "\n")
                        pred_f.flush()
                    pbar.update(1)

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
