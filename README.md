# Code Review Assistant

An AI-powered code review GitHub Action for Python pull requests. It parses changed code into an abstract syntax tree (AST), runs a series of independent checks to find bugs and security issues, and uses Claude to generate clear explanations and concrete suggested fixes — grounded in the static analysis so the LLM can't hallucinate issues that aren't real. Findings are posted as inline review comments on the PR.

<!-- Add a screenshot here showing the bot's review comments on a real PR. -->

## What it detects

| Check | Severity | What it catches |
|-------|----------|-----------------|
| Cyclomatic complexity | Warning | Functions with too many branches (hard to test and maintain) |
| Mutable default arguments | Error | The classic `def f(x=[])` bug where defaults are shared across calls |
| Bare except clauses | Warning | `except:` that hides bugs and swallows `KeyboardInterrupt` |
| Unused imports | Info | Imported names that are never referenced |
| Function length | Warning | Functions longer than 50 lines |
| Hardcoded secrets | Error | API keys, passwords, and tokens committed in source code |
| Dangerous calls | Error | Use of `eval()` and `exec()`, common security holes |

Findings are scoped to lines a PR actually changes. Pre-existing issues the author didn't touch are not reported.

## Quick start: install as a GitHub Action

Add this workflow to your repo at `.github/workflows/code-review.yml`:

```yaml
name: Code Review

on:
  pull_request:
    branches: [main]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read

    steps:
      - uses: AzaanMavan0327/Code-Review-Assistant@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          # Optional: provide an Anthropic API key for LLM-generated
          # explanations and suggested fixes. Without it, plain static
          # analysis findings are posted instead.
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

If you want the LLM explanations, add your Anthropic API key as a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions → New repository secret). Generate the key at https://console.anthropic.com/settings/keys.

The action requires `permissions: pull-requests: write` so it can post review comments. The `GITHUB_TOKEN` is automatically provided by GitHub Actions; you just need to pass it through.

## Use the CLI locally

For one-off analysis or development, you can run the tool from your own terminal.

### Installation

Requires Python 3.11 or newer.

```bash
git clone https://github.com/AzaanMavan0327/Code-Review-Assistant.git
cd Code-Review-Assistant

python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate

pip install -r requirements-dev.txt
```

Create a `.env` file in the project root with your credentials. See `.env.example` for the template.

### Commands

```bash
# Analyze a local Python file
python -m src.cli analyze path/to/your_file.py

# Analyze with LLM-generated explanations
python -m src.cli analyze path/to/your_file.py --explain

# Review a real GitHub pull request
python -m src.cli review https://github.com/owner/repo/pull/123

# Review with LLM explanations
python -m src.cli review https://github.com/owner/repo/pull/123 --explain
```

### Exit codes

The tool exits with code `0` when no issues are found, `1` when issues are found, and `2` on errors (such as a file that isn't valid Python or an invalid PR URL). This makes it suitable for use in CI pipelines beyond the bundled GitHub Action.

## How it works

### Static analysis

The analyzer is built around Python's built-in `ast` module and the visitor pattern:

1. **Parse** — the source file is parsed once into an AST.
2. **Visit** — each check is an independent `ast.NodeVisitor` subclass that walks the tree looking for a specific pattern. For example, the complexity check counts branch points (`if`, `for`, `while`, `except`, boolean operators) inside each function.
3. **Report** — each visitor produces a list of `Finding` objects, which are merged and sorted by line number.

Adding a new check means writing one new visitor class and registering it in the analyzer. The rest of the system doesn't change.

### PR review pipeline

For real pull requests, the pipeline adds three more stages: fetching the PR from the GitHub API, parsing unified diffs to identify changed line numbers, and filtering findings down to only those lines. The pipeline is implemented as a pure function in `src/review.py`, separate from both the CLI and the GitHub Action runner, so the same logic powers both interfaces without modification.

### Grounded LLM enrichment

The `--explain` flag (CLI) and the `anthropic_api_key` input (Action) pipe findings through Claude to generate explanations and concrete fixes. The key design choice: **the LLM never invents findings**. The static analyzer is the source of truth — Claude only enriches what's already there. The prompt explicitly forbids adding or skipping findings, and requires a structured JSON response that's matched back to the original findings by id.

This pattern (called "grounded generation") eliminates the most common failure mode of AI-assisted tools: hallucinations. The output is reproducible, auditable, and the static analysis still works when the LLM is unavailable — failed API calls produce fallback enrichments with the analyzer's original messages.

API responses are cached on disk in `.cache/llm/`. Re-running the same review costs nothing.

### GitHub Action runtime

The Action runs as a Docker container built from the Dockerfile at the repo root. The `runner.py` entry point reads GitHub's event payload to find the PR number, runs the review pipeline, optionally enriches findings with the LLM, and posts inline review comments via the GitHub API. The Action always posts as `event: COMMENT` (never `APPROVE` or `REQUEST_CHANGES`) so it informs human reviewers without overstepping into automated approval decisions.

## Project structure

```
src/
├── analyzer/
│   ├── base.py            # Finding dataclass and Severity enum
│   ├── analyzer.py        # Orchestrates all checks
│   └── visitors/          # One file per check (7 total)
├── github/
│   ├── client.py          # Wraps the GitHub API
│   ├── diff_parser.py     # Parses unified diffs into changed-line sets
│   └── models.py          # PullRequest and ChangedFile dataclasses
├── llm/
│   ├── prompts.py         # System prompt and message templates
│   ├── reviewer.py        # LLM enrichment with grounded generation
│   └── cache.py           # Disk cache for API responses
├── action/
│   ├── runner.py          # Entry point invoked by the GitHub Action
│   └── poster.py          # Formats findings and posts as PR comments
├── config.py              # Loads env vars from .env
├── review.py              # End-to-end PR review pipeline
└── cli.py                 # Command-line interface
tests/                     # 140+ tests
Dockerfile                 # GitHub Action container
action.yml                 # GitHub Action manifest
```

## Testing

```bash
pytest
```

All tests run offline. The GitHub client, LLM reviewer, and comment poster use mocks, so no real API calls are made and no Anthropic credits are spent during testing. The suite runs in under a second.

## Roadmap

- [x] Static analyzer with 7 checks and full test coverage
- [x] GitHub API integration to analyze real pull requests
- [x] LLM-generated explanations grounded in static analysis findings
- [x] Distribution as a GitHub Action that comments on PRs automatically

## Tech stack

Python, `ast` module, Click (CLI), PyGithub, unidiff, the Anthropic API, diskcache, pytest, Docker, GitHub Actions.
