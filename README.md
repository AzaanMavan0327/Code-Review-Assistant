# Code Review Assistant

A static analysis tool for Python that detects bugs, complexity issues, and security risks. It parses source code into an abstract syntax tree (AST) and runs a series of independent checks, reporting findings with file, line number, severity, and a clear explanation.

Built to eventually run as a GitHub Action that reviews pull requests automatically, with LLM-generated explanations grounded in the static analysis.

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

## Usage

Analyze a single Python file:

```bash
python -m src.cli analyze path/to/your_file.py
```

Example output:

```
your_file.py:11:ERROR:hardcoded-secret - Variable 'api_key' appears to contain a hardcoded secret. Load it from an environment variable instead.
your_file.py:23:WARNING:complexity - Function 'process' has cyclomatic complexity of 12 (threshold: 10). Consider breaking it into smaller functions.

Found 2 issue(s) in your_file.py.
```

The tool exits with code `0` when no issues are found, `1` when issues are found, and `2` on errors (such as a file that isn't valid Python). This makes it suitable for use in CI pipelines.

## How it works

The analyzer is built around Python's built-in `ast` module and the visitor pattern:

1. **Parse** — the source file is parsed once into an AST.
2. **Visit** — each check is an independent `ast.NodeVisitor` subclass that walks the tree looking for a specific pattern. For example, the complexity check counts branch points (`if`, `for`, `while`, `except`, boolean operators) inside each function.
3. **Report** — each visitor produces a list of `Finding` objects (file, line, severity, rule ID, message), which are merged and sorted by line number.

Adding a new check means writing one new visitor class and registering it in the analyzer. The rest of the system doesn't change, following the open/closed principle.

## Project structure

```
src/
├── analyzer/
│   ├── base.py            # Finding dataclass and Severity enum
│   ├── analyzer.py        # Orchestrates all checks
│   └── visitors/          # One file per check
├── github/                # GitHub PR integration (in progress)
├── llm/                   # LLM-generated explanations (planned)
└── cli.py                 # Command-line interface
tests/                     # Test suite (one file per check)
```

## Testing

The project has a full test suite. Run it with:

```bash
pytest
```

Each check has its own test file covering both positive cases (issues that should be flagged) and negative cases (clean code that should pass).

## Roadmap

- [x] Static analyzer with 7 checks and full test coverage
- [ ] GitHub API integration to analyze real pull requests
- [ ] LLM-generated explanations grounded in static analysis findings
- [ ] Distribution as a GitHub Action that comments on PRs automatically

## Tech stack

Python, `ast` module, Click (CLI), pytest (testing). Planned: PyGithub, the Anthropic API, and GitHub Actions.