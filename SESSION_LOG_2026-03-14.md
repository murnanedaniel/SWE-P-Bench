# Session Log — 2026-03-14

## Goal

Produce 50 high-quality benchmark instances across `pyhf`, `awkward`, and `uproot5` for SWE-P-Bench. Each instance needs a verified (issue, gold patch, oracle tests) triplet where oracles show FAIL→PASS behavior.

## What we did

### 1. Code changes

**`scripts/01b_filter.py`** — Added `--model` CLI arg with `claude:` prefix routing (same pattern as `test_writer/generator.py`). Default model changed from `gpt-5.4` to `claude:sonnet`. Removed the silent score-10 fallback when no API key is set.

**`scripts/06_quality_review.py`** — New script. For each gold-passing instance, calls Claude to rate the (issue, PR diff, oracle tests) triplet on three axes (causal connection, test relevance, test robustness). Accept threshold: all scores >= 3 and average >= 3.5.

**`llm/claude_cli.py`** — Fixed critical billing issue: `ANTHROPIC_API_KEY` was set in the environment, causing the `claude` CLI to route through the paid API instead of the Pro subscription. Fix: strip `ANTHROPIC_API_KEY` from the subprocess environment.

**`evaluator/python_harness.py`** — Fixed `SETUPTOOLS_USE_DISTUTILS=stdlib` → `local`. Python 3.12 removed stdlib `distutils`, so forcing `stdlib` caused every install to fail with `ModuleNotFoundError: No module named 'distutils'`. The `local` setting uses setuptools' bundled distutils instead.

**`scripts/01b_filter.py`** (incremental caching) — Each scored instance is now appended to `candidates_scored.jsonl` immediately after scoring, so progress survives interruptions. On restart, both `candidates_scored.jsonl` and `candidates_filtered.jsonl` are checked for already-processed instances.

**`test_writer/validator.py`** — Feedback from failed oracle generation attempts now accumulates across retries. Previously only the most recent failure was included in the prompt; now attempt 3 sees feedback from attempts 1 and 2.

### 2. Repo selection

Dropped `particle` — only 13 candidates total (too small). Replaced with `uproot5`.

### 3. Pipeline execution

#### Scraping (Step 3)

| Repo | Min date | Candidates scraped |
|---|---|---|
| pyhf | 2021-01-01 | 149 |
| uproot5 | 2022-01-01 | 84 |
| awkward | 2022-01-01 | 200 (capped) |
| **Total** | | **433** |

Note: 22 pre-2021 pyhf instances leaked through due to cached issue data from a previous run. The `--min-date` filter checks `merged_at` during PR linking, but cached PRs bypassed this check. These will fail to install and should be filtered out before the full oracle run.

#### Filtering (Step 4)

| Repo | Candidates | Passed filter | Pass rate |
|---|---|---|---|
| pyhf | 149 | 107 | 72% |
| uproot5 | 84 | 63 | 75% |
| awkward | 200 | 161 | 81% |
| **Total** | **433** | **331** | **76%** |

Using `claude:sonnet` via subscription. ~6–10s per instance. Incremental writes working.

#### Oracle generation pilot (Step 5 — 10 pyhf instances)

| Metric | Value |
|---|---|
| Instances tested | 10 |
| Install success | 10/10 (100%) |
| Valid oracles | 8/10 (80%) |
| Avg attempts for valid | 1.5 |

The two failures were genuine hard cases where Claude couldn't generate tests that distinguish pre/post patch behavior (tests failed both before and after across all 3 attempts).

#### Gold evaluation pilot (Step 6 — 10 pyhf instances)

| Metric | Value |
|---|---|
| Gold resolved | 7/10 (70%) |
| Of valid oracles: gold resolved | 7/8 (87.5%) |
| Failure modes | 1 patch-apply failure, 2 bad oracles |

## Bugs found and fixed

1. **Billing leak**: `ANTHROPIC_API_KEY` env var caused `claude` CLI to use paid API instead of Pro subscription. Potentially expensive if not caught.
2. **distutils crash**: `SETUPTOOLS_USE_DISTUTILS=stdlib` broke all installs on Python 3.12. This was the cause of the previous 21% pyhf pass rate — it wasn't oracle quality, it was install failures.
3. **No incremental caching**: Filter script wrote results only at the end. Killed jobs lost all progress.
4. **Non-cumulative retry feedback**: Oracle generator only showed the most recent failure to Claude on retry, losing context from earlier attempts.

## Where we are now

The pilot on 10 pyhf instances shows the pipeline is healthy:

```
Scrape → Filter (76%) → Oracle gen (80% valid) → Gold eval (87.5% of valid)
```

End-to-end yield estimate using pilot rates:

| Stage | Rate | pyhf (107) | uproot5 (63) | awkward (161) | Total |
|---|---|---|---|---|---|
| After filter | — | 107 | 63 | 161 | 331 |
| Valid oracles (80%) | 80% | 86 | 50 | 129 | 265 |
| Gold pass (87.5%) | 87.5% | 75 | 44 | 113 | 232 |
| Quality review (~80%) | 80% | 60 | 35 | 90 | 185 |

**Projected yield: ~185 accepted instances** — well above the 50 target. Even with conservative estimates and excluding pre-2021 install failures, we should comfortably hit 50.

## Next steps

1. Filter out pre-2021 instances from pyhf filtered dataset (22 will fail to install)
2. Run full oracle generation across all 3 repos (`--workers 1`, sequential via Claude subscription)
3. Run gold evaluation (`--workers 4`, parallelizable)
4. Run quality review (Step 7)
5. Assemble final 50 via `scripts/05_report.py`

Main time bottleneck: oracle generation at ~5–15 min per instance. 331 instances × ~10 min = ~55 hours if run sequentially. Can be split across repos and run in parallel sessions.
