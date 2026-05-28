"""
Command-line interface for the code review assistant.

Run from the project root:
    python -m src.cli analyze path/to/file.py
    python -m src.cli review https://github.com/owner/repo/pull/123  (Phase 2+)
"""

import sys
from pathlib import Path

import click

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


# Exit codes follow the Unix convention:
#   0 = success, no issues
#   1 = issues found (lets CI fail the build when problems exist)
#   2 = tool error (file not found, syntax error, etc.)
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


@click.group()
def cli() -> None:
    """Code review assistant - static analysis with LLM-powered explanations."""
    # Click uses this docstring as the --help text. The function body is empty
    # because this is just the parent group; real work happens in subcommands.
    pass


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
def analyze(file_path: str) -> None:
    """
    Analyze a single Python file and print findings to the terminal.

    FILE_PATH is the path to a .py file you want to check.
    """
    analyzer = CodeAnalyzer()

    try:
        findings = analyzer.analyze_file(file_path)
    except SyntaxError as e:
        # Show the user a clear error instead of a Python stack trace.
        click.echo(f"Error: {file_path} is not valid Python: {e.msg}", err=True)
        sys.exit(EXIT_ERROR)

    if not findings:
        click.echo(f"No issues found in {file_path}.")
        sys.exit(EXIT_OK)

    # Color-code output by severity so issues are easy to scan visually.
    # Click's `style` function adds ANSI color codes that work in most terminals.
    severity_colors = {
        Severity.INFO: "blue",
        Severity.WARNING: "yellow",
        Severity.ERROR: "red",
    }

    for finding in findings:
        color = severity_colors.get(finding.severity, "white")
        # Build the output line with the severity portion colored.
        prefix = f"{finding.file_path}:{finding.line}:"
        severity_text = click.style(finding.severity.value.upper(), fg=color, bold=True)
        suffix = f":{finding.rule_id} - {finding.message}"
        click.echo(prefix + severity_text + suffix)

    # Print a summary at the bottom so users see the total at a glance.
    click.echo(f"\nFound {len(findings)} issue(s) in {file_path}.")
    sys.exit(EXIT_FINDINGS)


if __name__ == "__main__":
    cli()