"""
ACTS GitHub scraper — collects candidate benchmark instances.

Strategy (issue-first, matching empirical ACTS development patterns):
  1. Fetch ALL closed true issues (not PRs) from acts-project/acts.
  2. For each issue, query its timeline to find merged PRs that cross-referenced it.
     (ACTS rarely uses "closes #N" in PR bodies — only ~2% of fix PRs do.
      The timeline cross-reference event is the reliable signal.)
  3. Fetch the PR diff; split into patch (non-test) and test_patch (test files).
  4. Filter: must touch at least one source file (.cpp/.hpp/.h/.py/.cuh).
  5. Write each passing instance as a JSONL record.

FAIL_TO_PASS / PASS_TO_PASS fields are left empty — populated by the evaluator.

Usage:
    python -m scraper.acts [--repo REPO] [--out PATH] [--cache-dir DIR]

Environment:
    GITHUB_TOKEN  GitHub PAT — strongly recommended (5000 req/hr vs 60 req/hr)
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
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "acts-project/acts"

_SRC_FILE_RE = re.compile(
    r"\.(cpp|hpp|h|ipp|cuh|cu|py)$",
    re.IGNORECASE,
)
_TEST_FILE_RE = re.compile(
    r"(Tests?/|tests?/|_[Tt]est\.|[Tt]est_|/[Tt]est[^/]*\.|UnitTest|IntegrationTest)",
)


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


def _get(session: requests.Session, url: str, params: dict | None = None) -> Any:
    """GET with automatic rate-limit back-off (waits until reset)."""
    for attempt in range(8):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429):
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time() + 5, 5)
            print(f"\n  [rate limit] sleeping {wait:.0f}s …", file=sys.stderr)
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
# Issue → PR linking via timeline (the reliable ACTS signal)
# ---------------------------------------------------------------------------

def _find_closing_prs(session: requests.Session, repo: str, issue_number: int) -> list[int]:
    """
    Return PR numbers of merged PRs that cross-referenced this issue.
    Uses the timeline API — more reliable than "closes #N" body text for ACTS,
    which uses that convention in only ~2% of fix PRs.
    """
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/timeline"
    # Timeline requires a special Accept header
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


def _split_diff(diff_text: str) -> tuple[str, str]:
    """Split unified diff into (non-test patch, test patch)."""
    if not diff_text:
        return "", ""
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
        (test_parts if _TEST_FILE_RE.search(path) else code_parts).append(block)
    return "".join(code_parts), "".join(test_parts)


def _has_src_changes(diff_text: str) -> bool:
    """Return True if the diff touches at least one source file."""
    for line in diff_text.splitlines():
        if line.startswith("diff --git a/"):
            m = re.search(r"diff --git a/(\S+)", line)
            if m and _SRC_FILE_RE.search(m.group(1)):
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
    repo: str = DEFAULT_REPO,
    token: str | None = None,
    cache_dir: str | None = None,
    require_test_patch: bool = False,
) -> list[dict]:
    """
    Scrape candidate instances from *repo* using the issue-first strategy.
    Returns a list of dataset records (no FAIL_TO_PASS / PASS_TO_PASS yet).
    """
    session = _session(token)
    cache = _Cache(cache_dir)
    owner, name = repo.split("/")

    # ---- Step 1: collect all true closed issues ----------------------------
    print(f"Fetching all closed issues from {repo} …", file=sys.stderr)
    cache_key_issues = f"issues_{owner}_{name}_all_closed"
    all_issues: list[dict] = cache.get(cache_key_issues) or []

    if not all_issues:
        url = f"{GITHUB_API}/repos/{repo}/issues"
        for item in tqdm(
            _paginate(session, url, {"state": "closed", "sort": "created", "direction": "asc"}),
            desc="fetching issues",
            unit="item",
        ):
            if not item.get("pull_request"):   # skip PRs returned by the issues endpoint
                all_issues.append({
                    "number": item["number"],
                    "title": item.get("title", ""),
                    "body": item.get("body") or "",
                    "created_at": item.get("created_at", ""),
                    "html_url": item.get("html_url", ""),
                    "labels": [l["name"] for l in item.get("labels", [])],
                })
        cache.set(cache_key_issues, all_issues)
        print(f"  Found {len(all_issues)} true issues.", file=sys.stderr)
    else:
        print(f"  Loaded {len(all_issues)} issues from cache.", file=sys.stderr)

    # ---- Step 2: for each issue, find merged PRs via timeline --------------
    candidates: list[dict] = []

    with tqdm(all_issues, desc="linking issues→PRs", unit="issue") as bar:
        for issue in bar:
            issue_num = issue["number"]

            # Timeline lookup (cached per issue)
            cache_key_tl = f"timeline_{owner}_{name}_{issue_num}"
            closing_prs: list[int] = cache.get(cache_key_tl)
            if closing_prs is None:
                closing_prs = _find_closing_prs(session, repo, issue_num)
                cache.set(cache_key_tl, closing_prs)

            if not closing_prs:
                bar.set_postfix(status="no_pr")
                continue

            # Use the first (usually only) closing PR
            pr_num = closing_prs[0]

            # Diff lookup (cached per PR)
            cache_key_diff = f"diff_{owner}_{name}_{pr_num}"
            diff: str | None = cache.get(cache_key_diff)
            if diff is None:
                diff = _fetch_pr_diff(session, repo, pr_num)
                cache.set(cache_key_diff, diff or "")

            if not diff or not _has_src_changes(diff):
                bar.set_postfix(status="no_src")
                continue

            code_patch, test_patch = _split_diff(diff)

            if require_test_patch and not test_patch:
                bar.set_postfix(status="no_test")
                continue

            # PR metadata (cached)
            cache_key_pr = f"pr_{owner}_{name}_{pr_num}"
            pr_meta: dict | None = cache.get(cache_key_pr)
            if pr_meta is None:
                pr_meta = _get(session, f"{GITHUB_API}/repos/{repo}/pulls/{pr_num}") or {}
                cache.set(cache_key_pr, pr_meta)

            if not pr_meta.get("merged_at"):
                bar.set_postfix(status="unmerged")
                continue

            # Issue comments before the PR was created (hints)
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
    parser = argparse.ArgumentParser(description="Scrape ACTS GitHub for benchmark candidates")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--out", default="data/acts/candidates.jsonl")
    parser.add_argument("--cache-dir", default=".scraper_cache", help="Dir for caching API responses")
    parser.add_argument("--token", default="", help="GitHub token (overrides GITHUB_TOKEN env var)")
    parser.add_argument("--require-test-patch", action="store_true",
                        help="Only keep instances that include a test file change")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("WARNING: No GITHUB_TOKEN — rate-limited to 60 req/hr. "
              "Provide a token for 5000 req/hr.", file=sys.stderr)

    instances = scrape(
        repo=args.repo,
        token=token or None,
        cache_dir=args.cache_dir,
        require_test_patch=args.require_test_patch,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")
    print(f"Written {len(instances)} instances to {out}")


if __name__ == "__main__":
    main()
