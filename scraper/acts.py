"""
ACTS GitHub scraper — collects candidate benchmark instances.

Pipeline (mirrors SWE-bench Stage I + II):
  1. Fetch all merged PRs for acts-project/acts.
  2. Find PRs that close a GitHub issue (via "fixes #N" / "closes #N" in body).
  3. Keep PRs whose diff touches at least one test file.
  4. Fetch the issue text (problem_statement) and pre-PR comments (hints_text).
  5. Compute the base_commit (commit just before the PR's first commit).
  6. Split the PR diff into patch (non-test files) and test_patch (test files).
  7. Write each passing instance as a JSONL record.

Note: FAIL_TO_PASS / PASS_TO_PASS extraction requires actually running tests
inside a build environment and is NOT done here — those fields are left empty
for manual or later automated filling. The scraper produces "Stage II" data.

Usage:
    python -m scraper.acts [--repo REPO] [--out PATH] [--max-prs N] [--since DATE]

Environment:
    GITHUB_TOKEN  GitHub PAT (required; otherwise rate-limited to 60 req/hr)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Generator

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "acts-project/acts"
# Patterns that indicate a PR fixes an issue
_CLOSES_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*#(\d+)",
    re.IGNORECASE,
)
# Test file heuristics for ACTS (C++ project)
_TEST_FILE_RE = re.compile(
    r"(Tests?/|tests?/|_test\.|test_|/test|UnitTest|IntegrationTest)",
    re.IGNORECASE,
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
    """GET with automatic rate-limit back-off."""
    for attempt in range(6):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time() + 2, 1)
            print(f"  [rate limit] sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
    raise RuntimeError(f"Failed to GET {url} after retries")


def _paginate(
    session: requests.Session, url: str, params: dict | None = None
) -> Generator[Any, None, None]:
    """Yield items from all pages of a GitHub list endpoint."""
    p = dict(params or {})
    p.setdefault("per_page", 100)
    page = 1
    while True:
        p["page"] = page
        data = _get(session, url, p)
        if not data:
            break
        if isinstance(data, list):
            yield from data
            if len(data) < p["per_page"]:
                break
        else:
            # search endpoint returns {"items": [...], "total_count": N}
            yield from data.get("items", [])
            if len(data.get("items", [])) < p["per_page"]:
                break
        page += 1


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

def _extract_issue_numbers(text: str) -> list[int]:
    """Extract issue numbers from PR body / commit messages."""
    return [int(m) for m in _CLOSES_RE.findall(text or "")]


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path))


def _split_diff(diff_text: str) -> tuple[str, str]:
    """
    Split a unified diff into (non-test patch, test patch).
    Returns two diff strings.
    """
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

    code_parts: list[str] = []
    test_parts: list[str] = []
    for block in blocks:
        # Extract file path from "diff --git a/... b/..."
        m = re.search(r"^diff --git a/(\S+)", block, re.MULTILINE)
        path = m.group(1) if m else ""
        if _is_test_file(path):
            test_parts.append(block)
        else:
            code_parts.append(block)

    return "".join(code_parts), "".join(test_parts)


def _fetch_pr_diff(session: requests.Session, repo: str, pr_number: int) -> str:
    """Fetch the raw unified diff for a PR."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    r = session.get(
        url,
        headers={**session.headers, "Accept": "application/vnd.github.v3.diff"},
        timeout=60,
    )
    if r.status_code == 200:
        return r.text
    return ""


def _get_base_commit(session: requests.Session, repo: str, pr: dict) -> str:
    """
    The SWE-bench base_commit is the commit immediately before the PR's
    first commit — i.e., the PR's base branch tip at the time it was opened.
    GitHub gives us this directly as pr['base']['sha'].
    """
    return pr["base"]["sha"]


def _fetch_issue(session: requests.Session, repo: str, issue_number: int) -> dict | None:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    return _get(session, url)


def _fetch_issue_comments_before(
    session: requests.Session, repo: str, issue_number: int, before_iso: str
) -> str:
    """Fetch all issue comments posted before *before_iso* (ISO 8601 string)."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    texts: list[str] = []
    for comment in _paginate(session, url):
        if comment["created_at"] < before_iso:
            texts.append(comment["body"] or "")
    return "\n\n".join(texts)


def _problem_statement(issue: dict) -> str:
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    return f"{title}\n\n{body}".strip()


# ---------------------------------------------------------------------------
# Main scraping loop
# ---------------------------------------------------------------------------

def scrape(
    repo: str = DEFAULT_REPO,
    max_prs: int = 0,
    since: str = "",
    token: str | None = None,
) -> list[dict]:
    """
    Scrape candidate instances from *repo*.
    Returns a list of dataset records (Stage II — no FAIL_TO_PASS yet).
    """
    session = _session(token)
    owner, name = repo.split("/")

    print(f"Fetching merged PRs from {repo}…")
    pr_params: dict[str, Any] = {"state": "closed", "sort": "updated", "direction": "desc"}
    if since:
        pr_params["since"] = since

    candidates: list[dict] = []
    seen_prs: set[int] = set()
    pr_iter = _paginate(session, f"{GITHUB_API}/repos/{repo}/pulls", pr_params)

    with tqdm(unit="pr", desc="scanning PRs") as bar:
        for pr in pr_iter:
            bar.update(1)
            if max_prs and len(candidates) >= max_prs:
                break

            # Must be merged (not just closed)
            if not pr.get("merged_at"):
                continue

            pr_number = pr["number"]
            if pr_number in seen_prs:
                continue
            seen_prs.add(pr_number)

            # Extract issue numbers from PR body + title
            body = (pr.get("body") or "") + "\n" + (pr.get("title") or "")
            issue_numbers = _extract_issue_numbers(body)
            if not issue_numbers:
                continue

            # Fetch diff and check for test file changes
            diff = _fetch_pr_diff(session, repo, pr_number)
            if not diff:
                continue

            _, test_patch = _split_diff(diff)
            if not test_patch:
                continue  # No test changes → skip (SWE-bench Stage II filter)

            code_patch, _ = _split_diff(diff)

            # Use the first linked issue
            issue_number = issue_numbers[0]
            issue = _fetch_issue(session, repo, issue_number)
            if issue is None or issue.get("pull_request"):
                continue  # Linked item is itself a PR, not an issue

            # Fetch issue comments posted before the PR's first commit
            pr_first_commit_time = pr.get("created_at", "")
            hints = _fetch_issue_comments_before(
                session, repo, issue_number, pr_first_commit_time
            )

            base_commit = _get_base_commit(session, repo, pr)

            instance_id = f"{owner}__{name}-{pr_number}"
            record = {
                "instance_id": instance_id,
                "repo": repo,
                "base_commit": base_commit,
                "problem_statement": _problem_statement(issue),
                "hints_text": hints,
                "patch": code_patch,
                "test_patch": test_patch,
                "FAIL_TO_PASS": [],   # populated by evaluator/harness.py
                "PASS_TO_PASS": [],   # populated by evaluator/harness.py
                "created_at": issue.get("created_at", ""),
                "pr_number": pr_number,
                "issue_number": issue_number,
                "pr_url": pr.get("html_url", ""),
                "issue_url": issue.get("html_url", ""),
            }
            candidates.append(record)
            bar.set_postfix(collected=len(candidates), pr=pr_number)

    print(f"Collected {len(candidates)} candidate instances.")
    return candidates


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape ACTS GitHub for benchmark candidates")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--out", default="data/acts/candidates.jsonl")
    parser.add_argument("--max-prs", type=int, default=0, help="Stop after N merged PRs scanned (0 = all)")
    parser.add_argument("--since", default="", help="ISO date, e.g. 2023-01-01")
    parser.add_argument("--token", default="", help="GitHub token (overrides GITHUB_TOKEN env var)")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("WARNING: No GITHUB_TOKEN set. Rate-limited to 60 requests/hr.", file=sys.stderr)

    instances = scrape(
        repo=args.repo,
        max_prs=args.max_prs,
        since=args.since,
        token=token or None,
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
