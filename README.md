# Code Review Assistant

A static analysis tool for Python that reviews real GitHub pull requests. It parses source code into an abstract syntax tree (AST), runs a series of independent checks, and reports findings scoped to only the lines a PR actually changed.

Built to eventually run as a GitHub Action that posts review comments on every PR automatically, with LLM-generated explanations grounded in the static analysis.

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

To use the `review` command (Phase 2), you'll also need a GitHub Personal Access Token. Create one at https://github.com/settings/tokens with `pull_requests: read` and `contents: read` permissions, then add it to a `.env` file in the project root:

```
GITHUB_TOKEN=your_token_here
```

The `.env.example` file shows the exact format.

## Usage

The tool has two subcommands.

### `analyze` — check a local file

```bash
python -m src.cli analyze path/to/your_file.py
```

Example output:

```
your_file.py:4:ERROR:hardcoded-secret - Variable 'api_key' appears to contain a hardcoded secret. Load it from an environment variable instead.
your_file.py:6:ERROR:mutable-default - Function 'bad_function' uses a mutable default argument. Defaults are shared across all calls, which causes subtle bugs.

Found 2 issue(s) in your_file.py.
```

### `review` — check a real GitHub pull request

```bash
python -m src.cli review https://github.com/owner/repo/pull/123
```

The tool fetches the PR from GitHub, parses the diff to identify which lines were added or modified, runs static analysis on each changed Python file, and reports only findings on those lines (pre-existing issues the author didn't touch are not reported).

Example output:

```
Fetching PR AzaanMavan0327/Code-Review-Assistant#1...
PR title: Create test_bad_code.py
Files changed: 1, Python files: 1
Analyzing test_bad_code.py...

test_bad_code.py:1:INFO:unused-import - Imported name 'os' is never used.
test_bad_code.py:2:INFO:unused-import - Imported name 'sys' is never used.
test_bad_code.py:4:ERROR:hardcoded-secret - Variable 'api_key' appears to contain a hardcoded secret.
test_bad_code.py:6:ERROR:mutable-default - Function 'bad_function' uses a mutable default argument.
test_bad_code.py:8:ERROR:dangerous-call - Use of 'eval()' can execute arbitrary code and is a security risk.
test_bad_code.py:9:WARNING:bare-except - Bare 'except:' clause catches all exceptions including KeyboardInterrupt.

Found 6 issue(s) on changed lines. (1 file(s) analyzed, 0 skipped)
```

### Exit codes

The tool exits with code `0` when no issues are found, `1` when issues are found, and `2` on errors (such as a file that isn't valid Python or an invalid PR URL). This makes it suitable for use in CI pipelines.

## How it works

The analyzer is built around Python's built-in `ast` module and the visitor pattern:

1. **Parse** — the source file is parsed once into an AST.
2. **Visit** — each check is an independent `ast.NodeVisitor` subclass that walks the tree looking for a specific pattern. For example, the complexity check counts branch points (`if`, `for`, `while`, `except`, boolean operators) inside each function.
3. **Report** — each visitor produces a list of `Finding` objects (file, line, severity, rule ID, message), which are merged and sorted by line number.

Adding a new check means writing one new visitor class and registering it in the analyzer. The rest of the system doesn't change, following the open/closed principle.

For the `review` command, the pipeline adds three more stages: fetching the PR from the GitHub API, parsing unified diffs to identify changed line numbers, and filtering findings down to only those lines. The pipeline is implemented as a pure function in `src/review.py`, separate from the CLI, so it can be reused unchanged by the planned GitHub Action.

## Project structure

```
src/
├── analyzer/
│   ├── base.py            # Finding dataclass and Severity enum
│   ├── analyzer.py        # Orchestrates all checks
│   └── visitors/          # One file per check (7 total)
├── github/
│   ├── client.py          # Wraps the GitHub API (PyGithub)
│   ├── diff_parser.py     # Parses unified diffs into changed-line sets
│   └── models.py          # PullRequest and ChangedFile dataclasses
├── llm/                   # LLM-generated explanations (planned)
├── config.py              # Loads env vars from .env
├── review.py              # End-to-end PR review pipeline
└── cli.py                 # Command-line interface
tests/                     # Test suite (87 tests)
```

## Testing

The project has a full test suite. Run it with:

```bash
pytest
```

All tests run offline — the GitHub client tests use `unittest.mock` so no real API calls are made. This keeps the suite fast (under a second) and deterministic.

## Roadmap

- [x] Static analyzer with 7 checks and full test coverage
- [x] GitHub API integration to analyze real pull requests
- [ ] LLM-generated explanations grounded in static analysis findings
- [ ] Distribution as a GitHub Action that comments on PRs automatically

## Tech stack

Python, `ast` module, Click (CLI), PyGithub, unidiff, pytest. Planned: the Anthropic API for LLM-generated explanations, and GitHub Actions for automated PR review.