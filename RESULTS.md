# SWE-P-Bench Results

Benchmark results for the SWE-P-Bench pipeline. Add your solver by following
the instructions in [CONTRIBUTING](#contributing).

---

## Benchmark v1 — `scikit-hep/{pyhf,uproot5,awkward}` (50 instances)

**Date:** 2026-03-18 / 2026-03-19
**Dataset:** `data/benchmark_v1.jsonl` (50 instances — pyhf 33, uproot5 9, awkward 8; seed 42)
**Evaluator:** post-fix (see [Evaluator corrections](#evaluator-corrections-2026-03-18) below)

### Overall Results

| Solver                | Repo                     | Instances | Resolved | Rate      |
|-----------------------|--------------------------|----------:|---------:|----------:|
| `gold`                | scikit-hep/pyhf          |        33 |       26 | 78.8%     |
| `gold`                | scikit-hep/uproot5       |         9 |        2 | 22.2%     |
| `gold`                | scikit-hep/awkward       |         8 |        3 | 37.5%     |
| **`gold` TOTAL**      |                          |    **50** |   **31** | **62.0%** |
| `claude_sonnet_1shot` | scikit-hep/pyhf          |        33 |       18 | 54.5%     |
| `claude_sonnet_1shot` | scikit-hep/uproot5       |         9 |        1 | 11.1%     |
| `claude_sonnet_1shot` | scikit-hep/awkward       |         8 |        2 | 25.0%     |
| **`claude_sonnet_1shot` TOTAL** |                |    **50** |   **21** | **42.0%** |

> ⚠️ **This gold run is degraded — do not cite 62.0% as the gold ceiling.**
> 7 of the 19 gold failures are a single environment bug, not a benchmark-content
> failure: `pip install failed: ModuleNotFoundError: No module named 'hatchling'`
> (the build backend is missing from the eval venv). A further 2 instances
> (`awkward-1377`, `awkward-2384`) have no eval record at all.
> Excluding both classes, gold resolves **31/41 = 75.6%**.
> uproot5 and awkward are worst hit (4/9 and 2/8 install failures respectively),
> which is why their rates look implausibly low.

**Known inconsistencies (unresolved — these need attention before publishing):**

1. **`benchmark_v1.jsonl` violates its own construction invariant.**
   `07_assemble_benchmark.py` selects only instances where gold resolves, but it
   was run at 12:48 against the *pre-fix* gold evals. The post-fix gold rerun
   (23:15–00:05) overwrote those eval files, and 19/50 selected instances no
   longer pass. The benchmark must be re-assembled from the corrected evals.
2. **4 instances where the solver beats gold.** `pyhf-1349`, `pyhf-1389`,
   `pyhf-1491`, `pyhf-1662` are resolved by `claude_sonnet_1shot` but recorded
   as F2P-failed for gold, with tests running both before and after. Since gold
   is the reference fix, this points at oracle nondeterminism or eval flakiness
   rather than genuine solver superiority.
3. **Solver and gold ran against different evaluator code.** The
   `claude_sonnet_1shot` evals predate the 22:45 harness fix; gold does not.
   The two columns above are therefore not strictly comparable.

**Next steps:** (1) install `hatchling` (and other PEP-517 backends) in the eval
environment and re-run gold; (2) re-assemble `benchmark_v1` from corrected evals;
(3) re-run `claude_sonnet_1shot` under the fixed harness; (4) investigate the
4 gold-fails-solver-passes instances.

---

## Evaluator corrections (2026-03-18)

Three pipeline bugs were fixed on 2026-03-18 (full write-ups in `CLAUDE.md`).
The first invalidates every gold number recorded before that date:

**Gold patches were being run through LLM-patch normalisation**, which corrupts
valid GitHub diffs by mangling blank context lines and hunk counts, producing
spurious "patch apply failed" results. Effect on the pyhf gold baseline:

| Measurement                          | Gold resolve rate |
|--------------------------------------|------------------:|
| Pre-fix (2026-03-13, recorded below) |  9/42 = **21.4%** |
| Post-fix (2026-03-19)                | 42/63 = **66.7%** |

Post-fix gold over all evaluated instances (not benchmark-scoped):

| Repo               | Resolved | Rate  | of which install failures |
|--------------------|---------:|------:|--------------------------:|
| scikit-hep/pyhf    |    42/63 | 66.7% |                         3 |
| scikit-hep/uproot5 |     9/30 | 30.0% |                        13 |
| scikit-hep/awkward |     8/15 | 53.3% |                         5 |

The `hatchling` install failure inflates the failure count in all three rows,
uproot5 most severely.

---

## Production Run — `scikit-hep/{particle,pyhf,decaylanguage}` (filtered datasets)

> ⚠️ **SUPERSEDED — pre-fix numbers, retained for history.** All gold figures in
> this section were produced by the buggy evaluator described above and understate
> gold. The pyhf row is corrected there (21.4% → 66.7%). **`particle` and
> `decaylanguage` were never re-evaluated post-fix**, so their gold rates below
> (63.8% / 16.7%) remain uncorrected and should not be cited.

**Date:** 2026-03-13
**Repos:** `scikit-hep/particle`, `scikit-hep/pyhf`, `scikit-hep/decaylanguage`
**Instances (candidates_filtered.jsonl):** 46 / 255 / 18 respectively
**Valid oracles:** 46/46 (particle), 34/255 (pyhf), 18/18 (decaylanguage)

### Overall Results

| Solver            | Repo                          | Instances | Resolved | Rate   |
|-------------------|-------------------------------|----------:|---------:|-------:|
| `gold`            | scikit-hep/particle           |        47 |       30 | 63.8%  |
| `gold`            | scikit-hep/pyhf               |        42 |        9 | 21.4%  |
| `gold`            | scikit-hep/decaylanguage      |        18 |        3 | 16.7%  |
| **`gold` TOTAL**  |                               |   **107** |   **42** | **39.3%** |
| `gpt5_mini_1shot` | scikit-hep/particle           |        47 |        2 |  4.3%  |
| `gpt5_mini_1shot` | scikit-hep/pyhf               |        16 |        0 |  0.0%  |
| **`gpt5_mini_1shot` TOTAL** |                   |    **63** |    **2** |  **3.2%** |

**Key observations:**
- Gold resolves 39.3% across 107 instances: strong for particle (63.8%), moderate for pyhf
  (21.4%) and decaylanguage (16.7%).
- `gpt5_mini_1shot` resolved 2/63 (3.2%). The low rate is primarily due to OpenAI API quota
  exhaustion mid-run: most new particle patches were empty (failed API calls) and pyhf patches
  had apply/install failures. The 2 resolved instances came from the 7 pre-existing patches.
- pyhf is harder: only 34/255 filtered instances have valid oracles (~13%), and patch-apply
  failures are common due to complex diffs. More oracle coverage needed.
- Next steps: (1) add more oracle coverage for pyhf/decaylanguage, (2) re-run solver with
  sufficient quota, (3) evaluate additional solvers (gpt5_mini_3shot, gpt54_1shot).

---

## Mini Run — `scikit-hep/particle` (10 instances)

> ⚠️ **Pre-fix evaluator** (see [Evaluator corrections](#evaluator-corrections-2026-03-18)).
> Gold reaches 8/8 on installable instances here, so this run was not visibly
> affected — but it has not been re-verified post-fix.

**Date:** 2026-03-12
**Repo:** `scikit-hep/particle`
**Instances scraped:** 10
**Valid oracles:** 8/10 (80.0%)
**Oracle model:** `gpt-5-mini` (3 tests × 3 attempts)

> **Note on gold baseline:** Gold resolves 8/10 total instances.
> The 2 failures are known-bad: `particle-9` (legacy `setuputils` build system,
> uninstallable at that commit) and `particle-55` (oracle tests pass before the
> patch — indistinguishable from the fixed version). Excluding these,
> gold resolves **8/8 installable instances (100%)**, confirming oracle quality.

### Overall Results

| Solver            | Instances | Valid Oracles | Resolved | Resolve Rate |
|-------------------|----------:|:-------------:|---------:|-------------:|
| `gold`            |        10 | 8/10          |        8 |       80.0%  |
| `gpt5_mini_1shot` |        10 | 8/10          |        2 |       20.0%  |
| `gpt5_mini_3shot` |        10 | 8/10          |        2 |       20.0%  |
| `gpt54_1shot`     |        10 | 8/10          |        2 |       20.0%  |

**Key observations:**
- All three baselines resolve 2/10 (20%) — `gpt-5.4` matches `gpt-5-mini` on this sample.
- `gpt5_mini_1shot` improved from 1→2 with the hunk-recount + progressive-fuzz fix
  (particle-49 now applies; previously "malformed patch" due to wrong hunk counts).
- `gpt54_1shot` uses OpenAI's frontier `gpt-5.4` model (2026-03-05, 1.05M ctx); on this
  10-instance sample the quality difference is not statistically significant.
- Remaining failures are genuinely wrong patches (tests run but don't pass),
  one patch-apply failure (particle-41/49), and the two known-bad instances.
- The patch apply pipeline now matches SWE-bench's fallback chain
  (`git apply` → `git apply --3way` → `patch --fuzz=5` → `patch --fuzz=8`)
  plus hunk-count normalisation for LLM-generated diffs.

---

## Adding Your Solver

1. Implement `solver/your_solver.py` with a `solve_dataset()` function matching
   the signature in `solver/gpt5_mini.py`.
2. Run the pipeline:
   ```bash
   python scripts/03_solve.py \
     --dataset data/scikit-hep/particle/candidates.jsonl \
     --solver your_solver --attempts 1
   python scripts/04_evaluate.py \
     --dataset data/scikit-hep/particle/candidates.jsonl \
     --solver your_solver_1shot
   python scripts/05_report.py \
     --solvers gold,gpt5_mini_1shot,gpt5_mini_3shot,your_solver_1shot
   ```
3. Copy the updated table here and open a PR.

---

## Reproducing These Results

```bash
# Prerequisites: OPENAI_API_KEY in .env; GITHUB_TOKEN recommended
python scripts/01_scrape.py --repos scikit-hep/particle --max-instances 10
python scripts/02_gen_oracles.py --dataset data/scikit-hep/particle/candidates.jsonl --workers 2
python scripts/03_solve.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt5_mini --attempts 1
python scripts/03_solve.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt5_mini --attempts 3
python scripts/04_evaluate.py --dataset data/scikit-hep/particle/candidates.jsonl --gold --workers 4
python scripts/04_evaluate.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt5_mini_1shot --workers 4
python scripts/04_evaluate.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt5_mini_3shot --workers 4
python scripts/03_solve.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt54 --attempts 1
python scripts/04_evaluate.py --dataset data/scikit-hep/particle/candidates.jsonl --solver gpt54_1shot --workers 4
python scripts/05_report.py --solvers gold,gpt5_mini_1shot,gpt5_mini_3shot,gpt54_1shot
```
