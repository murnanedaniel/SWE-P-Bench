"""
Generic GitHub scraper — collects candidate benchmark instances.

Strategy (issue-first):
  1. Fetch closed true issues from the target repo.
  2. For each issue, query its timeline to find merged PRs that cross-referenced it.
  3. Fetch the PR diff; split into patch (non-test) and test_patch (test files).
  4. Filter: must touch at least one source file.
  5. Write each passing instance as a JSONL record.

File-type patterns are loaded from repos.yml when available; sensible defaults
are used for repos that are not in the registry.

FAIL_TO_PASS / PASS_TO_PASS fields are left empty — populated by the evaluator.

Usage:
    python -m scraper.generic --repo OWNER/NAME [--max-instances N] [--out PATH]

Environment:
    GITHUB_TOKEN  GitHub PAT — strongly recommended (5000 req/hr vs 60 req/hr).
                  If not set and the rate limit is hit, the scraper aborts
                  immediately with the reset timestamp rather than sleeping.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Generator

import requests
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

GITHUB_API = "https://api.github.com"

# Module-level fallback patterns (used when repos.yml has no entry for the repo).
_DEFAULT_SRC_PAT = re.compile(
    r"\.(cpp|hpp|h|ipp|cuh|cu|py)$",
    re.IGNORECASE,
)
_DEFAULT_TEST_PAT = re.compile(
    r"(Tests?/|tests?/|_[Tt]est\.|[Tt]est_|/[Tt]est[^/]*\.|UnitTest|IntegrationTest|test_.*\.py|.*_test\.py)",
)


# ---------------------------------------------------------------------------
# repos.yml helpers
# ---------------------------------------------------------------------------

def load_repo_config(repo: str, config_path: str = "repos.yml") -> dict:
    """
    Load per-repo config from *config_path* (default: repos.yml in cwd).
    Returns the config dict for *repo*, or {} if not found.
    """
    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        return data.get("repos", {}).get(repo, {})
    except Exception as exc:
        print(f"[warning] Could not load {config_path}: {exc}", file=sys.stderr)
        return {}


def _compile_patterns(config: dict) -> tuple[re.Pattern, re.Pattern]:
    """Return (src_pat, test_pat) compiled from *config*, falling back to defaults."""
    src_raw = config.get("src_file_pattern", "")
    test_raw = config.get("test_file_pattern", "")
    src_pat = re.compile(src_raw, re.IGNORECASE) if src_raw else _DEFAULT_SRC_PAT
    test_pat = re.compile(test_raw) if test_raw else _DEFAULT_TEST_PAT
    return src_pat, test_pat


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _session(token: str | None = None) -> requests.Session:
    s = requests.Session()
    t = token or os.environ.get("GITHUB_TOKEN", "")
    if t:
        s.headers["Authorization"] = f"Bearer {t}"
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["X-GitHub-Api-Version"] = "2022-11-28"
    return s


def _get(
    session: requests.Session,
    url: str,
    params: dict | None = None,
    *,
    abort_on_ratelimit_without_token: bool = True,
) -> Any:
    """GET with automatic rate-limit back-off.

    If *abort_on_ratelimit_without_token* is True (default) and no Authorization
    header is set, a 403/429 raises RuntimeError immediately (printing the reset
    timestamp) rather than sleeping, which would hang for up to an hour.
    """
    has_token = "Authorization" in session.headers

    for attempt in range(8):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429):
            reset = int(r.headers.get("X-RateLimit-Reset", 0))
            remaining = r.headers.get("X-RateLimit-Remaining", "?")
            if not has_token and abort_on_ratelimit_without_token:
                import datetime
                reset_human = (
                    datetime.datetime.fromtimestamp(reset).isoformat() if reset else "unknown"
                )
                raise RuntimeError(
                    f"GitHub rate limit hit (remaining={remaining}) and no "
                    f"GITHUB_TOKEN is set. Limit resets at {reset_human}. "
                    f"Set GITHUB_TOKEN to get 5000 req/hr."
                )
            wait = max(reset - time.time() + 5, 5) if reset else 60
            print(f"\n  [rate limit] sleeping {wait:.0f}s … (attempt {attempt+1})", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
    raise RuntimeError(f"Failed GET {url} after retries")


def _paginate(
    session: requests.Session, url: str, params: dict | None = None
) -> Generator[Any, None, None]:
    p = dict(params or {})
    p.setdefault("per_page", 100)
    page = 1
    while True:
        p["page"] = page
        data = _get(session, url, p)
        if not data:
            break
        items = data if isinstance(data, list) else data.get("items", [])
        yield from items
        if len(items) < p["per_page"]:
            break
        page += 1


# ---------------------------------------------------------------------------
# Issue → PR linking via timeline
# ---------------------------------------------------------------------------

def _find_closing_prs(session: requests.Session, repo: str, issue_number: int) -> list[int]:
    """
    Return PR numbers of merged PRs that cross-referenced this issue.
    Uses the timeline API — more reliable than "closes #N" body text for many
    repos that don't consistently use that convention.
    """
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/timeline"
    old_accept = session.headers.get("Accept")
    session.headers["Accept"] = "application/vnd.github.mockingbird-preview+json"
    try:
        pr_numbers: list[int] = []
        for event in _paginate(session, url):
            if event.get("event") != "cross-referenced":
                continue
            src_issue = event.get("source", {}).get("issue", {})
            pr_info = src_issue.get("pull_request", {})
            if pr_info.get("merged_at"):
                pr_numbers.append(src_issue["number"])
        return pr_numbers
    finally:
        session.headers["Accept"] = old_accept or "application/vnd.github+json"


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def _fetch_pr_diff(session: requests.Session, repo: str, pr_number: int) -> str:
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    r = session.get(
        url,
        headers={**dict(session.headers), "Accept": "application/vnd.github.v3.diff"},
        timeout=60,
    )
    return r.text if r.status_code == 200 else ""


def _split_diff(
    diff_text: str,
    src_pat: re.Pattern | None = None,
    test_pat: re.Pattern | None = None,
) -> tuple[str, str]:
    """Split a unified diff into (non-test patch, test patch).

    *src_pat* and *test_pat* are per-repo patterns from repos.yml.
    Falls back to module-level defaults when not provided.
    """
    if not diff_text:
        return "", ""

    _test_pat = test_pat or _DEFAULT_TEST_PAT

    blocks: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("".join(current))

    code_parts, test_parts = [], []
    for block in blocks:
        m = re.search(r"^diff --git a/(\S+)", block, re.MULTILINE)
        path = m.group(1) if m else ""
        if _test_pat.search(path):
            test_parts.append(block)
        else:
            code_parts.append(block)
    return "".join(code_parts), "".join(test_parts)


def _has_src_changes(
    diff_text: str,
    src_pat: re.Pattern | None = None,
) -> bool:
    """Return True if the diff touches at least one source file."""
    _src_pat = src_pat or _DEFAULT_SRC_PAT
    for line in diff_text.splitlines():
        if line.startswith("diff --git a/"):
            m = re.search(r"diff --git a/(\S+)", line)
            if m and _src_pat.search(m.group(1)):
                return True
    return False


# ---------------------------------------------------------------------------
# Disk cache  (avoids re-fetching on rate-limit interruptions)
# ---------------------------------------------------------------------------

class _Cache:
    def __init__(self, cache_dir: str | None):
        self._dir = Path(cache_dir) if cache_dir else None
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path | None:
        if not self._dir:
            return None
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)
        return self._dir / f"{safe}.json"

    def get(self, key: str) -> Any:
        p = self._path(key)
        if p and p.exists():
            return json.loads(p.read_text())
        return None

    def set(self, key: str, value: Any) -> None:
        p = self._path(key)
        if p:
            p.write_text(json.dumps(value))


# ---------------------------------------------------------------------------
# Main scraping loop
# ---------------------------------------------------------------------------

def scrape(
    repo: str,
    token: str | None = None,
    cache_dir: str | None = None,
    require_test_patch: bool = False,
    max_instances: int = 0,
    config: dict | None = None,
    min_date: str | None = None,
) -> list[dict]:
    """
    Scrape candidate instances from *repo* using the issue-first strategy.

    Args:
        repo:               GitHub repo slug, e.g. "scikit-hep/awkward".
        token:              GitHub PAT. Overrides GITHUB_TOKEN env var.
        cache_dir:          Directory for caching API responses (avoids re-fetch).
        require_test_patch: Only keep instances that include a test-file change.
        max_instances:      Stop once this many valid instances are collected.
                            0 means collect all.
        config:             Per-repo config dict (from load_repo_config()).
                            Used for src/test file patterns. Defaults loaded from
                            repos.yml if not provided.
        min_date:           ISO-8601 date string (e.g. "2021-01-01"). Instances
                            whose PR was merged before this date are skipped.
                            Avoids old commits that need cmake/Cython to install.

    Returns:
        List of dataset records (no FAIL_TO_PASS / PASS_TO_PASS yet).
    """
    if config is None:
        config = load_repo_config(repo)

    src_pat, test_pat = _compile_patterns(config)

    session = _session(token)
    cache = _Cache(cache_dir)
    owner, name = repo.split("/")

    # ---- Step 1: collect all true closed issues ----------------------------
    print(f"Fetching closed issues from {repo} …", file=sys.stderr)
    cache_key_issues = f"issues_{owner}_{name}_all_closed"
    all_issues: list[dict] = cache.get(cache_key_issues) or []

    if not all_issues:
        url = f"{GITHUB_API}/repos/{repo}/issues"
        for item in tqdm(
            _paginate(session, url, {"state": "closed", "sort": "created", "direction": "asc"}),
            desc="fetching issues",
            unit="item",
        ):
            if not item.get("pull_request"):
                all_issues.append({
                    "number": item["number"],
                    "title": item.get("title", ""),
                    "body": item.get("body") or "",
                    "created_at": item.get("created_at", ""),
                    "html_url": item.get("html_url", ""),
                    "labels": [lb["name"] for lb in item.get("labels", [])],
                })
        cache.set(cache_key_issues, all_issues)
        print(f"  Found {len(all_issues)} true issues.", file=sys.stderr)
    else:
        print(f"  Loaded {len(all_issues)} issues from cache.", file=sys.stderr)

    # ---- Step 2: for each issue, find merged PRs via timeline --------------
    candidates: list[dict] = []

    with tqdm(all_issues, desc="linking issues→PRs", unit="issue") as bar:
        for issue in bar:
            if max_instances and len(candidates) >= max_instances:
                break

            issue_num = issue["number"]

            cache_key_tl = f"timeline_{owner}_{name}_{issue_num}"
            closing_prs: list[int] | None = cache.get(cache_key_tl)
            if closing_prs is None:
                closing_prs = _find_closing_prs(session, repo, issue_num)
                cache.set(cache_key_tl, closing_prs)

            if not closing_prs:
                bar.set_postfix(status="no_pr")
                continue

            pr_num = closing_prs[0]

            cache_key_diff = f"diff_{owner}_{name}_{pr_num}"
            diff: str | None = cache.get(cache_key_diff)
            if diff is None:
                diff = _fetch_pr_diff(session, repo, pr_num)
                cache.set(cache_key_diff, diff or "")

            if not diff or not _has_src_changes(diff, src_pat=src_pat):
                bar.set_postfix(status="no_src")
                continue

            code_patch, test_patch = _split_diff(diff, src_pat=src_pat, test_pat=test_pat)

            if require_test_patch and not test_patch:
                bar.set_postfix(status="no_test")
                continue

            cache_key_pr = f"pr_{owner}_{name}_{pr_num}"
            pr_meta: dict | None = cache.get(cache_key_pr)
            if pr_meta is None:
                pr_meta = _get(session, f"{GITHUB_API}/repos/{repo}/pulls/{pr_num}") or {}
                cache.set(cache_key_pr, pr_meta)

            if not pr_meta.get("merged_at"):
                bar.set_postfix(status="unmerged")
                continue

            if min_date and pr_meta.get("merged_at", "") < min_date:
                bar.set_postfix(status="too_old")
                continue

            pr_created = pr_meta.get("created_at", "")
            cache_key_hints = f"hints_{owner}_{name}_{issue_num}_{pr_created[:10]}"
            hints: str | None = cache.get(cache_key_hints)
            if hints is None:
                url = f"{GITHUB_API}/repos/{repo}/issues/{issue_num}/comments"
                texts = [
                    c["body"] or ""
                    for c in _paginate(session, url)
                    if c.get("created_at", "") < pr_created
                ]
                hints = "\n\n".join(texts)
                cache.set(cache_key_hints, hints)

            instance_id = f"{owner}__{name}-{issue_num}"
            problem_statement = f"{issue['title']}\n\n{issue['body']}".strip()

            record = {
                "instance_id": instance_id,
                "repo": repo,
                "base_commit": pr_meta.get("base", {}).get("sha", ""),
                "problem_statement": problem_statement,
                "hints_text": hints,
                "patch": code_patch,
                "test_patch": test_patch,
                "FAIL_TO_PASS": [],
                "PASS_TO_PASS": [],
                "created_at": issue["created_at"],
                "pr_number": pr_num,
                "issue_number": issue_num,
                "pr_url": pr_meta.get("html_url", ""),
                "issue_url": issue["html_url"],
                "labels": issue["labels"],
                "pr_additions": pr_meta.get("additions", 0),
                "pr_deletions": pr_meta.get("deletions", 0),
                "pr_changed_files": pr_meta.get("changed_files", 0),
            }
            candidates.append(record)
            bar.set_postfix(collected=len(candidates), issue=issue_num)

    print(f"\nCollected {len(candidates)} candidate instances.", file=sys.stderr)
    return candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic GitHub scraper for SWE-P-Bench benchmark candidates"
    )
    parser.add_argument("--repo", required=True,
                        help="GitHub repo slug, e.g. scikit-hep/awkward")
    parser.add_argument("--out", default=None,
                        help="Output JSONL path (default: data/<owner>/<name>/candidates.jsonl)")
    parser.add_argument("--cache-dir", default=".scraper_cache",
                        help="Directory for caching API responses")
    parser.add_argument("--token", default="",
                        help="GitHub token (overrides GITHUB_TOKEN env var)")
    parser.add_argument("--require-test-patch", action="store_true",
                        help="Only keep instances that include a test file change")
    parser.add_argument("--max-instances", type=int, default=0,
                        help="Stop after collecting this many instances (0=all)")
    parser.add_argument("--config", default="repos.yml",
                        help="Path to repos.yml config file (default: repos.yml)")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print(
            "WARNING: No GITHUB_TOKEN — rate-limited to 60 req/hr. "
            "Scraper will abort on first rate-limit hit. "
            "Provide a token for 5000 req/hr.",
            file=sys.stderr,
        )

    repo_config = load_repo_config(args.repo, config_path=args.config)

    instances = scrape(
        repo=args.repo,
        token=token or None,
        cache_dir=args.cache_dir,
        require_test_patch=args.require_test_patch,
        max_instances=args.max_instances,
        config=repo_config,
    )

    if args.out:
        out = Path(args.out)
    else:
        owner, name = args.repo.split("/")
        out = Path("data") / owner / name / "candidates.jsonl"

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")
    print(f"Written {len(instances)} instances to {out}")


if __name__ == "__main__":
    main()
