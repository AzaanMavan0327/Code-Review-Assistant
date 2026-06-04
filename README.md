# Code Review Assistant

An AI-powered static analysis tool for Python that reviews real GitHub pull requests. It parses source code into an abstract syntax tree (AST), runs a series of independent checks to find bugs and security issues, and uses Claude to generate clear explanations and concrete suggested fixes for each finding — grounded in the static analysis so the LLM can't hallucinate issues that aren't real.

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

## Installation

Requires Python 3.11 or newer.

```bash
# Clone the repository
git clone https://github.com/AzaanMavan0327/Code-Review-Assistant.git
cd Code-Review-Assistant

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt
```

The tool reads credentials from a `.env` file in the project root:

```
GITHUB_TOKEN=github_pat_your_token_here          # for `review` subcommand
ANTHROPIC_API_KEY=sk-ant-your_key_here           # for --explain
```

- Generate a GitHub token at https://github.com/settings/tokens (fine-grained, with `pull_requests: read` and `contents: read`).
- Generate an Anthropic key at https://console.anthropic.com/settings/keys (requires credits added in Billing).

See `.env.example` for the template.

## Usage

The tool has two subcommands and an optional `--explain` flag on each.

### `analyze` — check a local file

```bash
python -m src.cli analyze path/to/your_file.py
python -m src.cli analyze path/to/your_file.py --explain
```

Without `--explain`, it prints a one-line summary per finding. With `--explain`, each finding gets a priority, an explanation, and a concrete suggested fix from Claude.

### `review` — check a real GitHub pull request

```bash
python -m src.cli review https://github.com/owner/repo/pull/123
python -m src.cli review https://github.com/owner/repo/pull/123 --explain
```

The tool fetches the PR from GitHub, parses the diff to identify which lines were added or modified, runs static analysis on each changed Python file, and reports only findings on those lines (pre-existing issues the author didn't touch are not reported).

### Example output (with `--explain`)

```
test_bad_code.py:4:ERROR:hardcoded-secret
  Variable 'api_key' appears to contain a hardcoded secret.

  Priority: HIGH

  Why this matters:
    Anyone with read access to this repo can see and use this key.
    For public repos, that's literally everyone on the internet, and
    secret-scanning bots actively look for strings like this.

  Suggested fix:
    import os
    api_key = os.environ["API_KEY"]

test_bad_code.py:8:ERROR:dangerous-call
  Use of 'eval()' can execute arbitrary code and is a security risk.

  Priority: HIGH

  Why this matters:
    If 'code_string' ever comes from user input, an attacker can run
    any code they want with this program's permissions.

  Suggested fix:
    import ast
    result = ast.literal_eval(code_string)  # only parses literals
```

### Exit codes

The tool exits with code `0` when no issues are found, `1` when issues are found, and `2` on errors (such as a file that isn't valid Python or an invalid PR URL). This makes it suitable for use in CI pipelines.

## How it works

### The static analyzer

The analyzer is built around Python's built-in `ast` module and the visitor pattern:

1. **Parse** — the source file is parsed once into an AST.
2. **Visit** — each check is an independent `ast.NodeVisitor` subclass that walks the tree looking for a specific pattern. For example, the complexity check counts branch points (`if`, `for`, `while`, `except`, boolean operators) inside each function.
3. **Report** — each visitor produces a list of `Finding` objects, which are merged and sorted by line number.

Adding a new check means writing one new visitor class and registering it in the analyzer. The rest of the system doesn't change.

### The PR review pipeline

For the `review` command, the pipeline adds three more stages: fetching the PR from the GitHub API, parsing unified diffs to identify changed line numbers, and filtering findings down to only those lines. The pipeline is implemented as a pure function in `src/review.py`, separate from the CLI, so it can be reused unchanged by the planned GitHub Action.

### Grounded LLM enrichment

The `--explain` flag pipes findings through Claude to generate human-readable explanations and concrete fixes. The key design choice: **the LLM never invents findings**. The static analyzer is the source of truth — Claude only enriches what's already there. The prompt explicitly forbids adding or skipping findings, and requires a structured JSON response that's matched back to the original findings by id.

This pattern (called "grounded generation") eliminates the most common failure mode of AI-assisted tools: hallucinations. The output is reproducible, auditable, and the static analysis still works when the LLM is unavailable — failed API calls produce fallback enrichments with the analyzer's original messages.

Responses are cached on disk in `.cache/llm/`. Re-running the same review costs nothing.

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
├── config.py              # Loads env vars from .env
├── review.py              # End-to-end PR review pipeline
└── cli.py                 # Command-line interface
tests/                     # Test suite (110+ tests)
```

## Testing

```bash
pytest
```

All tests run offline. The GitHub client and LLM reviewer use mocks, so no real API calls are made and no Anthropic credits are spent. This keeps the suite fast (under a second) and deterministic.

## Roadmap

- [x] Static analyzer with 7 checks and full test coverage
- [x] GitHub API integration to analyze real pull requests
- [x] LLM-generated explanations grounded in static analysis findings
- [ ] Distribution as a GitHub Action that comments on PRs automatically

## Tech stack

Python, `ast` module, Click (CLI), PyGithub, unidiff, the Anthropic API, diskcache, pytest. Planned: GitHub Actions for automated PR review.