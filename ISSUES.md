# SWE-P-Bench — Issues & Findings

This document records bugs, gaps, and design problems discovered during
full-loop demo runs (`run_demo.py` on `scikit-hep/awkward`).

**Run 5 (2026-03-18/19, benchmark v1 assembly + gold/Claude evaluation):**
- **Three evaluator bugs found and fixed** (issues #24, #25, #26 below): gold
  patches were being run through LLM-patch normalisation, the evaluator ignored
  `meta.json` `is_valid`, and the solver ignored the benchmark subset. Full
  write-ups in `CLAUDE.md`. Net effect: pyhf gold went from 9/42 (21.4%) to
  42/63 (66.7%) — **every gold number recorded before 2026-03-18 is invalid.**
- **Three new open problems** (issues #27, #28, #29 below): missing PEP-517
  build backends in the eval venv, `benchmark_v1.jsonl` violating its own
  gold-resolvable invariant, and 4 instances the solver resolves but gold does not.
- See `RESULTS.md` for the reconciled result tables and caveats.

**Run 4 (2026-03-12, mini production run on scikit-hep/particle):**
- **pip install failure on old commits** (FIXED): instances from pre-pyproject.toml
  era fail with `AttributeError: install_layout` under pip ≥ 22.3. Fixed by
  setting `SETUPTOOLS_USE_DISTUTILS=stdlib` in the subprocess environment inside
  `evaluator.python_harness._install_repo()`.  A `--no-build-isolation` fallback
  chain was also added.
- **Legacy `setuputils` dependency** ⚠️ OPEN (severity: medium): `scikit-hep/particle`
  commit `5fc84a3b` (issue #9) uses `from setuputils import read` in `setup.py`.
  The `setuputils` package is not available on modern PyPI and cannot be installed.
  Instances at base commits that use this package will always fail install.
  Workaround: filter these out at scrape time or skip during oracle generation.
- **`compute_per_repo_metrics` uses wrong repo slug** (FIXED): function parsed
  `instance_id` (e.g. `scikit-hep__particle-24`) using only `rsplit("-",1)[0]`,
  giving `scikit-hep__particle` instead of `scikit-hep/particle`. Fixed by
  replacing the first `__` with `/` after stripping the issue number.
- **Solver patch apply failures dominate** ⚠️ OPEN: primary failure mode for
  `gpt5_mini` is `patch apply failed` — model generates syntactically valid diffs
  but with wrong target file paths or mismatched context lines. This accounts for
  ≥3 of the 8 valid-oracle failures in both 1-shot and 3-shot runs. See issue #23.
  More attempts help marginally (1→2 resolved) but path normalisation is the real fix.

**Run 3 (2026-03-11, after validator added):**
- Oracle test validator (`test_writer/validator.py`) implemented and working.
  Retry fired on attempt 1 (tests failed both before AND after gold patch on
  first generation); attempt 2 produced valid tests after error feedback.
  FAIL_TO_PASS = [test_oracle_001, test_oracle_002, test_oracle_003].
- Patch normalization for bare-`@@` format implemented in `_normalize_patch()`
  (Issue #22). Solver output now has proper hunk headers.
- Solver still produces wrong file paths (Issue #23): it guesses
  `awkward/_v2/from_buffers.py` but the real file is
  `src/awkward/operations/ak_from_buffers.py`. `git apply` fails because the
  file does not exist at the guessed path. This is the primary remaining
  blocker for the solver evaluation step.

**Run 2 (2026-03-11, refactoring sprint):**
- scraper/generic.py, max_instances, rate-limit abort, YAML patterns all
  working. run_demo.py simplified significantly. Solver language-aware.

**Run 1 (2026-03-08, initial full-loop):**
- Initial findings documented below.

---

## Critical Blockers

### ~~1. Scraping requires GITHUB_TOKEN (unauthenticated rate limit = 60 req/hr)~~ ✅ RESOLVED

**Symptom:** On the first run in a clean environment without `GITHUB_TOKEN`,
the scraper immediately hits GitHub's unauthenticated rate limit (60 req/hr
shared per IP). In a shared compute environment (e.g. CI workers, cloud
instances), the shared IP is often already at 0 remaining when the run starts.

**Impact:** `run_demo.py --skip-eval` hangs for up to 60 minutes waiting for
the rate limit to reset instead of failing fast.

**Fix needed:**
- Fail immediately if `GITHUB_TOKEN` is not set (raise, don't wait).
- Or require `GITHUB_TOKEN` as a mandatory env var rather than optional.
- Better UX: print the reset timestamp and exit with a clear error instead of
  sleeping indefinitely.

**Location:** `scraper/acts.py:_get()` — the backoff sleeps without checking
if the token is absent.

---

### ~~2. No mechanism to fetch only N instances (scraper always scans all issues)~~ ✅ RESOLVED

**Symptom:** `scraper/acts.py:scrape()` always fetches ALL closed issues
before returning any. For `scikit-hep/awkward` (~1,500 issues) this means
hundreds of API calls just to get one example.

**Impact:** Demo is impractical without a `--max-instances 1` short-circuit.

**Fix needed:** Add `max_instances: int = 0` parameter to `scrape()`. Stop
collecting once that many valid instances are found. The new `run_demo.py`
uses a custom `scrape_first_instance()` workaround instead.

**Location:** `scraper/acts.py:scrape()` — add early exit in the inner loop.

---

## Design Gaps (P0 Items from DESIGN.md Not Yet Implemented)

### ~~3. No `test_writer/` package existed before this PR~~ ✅ RESOLVED

DESIGN.md lists `test_writer/generator.py` and `test_writer/validator.py` as
P0 requirements, but neither existed. Added by this PR:
- `test_writer/__init__.py`
- `test_writer/generator.py` — GPT-5-mini oracle test generation

Still missing: `test_writer/validator.py` — the Docker-based fail→pass
validation loop described in DESIGN.md §4 (Test Validation). Without it,
generated oracle tests are accepted without verification.

---

### ~~4. No `repos.yml` configuration registry~~ ✅ RESOLVED

DESIGN.md §1 describes a per-repo config registry for build commands, test
frameworks, and file patterns. This file did not exist. Added by this PR.

The existing code (both `scraper/acts.py` and `evaluator/harness.py`) uses
hardcoded ACTS-specific values rather than loading from a registry.

**Fix needed:** Refactor `scraper/acts.py` and `evaluator/harness.py` to
accept a `repos.yml` config path and look up per-repo settings from it.

---

### ~~5. No `data/` directory structure~~ ✅ RESOLVED

DESIGN.md describes `data/{repo}/candidates.jsonl` and a two-stage filtered
pipeline. No `data/` directory existed. Scripts that output to
`data/acts/candidates.jsonl` would fail silently on a fresh checkout because
there is no `mkdir -p` for the parent in some paths.

**Fix:** Added `mkdir -p` in `run_demo.py`. `scraper/acts.py:main()` already
calls `out.parent.mkdir(parents=True, exist_ok=True)` so that part is fine.

---

## Code Quality Issues

### ~~6. `solver/gpt5_mini.py` module name vs. filename mismatch~~ ✅ RESOLVED

- **File:** `solver/gpt5_mini.py`
- **CLI docs in file:** `python -m solver.gpt4o_mini …`
- **`MODEL` constant:** `"gpt-5-mini"` (correct per user confirmation)

The internal usage docs say `gpt4o_mini` but the file is `gpt5_mini`. This
was likely renamed from gpt-4o-mini to gpt-5-mini mid-development without
updating the docstring. Minor, but confusing.

---

### ~~7. `solver/gpt5_mini.py` is ACTS/C++ specific — no Python repo variant~~ ✅ RESOLVED

The system prompt says "expert C++ software engineer working on the ACTS
project" and requests C++17/20 patches. There is no Python-repo solver.

**Fix:** `run_demo.py` provides an inline Python solver prompt. A proper
`solver/python_solver.py` should be extracted for reuse.

---

### ~~8. `evaluator/harness.py` is ACTS/Docker only~~ ✅ RESOLVED

The Docker evaluator is hardcoded to `ghcr.io/acts-project/ubuntu2404:latest`
and contains an inline CMake build script. There is no Python equivalent.

**Fix:** Added `evaluator/python_harness.py` in this PR. A longer-term
refactor should extract a common `BaseEvaluator` interface.

---

### ~~9. `_split_diff()` uses module-level hardcoded regex patterns~~ ✅ RESOLVED

`scraper/acts.py:_split_diff()` uses module-level `_SRC_FILE_RE` and
`_TEST_FILE_RE` regex constants instead of accepting them as parameters.
DESIGN.md §repos.yml shows these as per-repo configurable fields.

**Fix:** Add `src_pat` and `test_pat` keyword arguments to `_split_diff()`
with the current values as defaults, then read from `repos.yml`.

**Location:** `scraper/acts.py:143` — `def _split_diff(diff_text: str)`

---

### 10. `evaluate_patch_mode()` clones directly from github.com ⚠️ OPEN (ACTS/Docker path, not blocking)

`evaluator/harness.py:evaluate_patch_mode()` clones repos via
`https://github.com/` with no mirror or proxy option. This fails in
network-restricted environments or when GitHub is rate-limiting git clones.

**Fix:** Add a `git_base_url` parameter defaulting to `"https://github.com"`.

---

### 11. `DOCKER_EVAL_SCRIPT` runs ALL unit tests, not just affected ones ⚠️ OPEN (ACTS/Docker path, not blocking)

The inline bash script in `evaluator/harness.py` runs `ctest -R '.*'` which
executes every ACTS unit test. For large repos this takes 30+ minutes. The
benchmark only needs to run the tests in `FAIL_TO_PASS` + `PASS_TO_PASS`.

**Fix:** Filter `ctest -R` to only the oracle test names from the instance.

---

### ~~12. `requirements.txt` missing `pyyaml`~~ ✅ RESOLVED

Added `pyyaml>=6.0` to `requirements.txt` in this PR (needed for `repos.yml`
loading). The original file only had `requests`, `python-dotenv`, `openai`,
`tqdm`.

### ~~18. gpt-5-mini solver outputs non-standard "*** Begin Patch" diff format~~ ✅ RESOLVED

**Symptom:** The predicted patch from `run_demo.py` step 3 starts with
`*** Begin Patch` and uses `*** Update File:` headers instead of the
standard unified diff format (`diff --git a/… b/…`).

**Impact:** `git apply` and `patch -p1` both reject the patch:
```
git apply: error: No valid patches in input
patch: **** Only garbage was found in the patch input.
```

**Fix needed:** The solver system prompt says "Output ONLY the raw unified
diff, nothing else." but the model ignores this and uses its own format.
Options:
1. Add a post-processing step to parse "*** Begin Patch" format and convert
   to unified diff.
2. Add examples of correct diff format in the system prompt (few-shot).
3. Request JSON-wrapped diff output and parse it.

**Location:** `solver/gpt5_mini.py:SYSTEM_PROMPT` — improve format guidance.

---

## Runtime Observations

### ~~13. `evaluator/python_harness.py` uses `sys.executable` which may lack pytest~~ ✅ RESOLVED

**Symptom:** `pytest BEFORE patch` runs but captures empty output `{}`. The
actual reason is `/usr/bin/python3: No module named pytest`.

**Root cause:** `sys.executable` resolves to `/usr/bin/python3` (or
`/usr/bin/python`), which is the system Python. The `pytest` command on PATH
may be installed in a separate tool environment (e.g. `uv` managed). Running
`sys.executable -m pytest` fails silently when pytest is not installed in that
specific Python's site-packages.

**Fix:** `evaluator/python_harness.py` should:
1. Check `shutil.which('pytest')` as a fallback.
2. Or install pytest as part of the `pip install -e .` step.
3. Or document `pytest` as a required system dependency in `requirements.txt`.

The fix used in this session: `pip install pytest` into the active Python.

---

### 14. Oracle test generator (GPT-5-mini) gets `ak.to_buffers` return order wrong ⚠️ OPEN (needs validator retry loop)

**Symptom:** Generated tests use `form, buffers, length = ak.to_buffers(...)`
but actual API returns `form, length, container = ak.to_buffers(...)`.
This causes a `TypeError` at test execution (passing int as dict and vice versa).

**Impact:** All 3 oracle tests return `{}` before/after (collection error, not
a proper FAIL). The DESIGN.md §4 (Test Validation) addresses this with a
Docker fail→pass cycle that would catch this — but `test_writer/validator.py`
is not yet implemented.

**Fix needed:** Implement `test_writer/validator.py` to run generated tests in
isolation and retry with a correction prompt if they error at collection.
Meanwhile, adding few-shot examples of correct API usage in the generator
prompt would help.

---

### ~~19. F-string syntax issue in run_demo.py (curly quote in f-string)~~ ✅ RESOLVED

The initial version of `run_demo.py` used a Unicode curly quote (`"`) inside
an f-string, causing a `SyntaxError`. Python f-strings require the same quote
character to be escaped or avoided. Fixed in this PR.

---

### 20. Oracle test quality depends heavily on patch visibility ⚠️ OPEN (design trade-off)

The oracle test generator (GPT-5-mini) is given the gold patch. If the patch
is large or touches many files, the model may generate tests that are too
specific to the implementation rather than the observable behaviour, leading
to brittle oracles. The DESIGN.md §3 (LLM Test Generation) notes this risk
but no guardrails are implemented yet.

---

### ~~15. `max_tokens` not supported by gpt-5-mini; must use `max_completion_tokens`~~ ✅ RESOLVED

**Symptom:** `openai.BadRequestError: 400 — 'max_tokens' is not supported with
this model. Use 'max_completion_tokens' instead.`

**Impact:** `test_writer/generator.py` and `solver/gpt5_mini.py` both used the
deprecated `max_tokens` parameter, causing every API call to fail immediately.

**Fix:** Changed all three call sites (`test_writer/generator.py`,
`solver/gpt5_mini.py`, inline solver in `run_demo.py`) from `max_tokens=` to
`max_completion_tokens=`.

**Location:**
- `test_writer/generator.py:123`
- `solver/gpt5_mini.py:87`

### ~~16. gpt-5-mini is a **reasoning model** — `max_completion_tokens` must be large (≥5000)~~ ✅ RESOLVED

**Symptom:** With small `max_completion_tokens` (e.g. 2048 or 4096), the model
returns an empty `content` field. Inspecting the response shows
`reasoning_tokens = max_completion_tokens` and `output_tokens = 0`.

**Root cause:** gpt-5-mini (id: `gpt-5-mini-2025-08-07`) is a reasoning model
like o1/o3-mini. The `max_completion_tokens` budget covers BOTH internal
reasoning tokens and final output tokens. If the reasoning phase exhausts the
budget before the model writes its output, `content` is empty.

**Fix:** Increase `max_completion_tokens` to 8000. At this budget, a typical
request uses ~500-1000 reasoning tokens and ~200-600 output tokens.

**Impact:** All three call sites originally had `max_tokens=2048`/`4096`
(already wrong — see issue #15). After fixing to `max_completion_tokens`, the
budget still needs to be large enough for reasoning to complete.

**Location:** `test_writer/generator.py`, `solver/gpt5_mini.py`, `run_demo.py`

### ~~17. `temperature` not supported by gpt-5-mini — only default value (1) allowed~~ ✅ RESOLVED

**Symptom:** `openai.BadRequestError: 400 — 'temperature' does not support
0.2 with this model. Only the default (1) value is supported.`

**Impact:** The `temperature=0.2` in solver and test generator both fail immediately.

**Fix:** Removed `temperature=` from all gpt-5-mini calls. For reasoning models,
determinism is controlled internally — the `temperature` parameter is not exposed.

**Location:**
- `test_writer/generator.py`
- `solver/gpt5_mini.py` (also: `solve_dataset` accepts `--temperature` CLI arg
  but it is now silently unused — should be removed or raise a warning)
- Inline solver in `run_demo.py`

---

---

### ~~22. Solver outputs bare `@@` hunk separators without line numbers (compact format)~~ ✅ RESOLVED

**Symptom:** The solver outputs a unified diff where hunk separators appear as
` @@` (a space-prefixed `@@` line, treated as a context line) rather than a
proper `@@ -N,C +N,C @@` header.  Both `git apply` and `patch -p1` reject it:
```
git apply: error: patch with only garbage at line 4
```

**Fix:** Added `_normalize_bare_hunk_headers()` in `solver/gpt5_mini.py`.
The normalizer detects ` @@` separators, counts context/added/removed lines
per hunk, and inserts proper `@@ -N,C +N,C @@` headers.  `git apply --recount`
is then used so it recalculates positions from the context even if our estimated
line numbers are slightly off.

**Location:** `solver/gpt5_mini.py:_normalize_patch()` — now dispatches to
`_normalize_bare_hunk_headers()` when bare-@@ format is detected.

---

### ~~23. Zero-context solver guesses wrong file paths~~ ✅ RESOLVED

**Symptom:** The solver generates a syntactically valid patch but uses
invented file paths (e.g. `awkward/_v2/from_buffers.py`) rather than the
actual repo path (`src/awkward/operations/ak_from_buffers.py`).
`git apply` fails because the file does not exist at the guessed path.

**Root cause:** The zero-context solver has no access to the repo file tree,
so it guesses paths from the issue description and convention.  For repos that
have moved files (e.g. `awkward` migrated from `_v2/` to `src/` layout) the
guesses are wrong.

**Impact:** `evaluate_python_instance()` returns `resolved=False` with
`error="patch apply failed"` even when the patch logic is correct.

**Fix applied (file-context baseline):**
`fetch_source_context()` added to `solver/gpt5_mini.py`. It parses
`instance["patch"]` for file paths, then fetches each from
`raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}` using
`urllib.request` (stdlib, timeout=10 s). Content is included in the prompt
under `## Source Files` with a ground-truth instruction to the model.
Large files are truncated to 500 lines. All fetches are best-effort — errors
are silently skipped and the solver degrades to zero-context if nothing can be
fetched.

A complementary path-correction fallback (`_fix_patch_paths()`) was also added
to `evaluator/python_harness.py` and `test_writer/validator.py` as a last-resort
fallback in case path names still diverge slightly despite context being available.

---

## Benchmark v1 Run (2026-03-18/19)

### ~~24. Gold patches corrupted by LLM-patch normalisation in evaluator~~ ✅ RESOLVED

**Severity: Critical.** `evaluator/python_harness.py` ran `_normalize_patch()` and
`_correct_hunk_positions()` on *all* patches, including gold patches taken verbatim
from GitHub's API. Normalisation mangles blank context lines and hunk counts, so
valid diffs failed to apply and were scored as unresolved. 31 of 47 valid oracles
failed gold re-evaluation with "patch apply failed".

`test_writer/validator.py` already had a comment warning against exactly this and
correctly skipped normalisation for gold — the evaluator and validator had drifted.

**Fix:** added an `is_gold` parameter to `evaluate_python_instance()`; when true,
both normalisation steps are skipped and only a trailing newline is ensured.
Threaded through from `04_evaluate.py --gold`.

**Impact:** invalidates every gold figure recorded before 2026-03-18. pyhf gold
went 9/42 (21.4%) → 42/63 (66.7%). `particle` and `decaylanguage` have still not
been re-evaluated. See `RESULTS.md`.

### ~~25. Evaluator evaluated instances with invalid oracles~~ ✅ RESOLVED

**Severity: High.** `02_gen_oracles.py` writes a `.py` oracle file for every
attempt, including failed ones (intentional, for debugging) — validity lives in
`.meta.json` `is_valid`. `04_evaluate.py` only checked that the `.py` existed, so
it evaluated 220 instances when only 108 had valid oracles: 112 pointless
clone+install+test cycles, worst on awkward (94 attempted, 15 valid).

**Fix:** `04_evaluate.py` now reads `.meta.json` and skips anything without
`is_valid: true`. Missing or unparseable meta counts as invalid.

### ~~26. Solver processed all instances instead of the benchmark subset~~ ✅ RESOLVED

**Severity: Medium.** `03_solve.py` solved 161 awkward instances when only 8 were
in the benchmark; `--only-valid-oracles` was opt-in rather than the default.
Filtering in `03_solve.py` alone was also insufficient, because solver modules
re-read `dataset_path` internally and never saw the filtered list.

**Fix:** inverted the flag to `--include-invalid-oracles` (valid-only is now the
default); added `--benchmark` to both `03_solve.py` and `04_evaluate.py`; and
`03_solve.py` now writes the filtered instances to a temp JSONL that the solver
module reads.

### 27. Missing PEP-517 build backends in eval environment ⚠️ OPEN

**Severity: High.** 7 of the 19 gold failures on benchmark v1 are a single
environment fault, not a benchmark-content failure:

```
pip install failed: ModuleNotFoundError: No module named 'hatchling'
```

The build backend is absent from the eval venv, so any instance whose
`pyproject.toml` declares `hatchling` (or another backend not already installed)
fails at install and scores as unresolved.

**Impact:** severely distorts per-repo rates. uproot5 loses 4/9 benchmark
instances (13/30 across the full set), awkward 2/8, pyhf 1/33. Excluding install
failures and 2 instances with no eval record, gold is 31/41 (75.6%) rather than
the headline 31/50 (62.0%) — close to the ~80% target in GitHub issue #7.

**Fix direction:** install the common PEP-517 backends (`hatchling`,
`hatch-vcs`, `setuptools_scm`, `flit_core`, `poetry-core`) into the eval
environment, or extend the existing `--no-build-isolation` fallback chain in
`_install_repo()` to pre-install the backend named in `build-system.requires`.
Re-run gold afterwards.

### 28. `benchmark_v1.jsonl` violates its own gold-resolvable invariant ⚠️ OPEN

**Severity: High.** `07_assemble_benchmark.py` selects only instances where gold
resolves, reading `results/gold/evals/{owner}/{name}/{iid}.json`. It was run at
12:48 on 2026-03-18, against the **pre-fix** gold evals (issue #24). The post-fix
gold rerun that evening (23:15–00:05) overwrote those eval files, and 19 of the
50 selected instances no longer pass gold.

The committed `data/benchmark_v1.jsonl` therefore no longer satisfies the property
it was constructed to guarantee.

**Note:** the artifact was deliberately *not* regenerated, because `paper/instances.tex`
was generated from this exact file — re-assembling silently would desync the paper.
Re-assembly and paper regeneration must happen together, and after issue #27 is
fixed (otherwise install failures will wrongly exclude good instances).

### 29. Four instances resolved by solver but not by gold ⚠️ OPEN

**Severity: Medium.** `pyhf-1349`, `pyhf-1389`, `pyhf-1491`, `pyhf-1662` are
resolved by `claude_sonnet_1shot` but recorded as `f2p_ok: false` for gold, with
oracle tests running both before and after in each case (so this is not an install
or patch-apply artifact). Gold is the reference fix and should be an upper bound
on any solver, so this indicates oracle nondeterminism or evaluator flakiness.

Confounder to rule out first: the `claude_sonnet_1shot` evals predate the issue
#24 fix while the gold evals postdate it, so the two were not produced by the same
evaluator code. Re-run the solver under the fixed harness before investigating
the oracles themselves.

---

## Summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | No GITHUB_TOKEN = rate limit hang | Critical | ✅ abort with reset timestamp |
| 2 | Scraper fetches all issues before returning first | High | ✅ `scrape(max_instances=N)` param |
| 3 | test_writer/ package missing | High | ✅ implemented |
| 4 | repos.yml missing | High | ✅ implemented |
| 5 | data/ directory not created | Medium | ✅ mkdir -p in scripts |
| 6 | solver filename/docstring mismatch | Low | ✅ docstring + CLI updated |
| 7 | Solver is C++ / ACTS specific | High | ✅ language-aware prompts via repos.yml |
| 8 | Evaluator is Docker / ACTS specific | High | ✅ python_harness.py added |
| 9 | _split_diff() non-configurable regexes | Medium | ✅ `src_pat`/`test_pat` params |
| 10 | evaluate_patch_mode() hardcoded GitHub URL | Medium | ⚠️ OPEN (ACTS/Docker path only) |
| 11 | DOCKER_EVAL_SCRIPT runs all tests | Medium | ⚠️ OPEN (ACTS/Docker path only) |
| 12 | requirements.txt missing pyyaml | Low | ✅ added |
| 13 | sys.executable lacks pytest | High | ✅ `_find_pytest_cmd()` with PATH fallback |
| 14 | Oracle test API hallucination | High | ⚠️ OPEN (needs validator retry loop) |
| 15 | max_tokens not supported by gpt-5-mini | High | ✅ use `max_completion_tokens` |
| 16 | gpt-5-mini reasoning model needs ≥5000 tokens | High | ✅ budget set to 8000 |
| 17 | temperature not supported by gpt-5-mini | High | ✅ `temperature` param removed |
| 18 | gpt-5-mini outputs "*** Begin Patch" format | High | ✅ `_normalize_patch()` added |
| 19 | F-string curly quote syntax error | Low | ✅ fixed |
| 20 | Oracle test brittleness (design) | Medium | ⚠️ OPEN (design trade-off) |
| 21 | test_writer/validator.py not implemented | High | ✅ clone-once retry loop |
| 22 | Solver outputs bare `@@` hunk separators | High | ✅ `_normalize_bare_hunk_headers()` + `--recount` |
| 23 | Zero-context solver guesses wrong file paths | High | ✅ `fetch_source_context()` at base_commit |
| 24 | Gold patches corrupted by LLM-patch normalisation | Critical | ✅ `is_gold` flag skips normalisation |
| 25 | Evaluator ran instances with invalid oracles | High | ✅ `04_evaluate.py` checks `meta.json` `is_valid` |
| 26 | Solver ignored benchmark subset | Medium | ✅ `--benchmark` flag + temp-file filtering |
| 27 | Missing PEP-517 build backends (`hatchling`) in eval env | High | ⚠️ OPEN (distorts 7/19 gold failures) |
| 28 | `benchmark_v1.jsonl` violates gold-resolvable invariant | High | ⚠️ OPEN (needs re-assembly after #27) |
| 29 | Solver resolves 4 pyhf instances that gold does not | Medium | ⚠️ OPEN (rule out harness mismatch first) |
