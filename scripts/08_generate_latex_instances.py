"""
scripts/08_generate_latex_instances.py — Generate LaTeX showcase for benchmark instances.

Reads the assembled benchmark JSONL and Claude solver results, randomly
selects N instances, and formats each as a LaTeX subsection with issue
excerpt, patch stats, oracle test code, and solver result.

Usage:
    python scripts/08_generate_latex_instances.py \
        --benchmark data/benchmark_v1.jsonl \
        [--solver-dir results/claude_sonnet_1shot] \
        [--results-dir results/] \
        [--n 10] [--seed 42] \
        [--out paper/instances.tex]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _patch_stats(patch: str) -> dict:
    """Extract stats from a unified diff."""
    files = re.findall(r"^diff --git a/(\S+)", patch, re.MULTILINE)
    added = len(re.findall(r"^\+(?!\+\+)", patch, re.MULTILINE))
    removed = len(re.findall(r"^-(?!--)", patch, re.MULTILINE))
    return {"files": files, "n_files": len(files), "added": added, "removed": removed}


def _truncate(text: str, max_lines: int = 30) -> str:
    """Truncate text to max_lines, adding ellipsis if needed."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + "\n... (truncated)"


def _issue_excerpt(problem_statement: str, max_chars: int = 500) -> str:
    """Extract a short excerpt from the issue."""
    text = problem_statement.strip()
    if len(text) <= max_chars:
        return text
    # Try to cut at a sentence boundary
    cut = text[:max_chars].rfind(". ")
    if cut > max_chars // 2:
        return text[: cut + 1]
    return text[:max_chars] + "..."


def format_instance(
    rec: dict, idx: int, solver_patch: str | None, solver_resolved: bool | None
) -> str:
    """Format one instance as a LaTeX subsection."""
    iid = rec["instance_id"]
    repo = rec.get("repo", "unknown")
    issue = rec.get("problem_statement", "")
    patch = rec.get("patch", "")
    oracle_code = rec.get("oracle_test_code", "")

    stats = _patch_stats(patch)
    issue_text = _issue_excerpt(issue)
    oracle_truncated = _truncate(oracle_code, 40)

    lines = []
    lines.append(f"\\subsection{{Instance {idx}: {_escape_latex(iid)}}}")
    lines.append(f"\\textbf{{Repository:}} \\texttt{{{_escape_latex(repo)}}}")
    lines.append("")

    # Issue excerpt
    lines.append("\\subsubsection*{Issue}")
    lines.append("\\begin{quote}")
    lines.append(_escape_latex(issue_text))
    lines.append("\\end{quote}")
    lines.append("")

    # Patch stats
    lines.append("\\subsubsection*{Gold Patch}")
    files_str = ", ".join(f"\\texttt{{{_escape_latex(f)}}}" for f in stats["files"][:5])
    if stats["n_files"] > 5:
        files_str += f" (+{stats['n_files'] - 5} more)"
    lines.append(
        f"{stats['n_files']} file(s) changed: {files_str}. "
        f"+{stats['added']}/$-${stats['removed']} lines."
    )
    lines.append("")

    # Oracle tests
    lines.append("\\subsubsection*{Oracle Tests}")
    lines.append("\\begin{lstlisting}[language=Python, basicstyle=\\tiny\\ttfamily]")
    lines.append(oracle_truncated)
    lines.append("\\end{lstlisting}")
    lines.append("")

    # Solver result
    lines.append("\\subsubsection*{Claude Sonnet Result}")
    if solver_resolved is None:
        lines.append("No solver attempt available.")
    elif solver_resolved:
        lines.append("\\textbf{Resolved} \\checkmark")
        if solver_patch:
            solver_stats = _patch_stats(solver_patch)
            lines.append(
                f" --- {solver_stats['n_files']} file(s), "
                f"+{solver_stats['added']}/$-${solver_stats['removed']} lines."
            )
    else:
        lines.append("\\textbf{Not resolved} \\texttimes")
        if solver_patch:
            solver_stats = _patch_stats(solver_patch)
            lines.append(
                f" --- attempted {solver_stats['n_files']} file(s), "
                f"+{solver_stats['added']}/$-${solver_stats['removed']} lines."
            )

    lines.append("")
    lines.append("\\vspace{1em}\\hrule\\vspace{1em}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate LaTeX showcase for SWE-P-Bench instances"
    )
    parser.add_argument("--benchmark", required=True, help="Path to benchmark_v1.jsonl")
    parser.add_argument(
        "--solver-dir",
        default="results/claude_sonnet_1shot",
        help="Solver results directory",
    )
    parser.add_argument("--results-dir", default="results", help="Root results dir")
    parser.add_argument("--n", type=int, default=10, help="Number of instances to showcase")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--out", default="paper/instances.tex", help="Output .tex file")
    args = parser.parse_args()

    instances = load_jsonl(args.benchmark)
    if not instances:
        print("No instances found.", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    selected = rng.sample(instances, min(args.n, len(instances)))

    results_dir = Path(args.results_dir)
    solver_dir = Path(args.solver_dir)

    sections = []
    for i, rec in enumerate(selected, 1):
        iid = rec["instance_id"]
        repo = rec.get("repo", "unknown/unknown")
        owner, name = (repo.split("/", 1) + ["unknown"])[:2]

        # Load solver patch if available
        solver_patch = None
        solver_resolved = None
        patch_path = solver_dir / owner / name / f"{iid}.patch"
        if patch_path.exists():
            solver_patch = patch_path.read_text()

        eval_path = (
            results_dir / "claude_sonnet_1shot" / "evals" / owner / name / f"{iid}.json"
        )
        if eval_path.exists():
            eval_data = json.loads(eval_path.read_text())
            solver_resolved = eval_data.get("resolved", False)

        sections.append(format_instance(rec, i, solver_patch, solver_resolved))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "% Auto-generated by scripts/08_generate_latex_instances.py\n"
        f"% {len(selected)} instances selected with seed={args.seed}\n\n"
        "\\section{Instance Showcase}\n\n"
    )

    with open(out_path, "w") as f:
        f.write(header)
        f.write("\n".join(sections))

    print(f"Wrote {len(selected)} instance sections to {out_path}")


if __name__ == "__main__":
    main()
