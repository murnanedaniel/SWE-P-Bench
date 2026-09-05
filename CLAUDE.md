# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

SWE-P-Bench is a SWE-bench-style benchmark for high-energy physics (HEP) software. Given a repo snapshot and issue description, a model produces a patch — validated by LLM-generated oracle tests satisfying the FAIL→PASS invariant (tests FAIL before the fix, PASS after). This replaces the standard SWE-bench assumption that merged PRs include regression tests.

## Setup

```bash
pip install -r requirements.txt
# Required env vars (use .env or export):
export GITHUB_TOKEN=...    # 5000 req/hr vs 60 without
export OPENAI_API_KEY=...  # For OpenAI solvers/filter
# Claude solvers use subscription CLI (no API key needed)
```

## Pipeline

All scripts are **idempotent** — existing outputs are skipped, safe to re-run/resume.

```bash
REPO=scikit-hep/particle

# 1. Scrape GitHub issues + linked PRs
python scripts/01_scrape.py --repos $REPO --max-instances 20

# 2. Filter (heuristic + LLM relevance scoring)
python scripts/01b_filter.py --dataset data/$REPO/candidates.jsonl

# 3. Generate + validate oracle tests (FAIL→PASS)
python scripts/02_gen_oracles.py --dataset data/$REPO/candidates_filtered.jsonl --model gpt-5-mini --workers 4

# 4. Solve (produce patches — filters to valid oracles by default)
python scripts/03_solve.py --dataset data/$REPO/candidates_filtered.jsonl --solver gpt5_mini --workers 4

# 5. Evaluate (clone, install, run oracles before/after patch)
python scripts/04_evaluate.py --dataset data/$REPO/candidates_filtered.jsonl --solver gpt5_mini --workers 8

# 6. Report (comparison table across solvers)
python scripts/05_report.py --solvers gold,gpt5_mini_1shot,gpt54_1shot
```

`run_demo.py` runs the full pipeline end-to-end on a single instance.

## Architecture

**Pipeline scripts** (`scripts/01-05`): Thin CLI wrappers that parse args and call into library modules. Each writes output to `data/` or `results/` directories.

**Core modules:**
- `scraper/generic.py` — GitHub issue/PR scraper; issue-first approach (find issues, then linked merged PRs); splits diffs into code patch vs test patch
- `test_writer/generator.py` — LLM oracle test generation (OpenAI or Claude CLI backends)
- `test_writer/validator.py` — Validates oracles by cloning repo, running pytest before/after gold patch; retry loop with error feedback (up to 3 attempts)
- `solver/` — Solver backends (`gpt5_mini`, `gpt54`, `claude_sonnet`); file-context approach fetching source files at `base_commit` from GitHub
- `evaluator/python_harness.py` — Clone → install → write oracle → pytest before → apply patch → pytest after; cascading patch-apply fallbacks (git apply → patch -p1 with increasing fuzz)
- `metrics/score.py` — Scoring and comparison table generation
- `llm/claude_cli.py` — Claude subscription CLI bridge (shells out to `claude -p`)

**Configuration:** `repos.yml` is the central registry — per-repo language, install command, install fallback extras, test command, file patterns, test directory.

## Key Conventions

- **R&D model:** Use `gpt-5-mini` during development; `gpt-5.4` only for final benchmarking runs.
- **Claude solver:** Use `--workers 1` (subscription concurrency limits).
- **Adding a new repo:** Update `repos.yml` with all fields.
- **Adding a new solver:** Create `solver/my_solver.py` with a `solve_dataset(dataset_path, out_dir, ...)` function.
- **Parallel execution** uses `ThreadPoolExecutor` (not ProcessPoolExecutor).
- **Patch normalization** lives in `solver/gpt5_mini.py` (`_normalize_patch`) and is imported by the evaluator.
- `data/`, `results/`, `.scraper_cache/` are gitignored — never force-add them.

## Data Flow

```
data/{owner}/{name}/candidates.jsonl          ← scraper output
data/{owner}/{name}/candidates_filtered.jsonl ← filtered subset
data/{owner}/{name}/oracles/{instance_id}.py  ← oracle test files
data/{owner}/{name}/oracles/{instance_id}.meta.json ← validation metadata
results/{solver}/{owner}/{name}/{instance_id}.patch  ← solver predictions
results/{solver}/evals/{owner}/{name}/{instance_id}.json ← eval results
results/{solver}/evals/summary.jsonl          ← aggregated eval summary
```

## Instance Schema

Each instance follows the SWE-bench schema: `instance_id`, `repo`, `base_commit`, `problem_statement`, `hints_text`, `patch` (gold fix), `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `created_at`, `pr_number`, `issue_number`.

Oracle `.meta.json` adds: `is_valid`, `oracle_tests`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `error`.

## Known Bugs Found & Fixed (March 2026)

### Bug 1: Gold patch normalization corruption in evaluator

**Symptom:** 31 out of 47 valid oracles failed gold re-evaluation with "patch apply failed".

**Root cause:** `evaluator/python_harness.py` ran `_normalize_patch()` on ALL patches, including gold patches from GitHub's API. Normalization corrupts valid diffs by mangling blank context lines and hunk counts. The validator (`test_writer/validator.py`) already had a comment warning against this (line 222-226) and correctly skipped normalization for gold patches.

**Fix:** Added `is_gold` parameter to `evaluate_python_instance()`. When `True`, skips `_normalize_patch()` and `_correct_hunk_positions()`. Threaded through from `04_evaluate.py --gold`.

**Lesson:** The evaluator and validator must handle gold patches identically. `_normalize_patch()` is only for LLM-generated patches with non-standard formats. Never apply it to gold patches.

### Bug 2: Evaluator evaluated instances with invalid oracles

**Symptom:** `04_evaluate.py` processed 220 instances when only 108 had valid oracles — 112 pointless clone+install+test cycles (especially bad for awkward: 94 attempted, only 15 valid).

**Root cause:** `02_gen_oracles.py` writes `.py` oracle files for ALL attempts, even when validation fails (`is_valid: false` in `.meta.json`). This is intentional for debugging. But `04_evaluate.py` only checked if the `.py` file existed — it never read `meta.json` to check `is_valid`.

**Fix:** Added `is_valid` check in `04_evaluate.py`: after confirming the `.py` file exists, also read the `.meta.json` and skip instances where `is_valid` is not `true`.

**Lesson:** Oracle `.py` files exist for ALL generated oracles (valid or not). Any script that consumes oracles MUST check `meta.json` `is_valid` before proceeding. The `.py` file existing does NOT mean the oracle is usable.

### Bug 3: Solver processed all instances instead of benchmark subset

**Symptom:** `03_solve.py` solved 161 awkward instances when only 8 were in the benchmark. `--only-valid-oracles` was opt-in, not default.

**Fix:** (a) Changed `--only-valid-oracles` to `--include-invalid-oracles` (inverted default — now filters by default). (b) Added `--benchmark` flag to both `03_solve.py` and `04_evaluate.py` to restrict to benchmark instances. (c) Fixed `03_solve.py` to write filtered instances to a temp JSONL before passing to solver modules (which re-read the dataset file internally).

**Lesson:** Solver modules (`solver/*.py`) re-read `dataset_path` internally — filtering in `03_solve.py` alone is insufficient. The temp-file approach ensures the solver module only sees filtered instances.

## Pipeline Filtering Invariants

These invariants MUST hold for the pipeline to work correctly:

1. **`02_gen_oracles.py`** writes `.py` + `.meta.json` for every attempt. Invalid oracles have `is_valid: false` in meta.json but the `.py` file still exists on disk.
2. **`04_evaluate.py`** MUST check `meta.json` `is_valid` before evaluating. Never trust `.py` existence alone.
3. **`04_evaluate.py --gold`** MUST pass `is_gold=True` to `evaluate_python_instance()` to skip patch normalization. Gold patches are valid diffs; normalization corrupts them.
4. **`03_solve.py`** filters to valid oracles by default. To include invalid oracles, use `--include-invalid-oracles`.
5. **`03_solve.py`** must write filtered instances to a temp file before calling `solver_mod.solve_dataset()`, because solver modules re-read the dataset file independently.
6. **Benchmark-scoped runs** should use `--benchmark data/benchmark_v1.jsonl` to restrict to assembled benchmark instances only.
