"""
Python repo evaluator for SWE-P-Bench.

Evaluates a predicted patch by running pytest before and after applying it:
  1. Clone repo at base_commit into a temporary directory.
  2. Install the library with pip (uses repos.yml install_extras when available).
  3. Write oracle tests to a temp test file in the cloned repo.
  4. Run pytest BEFORE the patch → capture which tests fail/pass.
  5. Apply the predicted patch with `git apply` (fallback to `patch -p1`).
  6. Run pytest AFTER the patch → capture results.
  7. Compute FAIL_TO_PASS and PASS_TO_PASS lists.

Unlike the ACTS Docker evaluator, no Docker or CMake is needed for pure Python
repos. Cloning happens over HTTPS so GITHUB_TOKEN is not required here.

Usage:
    from evaluator.python_harness import evaluate_python_instance
    result = evaluate_python_instance(instance, oracle_code, predicted_patch)

    # With repos.yml config for better install_extras:
    from scraper.generic import load_repo_config
    cfg = load_repo_config(instance["repo"])
    result = evaluate_python_instance(instance, oracle_code, predicted_patch,
                                      repo_config=cfg)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Lazy import to avoid circular dependency — solver imports nothing from evaluator
def _normalize_patch(patch: str) -> str:
    """Delegate to solver.gpt5_mini._normalize_patch (normalises *** Begin Patch
    and bare-@@ formats).  Falls back to returning *patch* unchanged if the
    import fails for any reason."""
    try:
        from solver.gpt5_mini import _normalize_patch as _np
        return _np(patch)
    except Exception:
        return patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 300,
) -> tuple[int, str]:
    """Run *cmd*, return (returncode, combined stdout+stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 1, f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except Exception as e:
        return 1, str(e)


def _find_pytest_cmd() -> list[str]:
    """Return a working pytest invocation.

    Tries ``sys.executable -m pytest`` first (correct when pytest is installed
    in the same virtual environment as the harness).  Falls back to the
    ``pytest`` binary on PATH, which is correct when the harness runs under a
    different interpreter than the repo under test.

    Raises RuntimeError if pytest cannot be found at all.
    """
    rc, _ = _run([sys.executable, "-m", "pytest", "--version"], timeout=10)
    if rc == 0:
        return [sys.executable, "-m", "pytest"]

    pytest_bin = shutil.which("pytest")
    if pytest_bin:
        return [pytest_bin]

    raise RuntimeError(
        "pytest not found. Install it with: pip install pytest"
    )


_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "build", "dist", ".eggs",
    ".egg-info", ".tox", ".nox", ".venv", "venv", "node_modules",
})


def _fix_patch_paths(patch_text: str, repo_dir: Path) -> str | None:
    """
    Attempt to fix incorrect file paths in *patch_text* by fuzzy-matching
    file basenames against the actual contents of *repo_dir*.

    When the solver guesses wrong paths (e.g. ``awkward/_v2/foo.py`` instead
    of the real ``src/awkward/operations/foo.py``), this function:

    1. Finds every path declared in ``diff --git a/PATH`` headers.
    2. For each path that does *not* exist in *repo_dir*, searches the tree
       for a file with the same name (basename).
    3. If exactly one candidate exists, substitutes it.
       If multiple exist, picks the one whose directory components most
       overlap with the guessed path.
    4. Returns a corrected patch string, or ``None`` if any path cannot be
       resolved (so the caller knows the correction is incomplete).
    """
    patch_paths = re.findall(r"^diff --git a/(\S+)", patch_text, re.MULTILINE)
    if not patch_paths:
        return None

    corrections: dict[str, str] = {}
    for wrong_path in patch_paths:
        if (repo_dir / wrong_path).exists():
            continue  # already correct

        basename = Path(wrong_path).name
        stem = Path(wrong_path).stem
        suffix = Path(wrong_path).suffix  # e.g. ".py"

        def _ok(p: Path) -> bool:
            return not any(part in _SKIP_DIRS for part in p.parts)

        # Pass 1: exact basename match (e.g. same filename, different dir)
        candidates = [p for p in repo_dir.rglob(basename) if _ok(p)]

        # Pass 2: stem-suffix match — real filename ends with the guessed stem
        # e.g. guess "from_buffers.py" → matches "ak_from_buffers.py"
        if not candidates and suffix:
            candidates = [
                p for p in repo_dir.rglob(f"*{stem}{suffix}")
                if _ok(p) and p.name != basename  # avoid re-finding exact matches
            ]

        if not candidates:
            return None  # no match at all → can't safely fix

        if len(candidates) == 1:
            rel = candidates[0].relative_to(repo_dir)
        else:
            # Pick the candidate whose parent dirs most overlap with the guess
            wrong_parts = set(Path(wrong_path).parts[:-1])
            rel = max(
                candidates,
                key=lambda m: len(wrong_parts & set(m.relative_to(repo_dir).parts[:-1])),
            ).relative_to(repo_dir)

        corrections[wrong_path] = rel.as_posix()

    if not corrections:
        return None  # all paths were already fine (shouldn't reach here)

    corrected = patch_text
    for wrong, correct in corrections.items():
        corrected = corrected.replace(wrong, correct)
    return corrected


def _parse_pytest_output(output: str) -> dict[str, bool]:
    """
    Parse pytest -v output into {test_name: passed}.

    Matches lines like:
        tests/test_foo.py::test_oracle_001 PASSED
        tests/test_foo.py::test_oracle_002 FAILED
        test_oracle_003 ERROR
    """
    results: dict[str, bool] = {}
    for line in output.splitlines():
        m = re.search(r"::(\w+)\s+(PASSED|FAILED|ERROR)", line)
        if m:
            results[m.group(1)] = m.group(2) == "PASSED"
    return results


def _install_repo(
    repo_dir: Path,
    repo_config: dict | None = None,
) -> tuple[bool, str]:
    """
    Install the repo with pip, trying several extras combinations.

    If *repo_config* is provided and contains ``install_extras``, those are
    used as the list of extras to try.  Otherwise falls back to the hardcoded
    defaults.

    Returns (success, last_output).
    """
    # Build the extras list from config or defaults
    if repo_config and repo_config.get("install_extras"):
        extras_list = repo_config["install_extras"]
    else:
        extras_list = [".[dev,test]", ".[dev]", ".[test]", "."]

    attempts = [
        [sys.executable, "-m", "pip", "install", "-e", extras, "-q"]
        for extras in extras_list
    ]

    last_out = ""
    for cmd in attempts:
        rc, out = _run(cmd, cwd=str(repo_dir), timeout=600)
        last_out = out
        if rc == 0:
            return True, out
    return False, last_out


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

def evaluate_python_instance(
    instance: dict,
    oracle_test_code: str,
    predicted_patch: str,
    repo_config: dict | None = None,
) -> dict:
    """
    Evaluate *predicted_patch* against *oracle_test_code* for *instance*.

    Args:
        instance:          SWE-P-Bench record with 'repo' and 'base_commit'.
        oracle_test_code:  Python pytest module string (the oracle tests).
        predicted_patch:   Unified diff to evaluate.
        repo_config:       Optional per-repo config from repos.yml (used for
                           install_extras).

    Returns:
        Result dict with keys:
            instance_id, resolved, mode, install_ok,
            before_results, after_results, f2p_ok, p2p_ok,
            FAIL_TO_PASS, PASS_TO_PASS, oracle_tests, error
    """
    repo = instance["repo"]
    base_commit = instance.get("base_commit", "")
    instance_id = instance.get("instance_id", repo)

    result: dict = {
        "instance_id": instance_id,
        "resolved": False,
        "mode": "python",
        "install_ok": False,
        "before_results": {},
        "after_results": {},
        "f2p_ok": False,
        "p2p_ok": True,   # vacuously true when there are no p2p tests
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
        "oracle_tests": [],
        "error": None,
    }

    # Resolve pytest command once (raises if not found)
    try:
        pytest_cmd = _find_pytest_cmd()
    except RuntimeError as exc:
        result["error"] = str(exc)
        print(f"  [error] {exc}", file=sys.stderr)
        return result

    with tempfile.TemporaryDirectory(prefix="swepbench_") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        # ------------------------------------------------------------------
        # Step 1: Clone
        # ------------------------------------------------------------------
        print(f"  Cloning https://github.com/{repo} …", file=sys.stderr)
        rc, out = _run(
            ["git", "clone", f"https://github.com/{repo}.git", str(repo_dir)],
            timeout=300,
        )
        if rc != 0:
            result["error"] = f"git clone failed: {out[:500]}"
            print(f"  [error] {result['error']}", file=sys.stderr)
            return result

        if base_commit:
            rc, out = _run(
                ["git", "checkout", base_commit],
                cwd=str(repo_dir),
            )
            if rc != 0:
                result["error"] = f"git checkout {base_commit[:8]} failed: {out[:300]}"
                print(f"  [error] {result['error']}", file=sys.stderr)
                return result

        # ------------------------------------------------------------------
        # Step 2: Install
        # ------------------------------------------------------------------
        print(f"  Installing {repo} …", file=sys.stderr)
        install_ok, install_out = _install_repo(repo_dir, repo_config=repo_config)
        result["install_ok"] = install_ok
        if not install_ok:
            result["error"] = f"pip install failed: {install_out[-500:]}"
            print(f"  [error] pip install failed (see error field)", file=sys.stderr)
            return result

        # ------------------------------------------------------------------
        # Step 3: Write oracle tests
        # ------------------------------------------------------------------
        test_file = repo_dir / "test_oracle_swepbench.py"
        test_file.write_text(oracle_test_code)

        test_names = re.findall(r"^def (test_\w+)", oracle_test_code, re.MULTILINE)
        result["oracle_tests"] = test_names

        # ------------------------------------------------------------------
        # Step 4: Run pytest BEFORE patch
        # ------------------------------------------------------------------
        print(f"  pytest BEFORE patch …", file=sys.stderr)
        rc, before_out = _run(
            pytest_cmd + [
                str(test_file), "-v", "--tb=short", "--no-header",
                "-p", "no:cacheprovider",
            ],
            cwd=str(repo_dir),
            timeout=120,
        )
        before_results = _parse_pytest_output(before_out)
        result["before_results"] = before_results
        print(f"    {before_results}", file=sys.stderr)

        # ------------------------------------------------------------------
        # Step 5: Apply predicted patch
        # ------------------------------------------------------------------
        if not predicted_patch.strip():
            result["error"] = "empty predicted patch"
            return result

        # Normalise non-standard patch formats (bare-@@ separators, *** Begin Patch)
        predicted_patch = _normalize_patch(predicted_patch)

        patch_file = Path(tmpdir) / "predicted.patch"
        patch_file.write_text(predicted_patch)

        rc, patch_out = _run(
            ["git", "apply", "--whitespace=fix", "--recount", str(patch_file)],
            cwd=str(repo_dir),
        )
        if rc != 0:
            # Fallback 1: git apply with relaxed whitespace matching
            rc1b, patch_out1b = _run(
                ["git", "apply", "--whitespace=fix", "--recount",
                 "--ignore-whitespace", str(patch_file)],
                cwd=str(repo_dir),
            )
            if rc1b == 0:
                rc = 0
            else:
                # Fallback 2: GNU patch
                rc2, patch_out2 = _run(
                    ["patch", "-p1", "--input", str(patch_file)],
                    cwd=str(repo_dir),
                )
                if rc2 == 0:
                    rc = 0
                else:
                    # Fallback 3: fix wrong file paths by basename fuzzy-match
                    corrected = _fix_patch_paths(predicted_patch, repo_dir)
                    if corrected and corrected != predicted_patch:
                        print(
                            "  [patch] Retrying with corrected file paths …",
                            file=sys.stderr,
                        )
                        patch_file.write_text(corrected)
                        rc3, patch_out3 = _run(
                            ["git", "apply", "--whitespace=fix", "--recount",
                             str(patch_file)],
                            cwd=str(repo_dir),
                        )
                        if rc3 == 0:
                            rc = 0
                        else:
                            result["error"] = (
                                f"patch apply failed (including path-corrected retry).\n"
                                f"git apply: {patch_out[:200]}\n"
                                f"git apply --ignore-whitespace: {patch_out1b[:200]}\n"
                                f"patch -p1: {patch_out2[:200]}\n"
                                f"path-corrected git apply: {patch_out3[:200]}"
                            )
                            print(f"  [error] patch apply failed", file=sys.stderr)
                            return result
                    else:
                        result["error"] = (
                            f"patch apply failed.\n"
                            f"git apply: {patch_out[:300]}\n"
                            f"git apply --ignore-whitespace: {patch_out1b[:300]}\n"
                            f"patch -p1: {patch_out2[:300]}"
                        )
                        print(f"  [error] patch apply failed", file=sys.stderr)
                        return result

        # ------------------------------------------------------------------
        # Step 6: Run pytest AFTER patch
        # ------------------------------------------------------------------
        print(f"  pytest AFTER patch …", file=sys.stderr)
        rc, after_out = _run(
            pytest_cmd + [
                str(test_file), "-v", "--tb=short", "--no-header",
                "-p", "no:cacheprovider",
            ],
            cwd=str(repo_dir),
            timeout=120,
        )
        after_results = _parse_pytest_output(after_out)
        result["after_results"] = after_results
        print(f"    {after_results}", file=sys.stderr)

        # ------------------------------------------------------------------
        # Step 7: Compute FAIL_TO_PASS / PASS_TO_PASS
        # ------------------------------------------------------------------
        f2p = [
            t for t in test_names
            if not before_results.get(t, True) and after_results.get(t, False)
        ]
        p2p = [
            t for t in test_names
            if before_results.get(t, False) and after_results.get(t, False)
        ]

        result["FAIL_TO_PASS"] = f2p
        result["PASS_TO_PASS"] = p2p
        result["f2p_ok"] = len(f2p) > 0
        result["p2p_ok"] = all(after_results.get(t, True) for t in p2p)
        result["resolved"] = result["f2p_ok"] and result["p2p_ok"]

    return result
