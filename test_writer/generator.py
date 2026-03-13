"""
Oracle test generator for SWE-P-Bench.

Given a benchmark instance (issue + gold patch), generates minimal pytest
test functions that serve as validation oracles:
  - FAIL on the base commit (before the fix)
  - PASS after the gold patch is applied

Uses GPT-5-mini to synthesise the tests from the issue description and diff.

Usage:
    from test_writer.generator import generate_oracle_tests
    test_code, test_names = generate_oracle_tests(instance, n=3)

Environment:
    OPENAI_API_KEY  OpenAI API key
"""

from __future__ import annotations

import os
import re
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "gpt-5.4"

SYSTEM_PROMPT = """\
You are an expert Python software engineer and test writer specialising in \
high-energy physics (HEP) libraries.

Given a GitHub issue and the gold diff that fixes it, you must write minimal \
pytest test functions that serve as "oracle tests" for an automated benchmark.

Requirements for EVERY test function:
1. It MUST FAIL when run against the BUGGY code (before the patch).
2. It MUST PASS when run against the FIXED code (after the patch).
3. It MUST be self-contained — import the library at the top of the file, \
   create all data inline, no external fixtures, no network calls, no file I/O.
4. It MUST be deterministic.
5. Keep each test minimal — test EXACTLY the behaviour the patch fixes, nothing else.

Output ONLY a valid Python module. Do NOT include explanations, prose, or \
markdown code fences. Start directly with `import` statements.

Name each test function test_oracle_NNN (e.g., test_oracle_001, test_oracle_002).

IMPORTANT: Generate tests for ONLY the behaviour the issue explicitly describes.
If the diff contains changes not mentioned in the issue (e.g. an attribute rename, \
a refactor, or an unrelated bug fix bundled alongside the main change), do NOT \
write tests for those extra changes. Focus exclusively on what the reporter \
asked for.
"""

USER_TEMPLATE = """\
## Repository
{repo}

## Issue
{problem_statement}

{hints_section}

## Gold Patch (the fix that resolves this issue)

```diff
{patch}
```

## Task
Write {n} pytest test function(s) following the system instructions.
Output only the raw Python module code (imports + test functions).
"""


def _build_generation_prompt(instance: dict, n: int) -> str:
    hints = instance.get("hints_text", "").strip()
    hints_section = f"## Discussion / Hints\n\n{hints}" if hints else ""
    return USER_TEMPLATE.format(
        repo=instance.get("repo", "unknown/repo"),
        problem_statement=instance.get("problem_statement", ""),
        hints_section=hints_section,
        patch=instance.get("patch", ""),
        n=n,
    ).strip()


def _clean_code_block(response: str) -> str:
    """Strip markdown code fences if the model wrapped the output."""
    m = re.search(r"```(?:python)?\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return response.strip()


def _extract_test_names(code: str) -> list[str]:
    """Extract all `def test_*` function names from generated code."""
    return re.findall(r"^def (test_\w+)", code, re.MULTILINE)


def generate_oracle_tests(
    instance: dict,
    n: int = 3,
    model: str = MODEL,
    feedback: str | None = None,
) -> tuple[str, list[str]]:
    """
    Generate N oracle test functions for the given benchmark instance.

    Args:
        instance: SWE-P-Bench instance dict. Required keys:
                  repo, problem_statement, patch.
                  Optional: hints_text.
        n:        Number of test functions to generate.
        model:    OpenAI model name.
        feedback: Optional error feedback from a previous failed validation
                  attempt. When provided it is appended to the user prompt so
                  the model can correct its mistakes.

    Returns:
        (test_code, test_names) — test_code is a valid Python module string;
        test_names is the list of function names found in it.
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    prompt = _build_generation_prompt(instance, n)
    if feedback:
        prompt = prompt + "\n\n" + feedback

    print(f"  Calling {model} to generate {n} oracle tests…", file=sys.stderr)
    # Reasoning models (gpt-5-mini, o*) do not accept temperature.
    # Frontier models (gpt-5.4, gpt-4o, etc.) benefit from a low temperature.
    _is_reasoning = model.endswith("-mini") or model.startswith("o")
    api_kwargs: dict = {"max_completion_tokens": 8000}
    if not _is_reasoning:
        api_kwargs["temperature"] = 0.2

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        **api_kwargs,
    )

    raw = response.choices[0].message.content or ""
    code = _clean_code_block(raw)
    test_names = _extract_test_names(code)

    if not test_names:
        print(
            "  [warning] No test_* functions found in generated code.",
            file=sys.stderr,
        )

    return code, test_names
