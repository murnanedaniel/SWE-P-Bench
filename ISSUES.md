# SWE-P-Bench — Issues & Findings

This document records bugs, gaps, and design problems discovered during
full-loop demo runs (`run_demo.py` on `scikit-hep/awkward`).

**Run 4 (2026-03-12, mini production run on scikit-hep/particle):**
- **pip install failure on old commits** (FIXED): instances from pre-pyproject.toml
  era fail with `AttributeError: install_layout` under pip ≥ 22.3. Fixed by
  setting `SETUPTOOLS_USE_DISTUTILS=stdlib` in the subprocess environment inside
  `evaluator.python_harness._install_repo()`.  A `--no-build-isolation` fallback
  chain was also added.
- **Legacy `setuputils` dependency** (OPEN, severity: medium): `scikit-hep/particle`
  commit `5fc84a3b` (issue #9) uses `from setuputils import read` in `setup.py`.
  The `setuputils` package is not available on modern PyPI and cannot be installed.
  Instances at base commits that use this package will always fail install.
  Workaround: filter these out at scrape time or skip during oracle generation.
- **`compute_per_repo_metrics` uses wrong repo slug** (FIXED): function parsed
  `instance_id` (e.g. `scikit-hep__particle-24`) using only `rsplit("-",1)[0]`,
  giving `scikit-hep__particle` instead of `scikit-hep/particle`. Fixed by
  replacing the first `__` with `/` after stripping the issue number.
- **Solver patch apply failures dominate** (OPEN): primary failure mode for
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

### 1. Scraping requires GITHUB_TOKEN (unauthenticated rate limit = 60 req/hr)

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

### 2. No mechanism to fetch only N instances (scraper always scans all issues)

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

### 3. No `test_writer/` package existed before this PR

DESIGN.md lists `test_writer/generator.py` and `test_writer/validator.py` as
P0 requirements, but neither existed. Added by this PR:
- `test_writer/__init__.py`
- `test_writer/generator.py` — GPT-5-mini oracle test generation

Still missing: `test_writer/validator.py` — the Docker-based fail→pass
validation loop described in DESIGN.md §4 (Test Validation). Without it,
generated oracle tests are accepted without verification.

---

### 4. No `repos.yml` configuration registry

DESIGN.md §1 describes a per-repo config registry for build commands, test
frameworks, and file patterns. This file did not exist. Added by this PR.

The existing code (both `scraper/acts.py` and `evaluator/harness.py`) uses
hardcoded ACTS-specific values rather than loading from a registry.

**Fix needed:** Refactor `scraper/acts.py` and `evaluator/harness.py` to
accept a `repos.yml` config path and look up per-repo settings from it.

---

### 5. No `data/` directory structure

DESIGN.md describes `data/{repo}/candidates.jsonl` and a two-stage filtered
pipeline. No `data/` directory existed. Scripts that output to
`data/acts/candidates.jsonl` would fail silently on a fresh checkout because
there is no `mkdir -p` for the parent in some paths.

**Fix:** Added `mkdir -p` in `run_demo.py`. `scraper/acts.py:main()` already
calls `out.parent.mkdir(parents=True, exist_ok=True)` so that part is fine.

---

## Code Quality Issues

### 6. `solver/gpt5_mini.py` module name vs. filename mismatch

- **File:** `solver/gpt5_mini.py`
- **CLI docs in file:** `python -m solver.gpt4o_mini …`
- **`MODEL` constant:** `"gpt-5-mini"` (correct per user confirmation)

The internal usage docs say `gpt4o_mini` but the file is `gpt5_mini`. This
was likely renamed from gpt-4o-mini to gpt-5-mini mid-development without
updating the docstring. Minor, but confusing.

---

### 7. `solver/gpt5_mini.py` is ACTS/C++ specific — no Python repo variant

The system prompt says "expert C++ software engineer working on the ACTS
project" and requests C++17/20 patches. There is no Python-repo solver.

**Fix:** `run_demo.py` provides an inline Python solver prompt. A proper
`solver/python_solver.py` should be extracted for reuse.

---

### 8. `evaluator/harness.py` is ACTS/Docker only

The Docker evaluator is hardcoded to `ghcr.io/acts-project/ubuntu2404:latest`
and contains an inline CMake build script. There is no Python equivalent.

**Fix:** Added `evaluator/python_harness.py` in this PR. A longer-term
refactor should extract a common `BaseEvaluator` interface.

---

### 9. `_split_diff()` uses module-level hardcoded regex patterns

`scraper/acts.py:_split_diff()` uses module-level `_SRC_FILE_RE` and
`_TEST_FILE_RE` regex constants instead of accepting them as parameters.
DESIGN.md §repos.yml shows these as per-repo configurable fields.

**Fix:** Add `src_pat` and `test_pat` keyword arguments to `_split_diff()`
with the current values as defaults, then read from `repos.yml`.

**Location:** `scraper/acts.py:143` — `def _split_diff(diff_text: str)`

---

### 10. `evaluate_patch_mode()` clones directly from github.com

`evaluator/harness.py:evaluate_patch_mode()` clones repos via
`https://github.com/` with no mirror or proxy option. This fails in
network-restricted environments or when GitHub is rate-limiting git clones.

**Fix:** Add a `git_base_url` parameter defaulting to `"https://github.com"`.

---

### 11. `DOCKER_EVAL_SCRIPT` runs ALL unit tests, not just affected ones

The inline bash script in `evaluator/harness.py` runs `ctest -R '.*'` which
executes every ACTS unit test. For large repos this takes 30+ minutes. The
benchmark only needs to run the tests in `FAIL_TO_PASS` + `PASS_TO_PASS`.

**Fix:** Filter `ctest -R` to only the oracle test names from the instance.

---

### 12. `requirements.txt` missing `pyyaml`

Added `pyyaml>=6.0` to `requirements.txt` in this PR (needed for `repos.yml`
loading). The original file only had `requests`, `python-dotenv`, `openai`,
`tqdm`.

### 18. gpt-5-mini solver outputs non-standard "*** Begin Patch" diff format

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

### 13. `evaluator/python_harness.py` uses `sys.executable` which may lack pytest

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

### 14. Oracle test generator (GPT-5-mini) gets `ak.to_buffers` return order wrong

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

### 19. F-string syntax issue in run_demo.py (curly quote in f-string)

The initial version of `run_demo.py` used a Unicode curly quote (`"`) inside
an f-string, causing a `SyntaxError`. Python f-strings require the same quote
character to be escaped or avoided. Fixed in this PR.

---

### 14. Oracle test quality depends heavily on patch visibility

The oracle test generator (GPT-5-mini) is given the gold patch. If the patch
is large or touches many files, the model may generate tests that are too
specific to the implementation rather than the observable behaviour, leading
to brittle oracles. The DESIGN.md §3 (LLM Test Generation) notes this risk
but no guardrails are implemented yet.

---

### 15. `max_tokens` not supported by gpt-5-mini; must use `max_completion_tokens`

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

### 16. gpt-5-mini is a **reasoning model** — `max_completion_tokens` must be large (≥5000)

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

### 17. `temperature` not supported by gpt-5-mini — only default value (1) allowed

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

### 22. Solver outputs bare `@@` hunk separators without line numbers (compact format)

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

### 23. Zero-context solver guesses wrong file paths

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

## Summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | No GITHUB_TOKEN = rate limit hang | Critical | **Fixed** — abort with reset timestamp instead of sleeping |
| 2 | Scraper fetches all issues before returning first | High | **Fixed** — `scrape(max_instances=N)` param; workaround in run_demo.py removed |
| 3 | test_writer/ package missing | High | Fixed |
| 4 | repos.yml missing | High | Fixed |
| 5 | data/ directory not created | Medium | Fixed in run_demo.py |
| 6 | solver filename/docstring mismatch | Low | **Fixed** — docstring + CLI updated to gpt5_mini |
| 7 | Solver is C++ / ACTS specific | High | **Fixed** — language-aware system prompts via repos.yml |
| 8 | Evaluator is Docker / ACTS specific | High | Fixed (python_harness.py) |
| 9 | _split_diff() non-configurable regexes | Medium | **Fixed** — `src_pat`/`test_pat` params, loaded from repos.yml |
| 10 | evaluate_patch_mode() hardcoded GitHub URL | Medium | Open (ACTS/Docker path, not used in demo) |
| 11 | DOCKER_EVAL_SCRIPT runs all tests | Medium | Open (ACTS/Docker path, not used in demo) |
| 12 | requirements.txt missing pyyaml | Low | Fixed |
| 13 | sys.executable lacks pytest (python_harness) | High | **Fixed** — `_find_pytest_cmd()` with PATH fallback |
| 14 | Oracle test API hallucination (to_buffers order) | High | Open (needs test_writer/validator.py) |
| 15 | max_tokens not supported by gpt-5-mini | High | Fixed |
| 16 | gpt-5-mini reasoning model needs ≥5000 tokens | High | Fixed |
| 17 | temperature not supported by gpt-5-mini | High | **Fixed** — `temperature` param and `--temperature` CLI arg removed |
| 18 | gpt-5-mini solver outputs "*** Begin Patch" format | High | **Fixed** — `_normalize_patch()` in solver/gpt5_mini.py |
| 19 | F-string curly quote syntax error | Low | Fixed |
| 20 | Oracle test brittleness (design) | Medium | Open (design) |
| 21 | test_writer/validator.py not implemented | High | **Fixed** — implemented with clone-once retry loop |
| 22 | Solver outputs bare `@@` hunk separators | High | **Fixed** — `_normalize_bare_hunk_headers()` + `--recount` |
| 23 | Zero-context solver guesses wrong file paths | High | **Fixed** — file-context baseline: `fetch_source_context()` fetches real source files at `base_commit` and includes them in the solver prompt |
