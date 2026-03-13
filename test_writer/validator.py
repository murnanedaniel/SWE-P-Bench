"""
Oracle test validator for SWE-P-Bench.

Validates that LLM-generated oracle tests satisfy the benchmark invariant:

    1. They FAIL on the base commit (before the gold patch is applied).
    2. They PASS after the gold patch is applied.

Also implements the retry loop: when validation fails, the error output is
fed back to the test generator and generation is retried (up to *max_attempts*
times).  The repo is cloned once per `generate_and_validate()` call, so
subsequent attempts pay only the cost of test generation + pytest run.

Usage:
    # Generate tests and validate them in one call (recommended):
    from test_writer.validator import generate_and_validate

    oracle_code, result = generate_and_validate(
        instance, n=3, max_attempts=3, model="gpt-5-mini"
    )
    if result["is_valid"]:
        print("FAIL_TO_PASS:", result["FAIL_TO_PASS"])

    # Validate already-generated tests:
    from test_writer.validator import validate_oracle_tests

    result = validate_oracle_tests(instance, oracle_code)
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from evaluator.python_harness import (
    _find_pytest_cmd,
    _fix_patch_paths,
    _install_repo,
    _parse_pytest_output,
    _run,
)
from test_writer.generator import generate_oracle_tests


# ---------------------------------------------------------------------------
# Low-level helpers shared by both validate_oracle_tests and generate_and_validate
# ---------------------------------------------------------------------------

def _clone_and_install(
    repo_dir: Path,
    instance: dict,
    repo_config: dict | None = None,
) -> tuple[bool, str]:
    """Clone *instance["repo"]* at *base_commit* into *repo_dir* and pip-install it.

    Returns ``(ok, error_message)``.
    """
    repo = instance["repo"]
    base_commit = instance.get("base_commit", "")

    print(f"  Cloning https://github.com/{repo} …", file=sys.stderr)
    rc, out = _run(
        ["git", "clone", f"https://github.com/{repo}.git", str(repo_dir)],
        timeout=300,
    )
    if rc != 0:
        return False, f"git clone failed: {out[:500]}"

    if base_commit:
        rc, out = _run(["git", "checkout", base_commit], cwd=str(repo_dir))
        if rc != 0:
            return False, f"git checkout {base_commit[:8]} failed: {out[:300]}"

    print(f"  Installing {repo} …", file=sys.stderr)
    ok, out = _install_repo(repo_dir, repo_config=repo_config)
    if not ok:
        return False, f"pip install failed: {out[-500:]}"

    return True, ""


def _apply_patch(patch_text: str, repo_dir: Path) -> tuple[bool, str]:
    """Apply *patch_text* (unified diff) to *repo_dir*.

    Tries ``git apply`` first, then falls back to ``patch -p1``.
    Returns ``(ok, error_message)``.
    """
    import tempfile as _tmpfile

    with _tmpfile.NamedTemporaryFile(suffix=".patch", mode="w", delete=False) as pf:
        pf.write(patch_text)
        pf_path = Path(pf.name)
    try:
        rc, out = _run(
            ["git", "apply", "--whitespace=fix", "--recount", str(pf_path)],
            cwd=str(repo_dir),
        )
        if rc == 0:
            return True, ""
        # Fallback 1: relaxed whitespace matching
        rc1b, out1b = _run(
            ["git", "apply", "--whitespace=fix", "--recount",
             "--ignore-whitespace", str(pf_path)],
            cwd=str(repo_dir),
        )
        if rc1b == 0:
            return True, ""
        # Fallback 2: GNU patch with progressive fuzz (5→8)
        out2 = ""
        for _fuzz in (5, 8):
            rc2, out2 = _run(
                ["patch", "-p1", f"--fuzz={_fuzz}", "--batch", "--input", str(pf_path)],
                cwd=str(repo_dir),
            )
            if rc2 == 0:
                break
            _run(["git", "reset", "--hard", "HEAD"], cwd=str(repo_dir))
            _run(["git", "clean", "-fd"], cwd=str(repo_dir))
        if rc2 == 0:
            return True, ""
        # Fallback 3: fuzzy-match wrong file paths by basename
        corrected = _fix_patch_paths(patch_text, repo_dir)
        if corrected and corrected != patch_text:
            pf_path.write_text(corrected)
            rc3, out3 = _run(
                ["git", "apply", "--whitespace=fix", "--recount", str(pf_path)],
                cwd=str(repo_dir),
            )
            if rc3 == 0:
                return True, ""
            rc3b, out3b = _run(
                ["patch", "-p1", "--fuzz=5", "--batch", "--input", str(pf_path)],
                cwd=str(repo_dir),
            )
            if rc3b == 0:
                return True, ""
            return False, (
                f"git apply: {out[:200]}\n"
                f"git apply --ignore-whitespace: {out1b[:200]}\n"
                f"patch --fuzz=5: {out2[:200]}\n"
                f"path-corrected git apply: {out3[:200]}\n"
                f"path-corrected patch --fuzz=5: {out3b[:200]}"
            )
        return False, (
            f"git apply: {out[:200]}\n"
            f"git apply --ignore-whitespace: {out1b[:200]}\n"
            f"patch --fuzz=5: {out2[:200]}"
        )
    finally:
        pf_path.unlink(missing_ok=True)


def _revert_to_head(repo_dir: Path) -> None:
    """Hard-reset the working tree to HEAD (undoes gold patch for the next attempt)."""
    _run(["git", "reset", "--hard", "HEAD"], cwd=str(repo_dir))
    _run(["git", "clean", "-fd"], cwd=str(repo_dir))


def _run_oracle_tests(
    pytest_cmd: list[str],
    test_file: Path,
    repo_dir: Path,
) -> tuple[dict[str, bool], str]:
    """Run oracle tests, return ``({name: passed}, raw_output)``."""
    _rc, out = _run(
        pytest_cmd + [
            str(test_file), "-v", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
        ],
        cwd=str(repo_dir),
        timeout=120,
    )
    return _parse_pytest_output(out), out


# ---------------------------------------------------------------------------
# Single-attempt validation (operates on an already-cloned, installed repo)
# ---------------------------------------------------------------------------

def _validate_in_dir(
    repo_dir: Path,
    instance: dict,
    oracle_code: str,
    pytest_cmd: list[str],
) -> dict:
    """Run one validation cycle inside *repo_dir*.

    Writes the oracle test file, runs pytest before and after applying the
    gold patch, then reverts the working tree to HEAD.  The caller can run
    another attempt without re-cloning.

    Returns a result dict with an ``is_valid`` flag.
    """
    test_names = re.findall(r"^def (test_\w+)", oracle_code, re.MULTILINE)
    test_file = repo_dir / "test_oracle_swepbench.py"
    test_file.write_text(oracle_code)

    result: dict = {
        "oracle_tests": test_names,
        "before_results": {},
        "after_results": {},
        "before_output": "",
        "after_output": "",
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
        "is_valid": False,
        "error": None,
    }

    # --- Run BEFORE the gold patch ---
    print("    pytest BEFORE gold patch …", file=sys.stderr)
    before, before_out = _run_oracle_tests(pytest_cmd, test_file, repo_dir)
    result["before_results"] = before
    result["before_output"] = before_out
    print(f"      {before}", file=sys.stderr)

    # --- Apply gold patch ---
    # NOTE: Do NOT run _normalize_patch on gold patches. That function is
    # designed for LLM-generated output with non-standard formats (bare @@,
    # *** Begin Patch, trailing whitespace).  Gold patches from GitHub's API
    # are already valid unified diffs; normalising them can corrupt blank
    # context lines and hunk counts, causing git-apply to reject them.
    gold_patch = instance["patch"]
    if not gold_patch.endswith("\n"):
        gold_patch += "\n"
    ok, err = _apply_patch(gold_patch, repo_dir)
    if not ok:
        result["error"] = f"gold patch apply failed: {err}"
        _revert_to_head(repo_dir)
        test_file.unlink(missing_ok=True)
        return result

    # --- Run AFTER the gold patch ---
    print("    pytest AFTER gold patch …", file=sys.stderr)
    after, after_out = _run_oracle_tests(pytest_cmd, test_file, repo_dir)
    result["after_results"] = after
    result["after_output"] = after_out
    print(f"      {after}", file=sys.stderr)

    # --- Revert so the next attempt starts clean ---
    _revert_to_head(repo_dir)
    test_file.unlink(missing_ok=True)

    # --- Compute FAIL_TO_PASS / PASS_TO_PASS ---
    f2p = [t for t in test_names if not before.get(t, True) and after.get(t, False)]
    p2p = [t for t in test_names if before.get(t, False) and after.get(t, False)]
    result["FAIL_TO_PASS"] = f2p
    result["PASS_TO_PASS"] = p2p

    # Valid = at least one test flips from fail to pass, and ALL oracle tests
    # pass after the gold patch (no regression).
    all_pass_after = all(after.get(t, False) for t in test_names) if test_names else False
    result["is_valid"] = len(f2p) > 0 and all_pass_after

    return result


def _build_retry_feedback(result: dict, attempt: int) -> str:
    """Format a feedback block to append to the generator prompt on retry."""
    before = result["before_results"]
    after = result["after_results"]
    tests = result["oracle_tests"]

    # Tests that passed before the patch (they should have FAILED — bad oracles)
    bad_before = [t for t in tests if before.get(t, False)]
    # Tests that failed after the patch (they should PASS — broken oracles)
    bad_after = [t for t in tests if not after.get(t, False)]

    lines = [
        f"## Validation Feedback (attempt {attempt})",
        "",
        "The previously generated tests did NOT satisfy the oracle requirements.",
        "",
    ]

    if result.get("error"):
        lines += [f"**Error:** {result['error']}", ""]

    if bad_before:
        lines += [
            f"**Tests that PASSED before the gold patch (must FAIL):** {bad_before}",
            "Rewrite them so they actually reproduce the bug on the unfixed code.",
            "",
        ]

    if bad_after:
        lines += [
            f"**Tests that FAILED after the gold patch (must PASS):** {bad_after}",
            "Rewrite them so the gold patch makes them pass.",
            "",
        ]

    if not tests:
        lines += ["**No test functions were found in the generated code.**", ""]

    # Append a short excerpt of pytest output for context
    for label, key in [("before", "before_output"), ("after", "after_output")]:
        raw = result.get(key, "")
        if raw:
            excerpt = raw[-1500:]  # last 1500 chars is usually the most informative
            lines += [f"**pytest output ({label} patch, truncated):**", "```", excerpt, "```", ""]

    lines += ["Please rewrite all test functions to fix the issues described above."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_oracle_tests(
    instance: dict,
    oracle_code: str,
    repo_config: dict | None = None,
) -> dict:
    """
    Validate *oracle_code* against the gold patch in *instance*.

    Clones the repo, installs it, then runs one before/after cycle.

    Returns a result dict with keys:
        is_valid, FAIL_TO_PASS, PASS_TO_PASS, oracle_tests,
        before_results, after_results, error
    """
    try:
        pytest_cmd = _find_pytest_cmd()
    except RuntimeError as exc:
        return {
            "is_valid": False, "error": str(exc),
            "oracle_tests": [], "FAIL_TO_PASS": [], "PASS_TO_PASS": [],
            "before_results": {}, "after_results": {},
        }

    with tempfile.TemporaryDirectory(prefix="swepbench_val_") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"
        ok, err = _clone_and_install(repo_dir, instance, repo_config=repo_config)
        if not ok:
            return {
                "is_valid": False, "error": err,
                "oracle_tests": [], "FAIL_TO_PASS": [], "PASS_TO_PASS": [],
                "before_results": {}, "after_results": {},
            }
        return _validate_in_dir(repo_dir, instance, oracle_code, pytest_cmd)


def generate_and_validate(
    instance: dict,
    n: int = 3,
    max_attempts: int = 3,
    model: str = "gpt-5-mini",
    repo_config: dict | None = None,
) -> tuple[str, dict]:
    """
    Generate oracle tests and validate them, retrying with error feedback.

    Clones the repo **once** and reuses the checkout across all attempts,
    so only the test-generation API call and pytest run are repeated.

    Args:
        instance:     SWE-P-Bench instance dict.
        n:            Number of test functions to request per attempt.
        max_attempts: Maximum generation+validation attempts (default: 3).
        model:        OpenAI model for test generation.
        repo_config:  Per-repo config from repos.yml (for install_extras).

    Returns:
        ``(oracle_code, result)`` where *result* has an ``is_valid`` flag and
        (when valid) populated ``FAIL_TO_PASS`` / ``PASS_TO_PASS`` lists.
        If all attempts fail, the result from the last attempt is returned
        (``is_valid=False``) so the caller can inspect the failure details.
    """
    try:
        pytest_cmd = _find_pytest_cmd()
    except RuntimeError as exc:
        return "", {
            "is_valid": False, "error": str(exc),
            "oracle_tests": [], "FAIL_TO_PASS": [], "PASS_TO_PASS": [],
            "before_results": {}, "after_results": {},
        }

    with tempfile.TemporaryDirectory(prefix="swepbench_val_") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        print(f"[validator] Cloning + installing for validation …", file=sys.stderr)
        ok, err = _clone_and_install(repo_dir, instance, repo_config=repo_config)
        if not ok:
            return "", {
                "is_valid": False, "error": err,
                "oracle_tests": [], "FAIL_TO_PASS": [], "PASS_TO_PASS": [],
                "before_results": {}, "after_results": {},
            }

        feedback: str | None = None
        last_result: dict = {}
        oracle_code = ""

        for attempt in range(1, max_attempts + 1):
            print(
                f"[validator] Attempt {attempt}/{max_attempts} — generating tests …",
                file=sys.stderr,
            )
            oracle_code, _names = generate_oracle_tests(
                instance, n=n, model=model, feedback=feedback
            )

            print(
                f"[validator] Attempt {attempt}/{max_attempts} — running validation …",
                file=sys.stderr,
            )
            result = _validate_in_dir(repo_dir, instance, oracle_code, pytest_cmd)
            last_result = result

            if result["is_valid"]:
                print(
                    f"[validator] VALID on attempt {attempt}. "
                    f"FAIL_TO_PASS={result['FAIL_TO_PASS']}",
                    file=sys.stderr,
                )
                return oracle_code, result

            print(
                f"[validator] Attempt {attempt} INVALID — "
                f"before={result['before_results']}, after={result['after_results']}",
                file=sys.stderr,
            )
            feedback = _build_retry_feedback(result, attempt)

        print(
            f"[validator] All {max_attempts} attempts failed. "
            f"Returning last result (is_valid=False).",
            file=sys.stderr,
        )
        return oracle_code, last_result
