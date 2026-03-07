# SWE-P-Bench: Physics Software Engineering Benchmark

A SWE-bench-style benchmark for high-energy physics (HEP) software projects.

## Overview

SWE-P-Bench evaluates LLMs on real GitHub issues from HEP codebases (starting with
ACTS — A Common Tracking Software). Given a repository snapshot and issue description,
a model must produce a patch that resolves the issue, validated by the project's own tests.

## Structure

```
SWE-P-Bench/
├── scraper/          # GitHub issue/PR collection pipeline
│   └── acts.py       # ACTS-specific scraper
├── solver/           # LLM solvers
│   └── gpt4o_mini.py # OpenAI GPT-4o-mini baseline solver
├── evaluator/        # Patch application and test execution
│   └── harness.py    # Docker-based evaluation harness
├── metrics/          # Scoring and reporting
│   └── score.py      # Compute and display benchmark results
├── data/             # Scraped and filtered dataset instances
│   └── acts/
├── results/          # Solver outputs and evaluation results
└── requirements.txt
```

## Quick Start

```bash
pip install -r requirements.txt

# 1. Scrape ACTS issues → data/acts/candidates.jsonl
python -m scraper.acts --repo acts-project/acts --out data/acts/candidates.jsonl

# 2. Run the GPT-4o-mini solver → results/gpt4o_mini/
python -m solver.gpt4o_mini --dataset data/acts/candidates.jsonl --out results/gpt4o_mini/

# 3. Evaluate patches → results/gpt4o_mini/eval.jsonl
python -m evaluator.harness --results results/gpt4o_mini/ --dataset data/acts/candidates.jsonl

# 4. Print metrics
python -m metrics.score --eval results/gpt4o_mini/eval.jsonl
```

## Environment Variables

```
GITHUB_TOKEN   GitHub personal access token (required for scraper)
OPENAI_API_KEY OpenAI API key (required for solver)
```

## Dataset Schema

Each instance in `data/acts/candidates.jsonl` follows the SWE-bench schema:

```json
{
  "instance_id": "acts-project__acts-NNNN",
  "repo": "acts-project/acts",
  "base_commit": "<sha>",
  "problem_statement": "<issue title + body>",
  "hints_text": "<issue comments before first PR commit>",
  "patch": "<gold fix diff>",
  "test_patch": "<test-file changes from PR>",
  "FAIL_TO_PASS": ["TestSuite::test_foo"],
  "PASS_TO_PASS": ["TestSuite::test_bar"],
  "created_at": "2024-01-01T00:00:00Z",
  "pr_number": 1234,
  "issue_number": 1200
}
```
