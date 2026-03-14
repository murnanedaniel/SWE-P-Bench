"""
Claude CLI backend for SWE-P-Bench.

Drop-in replacement for OpenAI SDK calls that uses ``claude -p`` (print mode)
from a Claude Code subscription.  No API key needed — uses your subscription
authentication.

Usage::

    from llm.claude_cli import claude_chat

    text = claude_chat(
        system_prompt="You are an expert Python engineer.",
        user_prompt="Write a test for ...",
        model="sonnet",           # sonnet | opus | haiku
    )

The function shells out to the ``claude`` CLI in non-interactive print mode
(``-p``), parses the JSON response, and returns the result text.

Concurrency note: Claude Code subscription has per-user concurrency limits.
Callers should run sequentially (workers=1) or use a small pool (2–3).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_claude_binary() -> str:
    """Locate the claude CLI binary, raising if not found."""
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(
            "claude CLI not found on PATH. "
            "Install it from https://claude.ai/code or ensure it is on your PATH."
        )
    return path


def claude_chat(
    system_prompt: str,
    user_prompt: str,
    model: str = "sonnet",
    timeout: int = 300,
) -> str:
    """
    Call Claude via the CLI in print mode and return the response text.

    Args:
        system_prompt: System instructions for the model.
        user_prompt:   The user-turn content.
        model:         Model alias — "sonnet", "opus", or "haiku".
        timeout:       Subprocess timeout in seconds (default 5 min).

    Returns:
        The model's text response.

    Raises:
        RuntimeError:  If the CLI returns an error or non-zero exit code.
        TimeoutError:  If the call exceeds *timeout* seconds.
    """
    claude_bin = _find_claude_binary()

    # Write the user prompt to a temp file to avoid shell quoting issues
    # with large prompts containing special characters.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as tmp:
        tmp.write(user_prompt)
        prompt_file = tmp.name

    try:
        cmd = [
            claude_bin,
            "-p",                           # print mode (non-interactive)
            "--output-format", "json",      # structured output
            "--model", model,               # sonnet / opus / haiku
            "--no-session-persistence",     # don't clutter session history
            "--tools", "",                  # disable tool use — text only
            "--system-prompt", system_prompt,
        ]

        # Strip ANTHROPIC_API_KEY from the subprocess environment so the CLI
        # uses subscription auth instead of the paid API.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        result = subprocess.run(
            cmd,
            input=user_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    finally:
        Path(prompt_file).unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"claude CLI exited with code {result.returncode}: {stderr}"
        )

    # Parse JSON response — the "result" field contains the model's text.
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError("claude CLI returned empty output")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse claude CLI JSON output: {exc}\n"
            f"Raw output (first 500 chars): {stdout[:500]}"
        )

    if data.get("is_error"):
        raise RuntimeError(
            f"claude CLI reported error: {data.get('result', 'unknown')}"
        )

    return data.get("result", "")
