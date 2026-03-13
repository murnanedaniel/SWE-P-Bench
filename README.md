# SWE-P-Bench: Physics Software Engineering Benchmark

A SWE-bench-style benchmark for high-energy physics (HEP) software projects. Given a repository snapshot and issue description, a model must produce a patch that resolves the issue — validated by LLM-generated oracle tests that satisfy the FAIL→PASS invariant.

## Key Design Note

Standard SWE-bench relies on merged PRs adding regression tests. HEP projects rarely do this, so SWE-P-Bench instead uses an LLM to synthesise oracle tests that:
1. **FAIL** on the buggy code (before the patch)
2. **PASS** on the fixed code (after the patch)

These are validated by actually running them in a cloned environment before being accepted.

---

## Models

| Use case | Model |
|---|---|
| R&D (oracle generation + solving) | `gpt-5-mini` |
| Production / frontier baseline | `gpt-5.4` |

> **Always use `gpt-5-mini` during R&D.** It is fast and cheap. Only switch to `gpt-5.4` for final benchmarking runs.

---

## Supported Repositories

**Phase 1 — Python (active):**

| Repo | Install |
|---|---|
| `scikit-hep/particle` | `pip install -e ".[dev]"` |
| `scikit-hep/pyhf` | `pip install -e ".[dev]"` |
| `scikit-hep/uproot5` | `pip install -e ".[dev]"` |
| `scikit-hep/hist` | `pip install -e ".[dev]"` |
| `scikit-hep/iminuit` | `pip install -e ".[dev]"` |
| `scikit-hep/decaylanguage` | `pip install -e ".[dev]"` |
| `scikit-hep/awkward` | `pip install -e ".[dev]"` |
| `CoffeaTeam/coffea` | `pip install -e ".[dev]"` |
| `zfit/zfit` | `pip install -e ".[dev]"` |

**Phase 2 — C++ (deferred):**
- `acts-project/acts` — harness implemented, evaluation via Docker + CMake

---

## Pipeline

```
01_scrape.py → 01b_filter.py → 02_gen_oracles.py → 03_solve.py → 04_evaluate.py → 05_report.py
```

All scripts are idempotent — safe to re-run; existing outputs are skipped.

### Step 1 — Scrape

```bash
python scripts/01_scrape.py \
    --repos scikit-hep/particle,scikit-hep/pyhf \
    --max-instances 20 \
    --min-date 2023-01-01
# Output: data/{owner}/{name}/candidates.jsonl
```

Scrapes closed GitHub issues with linked merged PRs. Splits diffs into code patch vs test patch.

### Step 2 — Filter

```bash
python scripts/01b_filter.py --dataset data/scikit-hep/particle/candidates.jsonl
# Output: candidates_filtered.jsonl, candidates_scored.jsonl
```

Two-stage quality filter:
- **Filter A (free):** Removes bulk data-entry PRs (high ratio of data lines)
- **Filter B (LLM):** Uses `gpt-5.4` to score issue/patch relevance 0–10; drops instances below `--min-score 6`

### Step 3 — Generate Oracles

```bash
# R&D: always use gpt-5-mini
python scripts/02_gen_oracles.py \
    --dataset data/scikit-hep/particle/candidates_filtered.jsonl \
    --model gpt-5-mini \
    --workers 4
# Output: data/{owner}/{name}/oracles/{instance_id}.py + .meta.json
```

Generates pytest oracle tests and validates them by running in a cloned environment. Retries with error feedback on failure (up to `--max-attempts 3`).

### Step 4 — Solve

```bash
# R&D: always use gpt5_mini solver
python scripts/03_solve.py \
    --dataset data/scikit-hep/particle/candidates_filtered.jsonl \
    --solver gpt5_mini \
    --only-valid-oracles \
    --workers 4
# Output: results/gpt5_mini/{owner}/{name}/{instance_id}.patch
```

Thin wrapper that calls `solver.{name}.solve_dataset()`. The `gpt5_mini` solver uses a file-context baseline: it fetches modified source files from GitHub at `base_commit` and asks the model for a unified diff.

### Step 5 — Evaluate

```bash
python scripts/04_evaluate.py \
    --dataset data/scikit-hep/particle/candidates_filtered.jsonl \
    --solver gpt5_mini \
    --workers 8
# Output: results/gpt5_mini/evals/{owner}/{name}/{instance_id}.json + summary.jsonl

# Evaluate gold patches (upper bound):
python scripts/04_evaluate.py \
    --dataset data/scikit-hep/particle/candidates_filtered.jsonl \
    --gold --workers 8
```

Clones repo at `base_commit`, installs, runs oracle tests before/after applying the patch, computes FAIL_TO_PASS and PASS_TO_PASS.

### Step 6 — Report

```bash
python scripts/05_report.py \
    --solvers gold,gpt5_mini_1shot,gpt54_1shot \
    --dataset-dir data
```

Prints a comparison table: oracle validity rate + resolve rate per solver per repo.

---

## Directory Structure

```
SWE-P-Bench/
├── scripts/          # Pipeline (01–05 above)
├── scraper/
│   └── generic.py    # GitHub issue/PR scraper
├── test_writer/
│   ├── generator.py  # LLM oracle test generation
│   └── validator.py  # Clone + run to validate FAIL→PASS
├── solver/
│   ├── gpt5_mini.py  # GPT-5-mini file-context baseline (R&D)
│   └── gpt54.py      # GPT-5.4 frontier baseline
├── evaluator/
│   ├── python_harness.py  # Python repo evaluation (clone + pytest)
│   └── harness.py         # C++ / ACTS evaluation (Docker + CMake)
├── metrics/
│   └── score.py      # Metrics and reporting helpers
├── data/             # gitignored — scraped/oracle data lives here locally
├── results/          # gitignored — solver outputs and eval results
├── repos.yml         # Registry of supported repos and config
└── requirements.txt
```

> `data/scikit-hep/`, `results/`, and `.scraper_cache/` are in `.gitignore`. Do not force-add them.

---

## Environment Variables

```bash
GITHUB_TOKEN=...    # Recommended for scraping (5000 req/hr vs 60 without)
OPENAI_API_KEY=...  # Required for filtering, oracle generation, and solving
```

---

## Quick Start (R&D run on one repo)

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=...
export OPENAI_API_KEY=...

REPO=scikit-hep/particle

python scripts/01_scrape.py --repos $REPO --max-instances 20
python scripts/01b_filter.py --dataset data/$REPO/candidates.jsonl
python scripts/02_gen_oracles.py --dataset data/$REPO/candidates_filtered.jsonl --model gpt-5-mini --workers 4
python scripts/03_solve.py --dataset data/$REPO/candidates_filtered.jsonl --solver gpt5_mini --only-valid-oracles --workers 4
python scripts/04_evaluate.py --dataset data/$REPO/candidates_filtered.jsonl --solver gpt5_mini --workers 8
python scripts/05_report.py --solvers gpt5_mini_1shot
```

---

## Dataset Schema

Each instance in `candidates.jsonl` follows the SWE-bench schema:

```json
{
  "instance_id": "scikit-hep__particle-123",
  "repo": "scikit-hep/particle",
  "base_commit": "<sha>",
  "problem_statement": "<issue title + body>",
  "hints_text": "<issue comments before first PR commit>",
  "patch": "<gold fix diff>",
  "test_patch": "<test-file changes from PR>",
  "FAIL_TO_PASS": [],
  "PASS_TO_PASS": [],
  "created_at": "2024-01-01T00:00:00Z",
  "pr_number": 456,
  "issue_number": 123
}
```

Oracle `.meta.json` adds: `is_valid`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `error`.
