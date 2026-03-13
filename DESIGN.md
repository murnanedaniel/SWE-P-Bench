# SWE-P-Bench Design Document

## 1. Motivation and Core Idea

Standard SWE-bench relies on projects that practice test-driven development: a merged PR fixes a bug
*and* adds tests that would have caught it, so the benchmark can use those PR tests as the oracle.
High-energy physics (HEP) codebases rarely follow this pattern. PRs fix real bugs but seldom add
accompanying regression tests. This means a naïve port of SWE-bench to HEP would either:

- Produce very few valid instances (only the rare PRs that *do* add tests), or
- Have no test oracle and therefore no objective pass/fail criterion.

**The solution: LLM-synthesised test oracles.**

For each scraped issue–PR pair we use a high-quality LLM (e.g. Claude Opus / GPT-4o) to write
minimal tests that:
1. **FAIL** on the base commit (before the fix), and
2. **PASS** after the gold patch is applied.

We then validate this property by actually building and running the tests inside Docker. Only
validated instances enter the final benchmark. This gives us a rigorous, objective dataset without
requiring the upstream project to follow TDD.

---

## 2. Target Repositories

**Phase 1 (Python-only):** 7 Python HEP repositories, targeting **~1,000 validated instances**.
Phase 2 extends to C++ repos.

### Phase 1 — Python repositories

| Repository | Language | Build/Test | Closed issues (approx) |
|---|---|---|---|
| `scikit-hep/awkward` | Python | pytest | ~1,500 |
| `scikit-hep/uproot5` | Python | pytest | ~400 |
| `CoffeaTeam/coffea` | Python | pytest | ~500 |
| `scikit-hep/pyhf` | Python | pytest | ~300 |
| `scikit-hep/iminuit` | Python/C++ | pytest | ~300 |
| `zfit/zfit` | Python | pytest | ~300 |
| `scikit-hep/particle` | Python | pytest | ~150 |

**Estimated funnel for Phase 1:**

```
~3,000 closed issues
  × ~35% pairing rate (have linked merged PR)   →  ~1,050 raw candidates
  × ~80% quality filter pass rate               →    ~840 filtered candidates
  × ~70% LLM test validation yield (with retry) →    ~590 validated instances
                                                 ≈  O(1,000) benchmark instances
```

The Python case is well-suited to this scale: `pip install` takes seconds, pytest runs are
fast (~10–60s per instance), and LLMs generate reliable pytest code. The entire validation
pass for 840 candidates can run in ~25 CPU-hours, easily parallelised.

### Phase 2 — C++ repositories (deferred)

| Repository | Language | Build/Test | Notes |
|---|---|---|---|
| `acts-project/acts` | C++ | CMake + CTest/Catch2 | Already scraped; infrastructure exists |
| `root-project/root` | C++/Python | CMake + CTest | Very large; needs pre-built Docker image |
| `AIDASoft/DD4hep` | C++ | CMake + CTest | Detector description |
| `AIDASoft/podio` | C++ | CMake + CTest | Event data model I/O |
| `key4hep/EDM4hep` | C++ | CMake + CTest | Future collider EDM |
| `GooFit/GooFit` | C++/Python | CMake + pytest | GPU fitting |

C++ repos are deferred due to 15–30 min build times per instance and the added complexity of
CMake diffs for test registration. See §10 (Open Questions) for details.

**Selection criteria:** must have GitHub Issues (not JIRA/GitLab-only), active development history,
and a reasonable volume of closed issues linked to merged PRs.

---

## 3. Updated End-to-End Pipeline

```
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 1 — SCRAPING                                                       │
│  scraper/generic.py + repos.yml                                          │
│  • Fetch closed GitHub issues with linked merged PRs                     │
│  • Split PR diff → code patch vs test patch                              │
│  • Run per-repo, write data/{repo}/raw.jsonl                             │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 2 — QUALITY FILTERING                                              │
│  filter/quality.py                                                       │
│  • Automated filters: issue body length, diff size, file diversity       │
│  • Aim for ~840 filtered candidates (from ~1,050 raw) across all repos   │
│  • Write data/benchmark_candidates.jsonl                                 │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 3 — LLM TEST GENERATION                                            │
│  test_writer/generator.py                                                │
│  • For each candidate: issue + gold patch + relevant source files        │
│  • Prompt high-quality LLM to write minimal failing→passing tests        │
│  • Write generated test patch alongside instance                         │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 4 — TEST VALIDATION  ← core new infrastructure                    │
│  test_writer/validator.py                                                │
│  • Docker per repo; checkout base_commit                                 │
│  • Run generated tests → must FAIL                                       │
│  • Apply gold patch; run tests again → must PASS                         │
│  • Populate FAIL_TO_PASS / PASS_TO_PASS; discard instances that fail     │
│  • Write data/validated_benchmark.jsonl                                  │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 5 — SOLVING  (existing)                                            │
│  solver/{model}.py                                                       │
│  • LLM receives problem_statement + hints                                │
│  • Outputs predicted patch                                               │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 6 — EVALUATION  (extend existing)                                  │
│  evaluator/harness.py                                                    │
│  • Apply generated test_patch (from step 3/4)                            │
│  • Apply predicted patch; rebuild; run tests                             │
│  • Check FAIL_TO_PASS / PASS_TO_PASS                                     │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 7 — METRICS  (existing)                                            │
│  metrics/score.py                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Repository Configuration System

A central `repos.yml` (or `repos/` directory) captures per-repo metadata needed by the scraper,
validator, and evaluator:

```yaml
# repos.yml (sketch)
repos:
  acts-project/acts:
    language: cpp
    docker_image: ghcr.io/acts-project/ubuntu2404:latest
    build_cmd: |
      cmake -B build -S . -DCMAKE_BUILD_TYPE=Release \
        -DACTS_BUILD_UNITTESTS=ON -DACTS_BUILD_INTEGRATIONTESTS=ON
      cmake --build build --target UnitTests IntegrationTests -j$(nproc)
    test_cmd: ctest --test-dir build -R "{test_filter}" --output-on-failure
    test_framework: catch2        # informs how to parse results and write tests
    src_file_pattern: '\.(cpp|hpp|h|ipp|cuh|cu)$'
    test_file_pattern: 'Tests?/|tests?/|UnitTest|IntegrationTest'

  scikit-hep/awkward:
    language: python
    docker_image: python:3.11-slim
    build_cmd: pip install -e ".[dev,test]"
    test_cmd: pytest {test_files} -x -q
    test_framework: pytest
    src_file_pattern: '\.(py)$'
    test_file_pattern: 'tests?/|test_|_test\.py'
```

Key fields:
- `docker_image` — base image for build and test execution
- `build_cmd` — command to build/install the repo
- `test_cmd` — command to run a specific test file or filter
- `test_framework` — `catch2 | googletest | ctest | pytest | unittest`; controls LLM test-writing
  prompts and result parsing
- `src_file_pattern` / `test_file_pattern` — regex used by scraper diff splitter

---

## 5. LLM Test Generation Design

### 5.1 Context Assembly

For each candidate instance the generator fetches (from the repo at `base_commit`):

1. **Issue text** — `problem_statement` + `hints_text` (already in the instance)
2. **Gold patch** — the actual fix diff (`patch` field); tells the LLM *exactly* what changed
3. **Changed source files** — full file contents of every file touched by the gold patch
4. **Nearest existing test file(s)** — e.g. `tests/test_foo.py` or `Tests/UnitTest/FooTest.cpp`
   adjacent to the changed source; shows the LLM the testing idioms used in this repo

### 5.2 Prompt Strategy

```
System:
  You are an expert {language} engineer working on {repo}.
  You write minimal, self-contained tests that demonstrate a specific bug.
  A good test:
    - Fails on the code BEFORE the patch is applied.
    - Passes on the code AFTER the patch is applied.
    - Tests only the behaviour described in the issue; no unrelated assertions.
    - Follows the test framework and conventions of the repository (see examples below).

User:
  ## Issue
  {problem_statement}

  ## Gold fix (what changed to resolve the issue)
  {patch}

  ## Source files changed by the fix
  {source_file_contents}

  ## Existing test file for reference (style/conventions)
  {nearest_test_file}

  ## Task
  Write one or more test functions in {test_framework} style.
  Output ONLY the test code — no explanations, no markdown fences.
  The tests must go in: {suggested_test_file_path}
```

Model: Claude Opus or GPT-4o (configurable via `--test-model`).
Temperature: 0.2 (deterministic; can retry with higher temp if validation fails).

### 5.3 Retry Logic

If the generated tests fail validation (see §6), the generator retries up to **3 times**, each time:
- Feeding back the error output from the failed run
- Incrementally raising temperature (0.2 → 0.5 → 0.8)

---

## 6. Test Validation Design

Each candidate goes through a Docker-based validation pipeline:

```
checkout base_commit
↓
apply generated test_patch
↓
build / install repo
↓
run generated tests  ──► all must FAIL  (if any pass → invalid instance)
↓
apply gold patch (code only, not test_patch)
↓
rebuild / reinstall
↓
run generated tests  ──► all must PASS  (if any fail → invalid instance)
↓
record FAIL_TO_PASS list → instance is valid
```

**Discard conditions:**
- Generated tests cannot be parsed / applied
- Build fails (broken test code)
- Tests pass on base commit (test doesn't catch the bug)
- Tests fail even after gold patch (test is wrong or tests unrelated behaviour)

**Expected yield:** Based on SWE-bench experience, expect ~40–60% of LLM-generated tests to
validate on the first attempt; the retry loop should bring total yield to ~70–80%.

---

## 7. What Exists vs. What's Missing

### Already Built ✓

| Component | File | Status |
|---|---|---|
| ACTS-specific scraper | `scraper/acts.py` | Complete, battle-tested |
| Scraper statistics tool | `scraper/stats.py` | Complete |
| GPT-5-mini baseline solver | `solver/gpt5_mini.py` | Complete |
| Docker-based evaluator (ACTS) | `evaluator/harness.py` | Complete for ACTS; needs generalisation |
| Metrics and reporting | `metrics/score.py` | Complete, repo-agnostic |
| Instance schema | `README.md` | Documented |

### To Build ✗

| Component | Suggested Path | Priority | Description |
|---|---|---|---|
| Repo config registry | `repos.yml` | P0 | Per-repo build/test/Docker metadata |
| Generic multi-repo scraper | `scraper/generic.py` | P0 | Refactor `acts.py` → shared base |
| Quality filter | `filter/quality.py` | P1 | Filter ~1,050 raw candidates to ~840 |
| LLM test generator | `test_writer/generator.py` | P0 | Core new component |
| Test validator | `test_writer/validator.py` | P0 | Docker fail→pass verification |
| Generalized evaluator | `evaluator/harness.py` (extend) | P1 | Multi-repo Docker support |
| Data directory structure | `data/{repo}/` | P0 | One subdirectory per repo |

### Existing Code Requiring Modification

| File | Change Needed |
|---|---|
| `scraper/acts.py` | Extract generic logic into `scraper/generic.py`; `acts.py` becomes a thin wrapper |
| `evaluator/harness.py` | Load repo config from `repos.yml`; parameterise build/test commands |
| `README.md` | Update quick-start to reflect multi-repo pipeline |

---

## 8. Data Directory Structure

```
data/
├── repos.yml                         # repo registry
├── raw/                              # per-repo scraped candidates
│   ├── acts-project__acts.jsonl
│   ├── scikit-hep__awkward.jsonl
│   └── ...
├── benchmark_candidates.jsonl        # after quality filtering (~100 entries)
└── validated_benchmark.jsonl         # after test validation (final dataset)
```

Each instance in `validated_benchmark.jsonl` has all original SWE-bench fields plus:

```json
{
  "test_patch":        "<LLM-generated test diff>",
  "FAIL_TO_PASS":      ["test_function_name_1"],
  "PASS_TO_PASS":      [],
  "test_source":       "llm_generated",
  "test_model":        "claude-opus-4-6",
  "validation_passed": true
}
```

---

## 9. Implementation Roadmap

### Phase 1 — Python multi-repo scraping
1. Write `repos.yml` with configs for the 7 Python repos
2. Refactor `scraper/acts.py` → `scraper/generic.py` (repo config driven)
3. Run scraper across all Python repos; collect `data/raw/*.jsonl` (~1,050 raw candidates)
4. Write `filter/quality.py`; produce `data/benchmark_candidates.jsonl` (~840 filtered candidates)

### Phase 2 — LLM test generation and validation
5. Write `test_writer/generator.py` (context assembly + LLM prompting)
6. Write `test_writer/validator.py` (Docker fail→pass loop with retry)
7. Run on all ~840 candidates; expect ~590 validated instances (~70% yield)
8. Produce `data/validated_benchmark.jsonl` — target **O(1,000) instances**

### Phase 3 — Evaluation and reporting
9. Generalise `evaluator/harness.py` to consume `repos.yml`
10. Run baseline solver over validated benchmark
11. Evaluate and report results
12. Publish dataset and paper

### Phase 4 — C++ extension (future)
13. Add C++ repos to `repos.yml`; extend scraper and evaluator for CMake/CTest
14. Handle CMake diff generation for test registration
15. Use pre-built Docker images to keep validation tractable

---

## 10. Solver Model Strategy: Claude Code (Subscription) vs. API

### Why not the OpenAI/Anthropic API?

Early baseline runs used `gpt-5-mini` via the OpenAI API. The primary problems:
- **Quota exhaustion**: API rate limits truncated solver runs mid-batch; many patches came back
  empty because the API quota ran out.
- **Per-token cost**: At scale (~840 candidates × ~10k tokens each) a single oracle-generation
  pass costs $200–400 at Opus/GPT-4o pricing. Running multiple solvers multiplies this further.

### Recommended approach: Claude Code via subscription

[Claude Code](https://claude.ai/code) is the CLI that exposes Claude models (Sonnet, Opus) under
a flat subscription, **with no per-token billing**. This makes it practical to:

1. **Oracle generation** — run `test_writer/generator.py` against all ~840 candidates without
   worrying about per-call cost. Use `claude-sonnet-4-6` as the default; fall back to Opus for
   retries.
2. **Solver baseline** — `solver/claude_sonnet.py` invokes Claude Sonnet via the Anthropic SDK
   (or the `claude` CLI subprocess) with the same file-context prompt already used by
   `gpt5_mini.py`. Expected to outperform `gpt-5-mini` significantly given Sonnet's stronger
   coding ability.
3. **Interactive debugging** — the benchmark maintainers can open Claude Code in the repo and
   directly investigate failing instances without accumulating API spend.

### Implementation plan

| Component | Model | Mechanism |
|---|---|---|
| `test_writer/generator.py` | `claude-sonnet-4-6` | Anthropic SDK (`anthropic` package) |
| `test_writer/validator.py` (retry) | `claude-opus-4-6` | Anthropic SDK |
| `solver/claude_sonnet.py` | `claude-sonnet-4-6` | Anthropic SDK |
| `solver/gpt5_mini.py` | `gpt-5-mini` | OpenAI SDK (kept for comparison) |

The Anthropic SDK respects `ANTHROPIC_API_KEY` (or the subscription token when using Claude Code
Pro). The solver and oracle generator should check for `ANTHROPIC_API_KEY` in `.env` and fall back
to a warning if absent, rather than silently calling OpenAI.

---

## 11. Open Questions

- **Root project size:** `root-project/root` has thousands of issues and a very long build time.
  May need to cap instances or use a pre-built ROOT Docker image to keep validation tractable.
- **Test isolation in C++:** Catch2/GoogleTest tests are typically in a single binary; generated
  tests need to be added to the right `CMakeLists.txt`. The generator must also output the CMake
  diff, not just the `.cpp` diff.
- **Flaky tests:** Some generated tests may be non-deterministic. The validator should run each
  test 3 times before accepting it.
