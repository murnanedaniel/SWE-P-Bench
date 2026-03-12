# SWE-P-Bench Results

Benchmark results for the SWE-P-Bench pipeline. Add your solver by following
the instructions in [CONTRIBUTING](#contributing).

---

## Mini Run — `scikit-hep/particle` (10 instances)

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

**Key observations:**
- Both baselines now resolve 2/10 (20%) after patch apply improvements.
- `gpt5_mini_1shot` improved from 1→2 with the hunk-recount + progressive-fuzz fix
  (particle-49 now applies; previously "malformed patch" due to wrong hunk counts).
- Remaining failures are genuinely wrong patches (tests run but don't pass),
  one empty patch (particle-24, 1shot), and the two known-bad instances.
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
python scripts/05_report.py --solvers gold,gpt5_mini_1shot,gpt5_mini_3shot
```
