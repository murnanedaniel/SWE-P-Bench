"""
Pairing-rate statistics across ALL closed ACTS issues.

Run this after `python -m scraper.acts` has populated the cache, or
run it standalone — it will fetch just what it needs and cache results.

Usage:
    python -m scraper.stats [--cache-dir DIR] [--sample N]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"
REPO = "acts-project/acts"


def _session(token: str | None = None) -> requests.Session:
    s = requests.Session()
    t = token or os.environ.get("GITHUB_TOKEN", "")
    if t:
        s.headers["Authorization"] = f"Bearer {t}"
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["X-GitHub-Api-Version"] = "2022-11-28"
    return s


def _get(session, url, params=None):
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
    raise RuntimeError(f"Failed GET {url}")


def _paginate(session, url, params=None):
    p = dict(params or {}); p.setdefault("per_page", 100)
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


class Cache:
    def __init__(self, d):
        self._dir = Path(d); self._dir.mkdir(parents=True, exist_ok=True)
    def _p(self, k):
        return self._dir / (re.sub(r"[^a-zA-Z0-9_\-]", "_", k) + ".json")
    def get(self, k):
        p = self._p(k); return json.loads(p.read_text()) if p.exists() else None
    def set(self, k, v): self._p(k).write_text(json.dumps(v))


def _find_closing_prs(session, repo, issue_num, cache):
    key = f"timeline_{repo.replace('/', '_')}_{issue_num}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_num}/timeline"
    old = session.headers.get("Accept")
    session.headers["Accept"] = "application/vnd.github.mockingbird-preview+json"
    try:
        prs = []
        for event in _paginate(session, url):
            if event.get("event") != "cross-referenced":
                continue
            src = event.get("source", {}).get("issue", {})
            if src.get("pull_request", {}).get("merged_at"):
                prs.append(src["number"])
        cache.set(key, prs)
        return prs
    finally:
        session.headers["Accept"] = old or "application/vnd.github+json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=".scraper_cache")
    ap.add_argument("--sample", type=int, default=0, help="Random sample size (0=all)")
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("WARNING: No token — 60 req/hr limit applies.", file=sys.stderr)

    session = _session(token)
    cache = Cache(args.cache_dir)
    owner, name = REPO.split("/")

    # --- Collect all true issues ---
    cache_key = f"issues_{owner}_{name}_all_closed"
    all_issues = cache.get(cache_key)
    if all_issues is None:
        print("Fetching all closed issues …", file=sys.stderr)
        all_issues = []
        for item in _paginate(session, f"{GITHUB_API}/repos/{REPO}/issues",
                              {"state": "closed", "sort": "created", "direction": "asc"}):
            if not item.get("pull_request"):
                all_issues.append({
                    "number": item["number"],
                    "title": item.get("title", ""),
                    "labels": [l["name"] for l in item.get("labels", [])],
                })
                if len(all_issues) % 50 == 0:
                    print(f"  {len(all_issues)} issues so far …", file=sys.stderr)
        cache.set(cache_key, all_issues)

    print(f"\nTotal true closed issues: {len(all_issues)}")

    # --- Label distribution ---
    label_counts: Counter = Counter()
    for iss in all_issues:
        if not iss["labels"]:
            label_counts["(unlabeled)"] += 1
        for l in iss["labels"]:
            label_counts[l] += 1
    print("\nLabel distribution (top 20):")
    for label, count in label_counts.most_common(20):
        bar = "#" * (count // 2)
        print(f"  {label:35s}: {count:4d}  {bar}")

    # --- Pairing rate (sampled or full) ---
    population = all_issues
    if args.sample and args.sample < len(all_issues):
        random.seed(42)
        population = random.sample(all_issues, args.sample)
        print(f"\nPairing rate (random sample n={len(population)}):")
    else:
        print(f"\nPairing rate (all {len(population)} issues):")

    paired, unpaired = [], []
    for i, iss in enumerate(population):
        prs = _find_closing_prs(session, REPO, iss["number"], cache)
        (paired if prs else unpaired).append(iss)
        if (i + 1) % 10 == 0:
            done = i + 1
            print(f"  {done}/{len(population)}  paired={len(paired)} unpaired={len(unpaired)}",
                  file=sys.stderr)
        time.sleep(0.1)

    total = len(paired) + len(unpaired)
    print(f"\n  Paired (found a merged PR) : {len(paired):4d} / {total}  ({100*len(paired)/total:.0f}%)")
    print(f"  Unpaired (no PR found)     : {len(unpaired):4d} / {total}  ({100*len(unpaired)/total:.0f}%)")
    print(f"\n  Estimated total pairs (full {len(all_issues)} issues @ {100*len(paired)/total:.0f}%): "
          f"~{int(len(all_issues)*len(paired)/total)}")

    # --- Breakdown by label ---
    print("\nPairing rate by label (paired issues):")
    label_paired: Counter = Counter()
    label_total: Counter = Counter()
    for iss in population:
        labels = iss["labels"] or ["(unlabeled)"]
        has_pr = iss in paired
        for l in labels:
            label_total[l] += 1
            if has_pr:
                label_paired[l] += 1
    for label, total_l in label_total.most_common(15):
            p = label_paired[label]
            print(f"  {label:35s}: {p}/{total_l} ({100*p/total_l:.0f}%)")


if __name__ == "__main__":
    main()
