"""
Batch scraper for all Python repos in repos.yml.

Scrapes every Python repo in repos.yml and writes per-repo JSONL files to
data/{owner}/{name}/candidates.jsonl. Idempotent: existing instances are
preserved and only new (by instance_id) ones are appended.

Usage:
    python scripts/01_scrape.py [--repos scikit-hep/awkward,scikit-hep/hist] \
                                 [--max-instances 50] [--out-dir data/]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.generic import load_repo_config, scrape


def load_repos_yml(path: str = "repos.yml") -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("repos", [])


def load_existing_ids(jsonl_path: Path) -> set[str]:
    """Return the set of instance_ids already present in a JSONL file."""
    if not jsonl_path.exists():
        return set()
    ids: set[str] = set()
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    if "instance_id" in rec:
                        ids.add(rec["instance_id"])
                except json.JSONDecodeError:
                    pass
    return ids


def scrape_repo(
    repo: str,
    token: str | None,
    out_dir: Path,
    max_instances: int,
    min_date: str | None = None,
) -> int:
    """Scrape one repo and append new instances to candidates.jsonl.

    Returns the number of *new* instances written.
    """
    owner, name = repo.split("/", 1)
    repo_dir = out_dir / owner / name
    repo_dir.mkdir(parents=True, exist_ok=True)
    out_path = repo_dir / "candidates.jsonl"

    existing_ids = load_existing_ids(out_path)

    config = load_repo_config(repo)
    cache_dir = str(repo_dir / ".cache")

    print(f"  Scraping {repo} …", flush=True)
    instances = scrape(
        repo=repo,
        token=token,
        cache_dir=cache_dir,
        require_test_patch=False,
        max_instances=max_instances,
        config=config,
        min_date=min_date,
    )

    new_instances = [i for i in instances if i.get("instance_id") not in existing_ids]

    if new_instances:
        with open(out_path, "a") as f:
            for inst in new_instances:
                f.write(json.dumps(inst) + "\n")

    total = len(existing_ids) + len(new_instances)
    print(
        f"  {repo}: {len(new_instances)} new instances "
        f"({total} total) → {out_path}",
        flush=True,
    )
    return len(new_instances)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch scraper for SWE-P-Bench repos")
    parser.add_argument(
        "--repos",
        default="",
        help="Comma-separated list of repos to scrape (default: all Python repos in repos.yml)",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Max instances per repo (0 = no limit)",
    )
    parser.add_argument(
        "--out-dir",
        default="data",
        help="Root output directory (default: data/)",
    )
    parser.add_argument(
        "--repos-yml",
        default="repos.yml",
        help="Path to repos.yml (default: repos.yml)",
    )
    parser.add_argument(
        "--min-date",
        default=None,
        help="Only include instances whose PR was merged on or after YYYY-MM-DD "
             "(e.g. 2021-01-01). Avoids old commits that need cmake/Cython to install.",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "WARNING: GITHUB_TOKEN not set — unauthenticated API (60 req/hr limit).",
            file=sys.stderr,
        )

    out_dir = Path(args.out_dir)

    # Determine which repos to scrape
    if args.repos:
        target_repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    else:
        all_repos = load_repos_yml(args.repos_yml)
        target_repos = [
            r["repo"]
            for r in all_repos
            if r.get("language", "python").lower() == "python"
        ]

    if not target_repos:
        print("No repos to scrape.", file=sys.stderr)
        sys.exit(1)

    print(f"Scraping {len(target_repos)} repo(s) → {out_dir}/", flush=True)

    total_new = 0
    for repo in target_repos:
        try:
            total_new += scrape_repo(
                repo=repo,
                token=token,
                out_dir=out_dir,
                max_instances=args.max_instances,
                min_date=args.min_date,
            )
        except Exception as exc:
            print(f"  ERROR scraping {repo}: {exc}", file=sys.stderr)

    print(f"\nDone. {total_new} new instances written across all repos.", flush=True)


if __name__ == "__main__":
    main()
