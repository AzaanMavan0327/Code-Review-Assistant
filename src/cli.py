"""
Command-line interface for the code review assistant.

Two subcommands:

    analyze   - Run static analysis on a local Python file.
    review    - Fetch a real GitHub pull request, analyze its changed
                Python files, and report findings scoped to changed lines.

Run from the project root:
    python -m src.cli analyze path/to/file.py
    python -m src.cli review https://github.com/owner/repo/pull/123
"""

import sys
from typing import Iterable

import click

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Finding, Severity
from src.config import ConfigError
from src.github.client import GitHubAPIError, GitHubClient, parse_pr_url
from src.review import review_pull_request


# Exit codes follow the Unix convention:
#   0 = success, no issues
#   1 = issues found (lets CI fail the build when problems exist)
#   2 = tool error (file not found, syntax error, missing token, etc.)
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


# Severity-to-color map used by both subcommands' output.
# Centralizing this means the look stays consistent across commands.
_SEVERITY_COLORS = {
    Severity.INFO: "blue",
    Severity.WARNING: "yellow",
    Severity.ERROR: "red",
}


def _print_findings(findings: Iterable[Finding]) -> None:
    """
    Print findings to the terminal with color-coded severity.

    Shared by both subcommands so output looks identical regardless of
    where the findings came from.
    """
    for finding in findings:
        color = _SEVERITY_COLORS.get(finding.severity, "white")
        prefix = f"{finding.file_path}:{finding.line}:"
        severity_text = click.style(
            finding.severity.value.upper(), fg=color, bold=True
        )
        suffix = f":{finding.rule_id} - {finding.message}"
        click.echo(prefix + severity_text + suffix)


@click.group()
def cli() -> None:
    """Code review assistant - static analysis with LLM-powered explanations."""
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
        click.echo(f"Error: {file_path} is not valid Python: {e.msg}", err=True)
        sys.exit(EXIT_ERROR)

    if not findings:
        click.echo(f"No issues found in {file_path}.")
        sys.exit(EXIT_OK)

    _print_findings(findings)
    click.echo(f"\nFound {len(findings)} issue(s) in {file_path}.")
    sys.exit(EXIT_FINDINGS)


@cli.command()
@click.argument("pr_url")
def review(pr_url: str) -> None:
    """
    Review a real GitHub pull request.

    Fetches the PR, identifies which lines were changed, and runs the
    static analyzer on each changed Python file. Reports only findings
    on lines this PR actually added or modified.

    PR_URL is a GitHub pull request URL, like:
        https://github.com/owner/repo/pull/123
    """
    # Step 1: parse the URL.
    try:
        owner, repo, number = parse_pr_url(pr_url)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    # Step 2: initialize the GitHub client. This validates the token is
    # present and fails fast with a clear message if it's missing.
    try:
        client = GitHubClient()
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    # Step 3: run the pipeline. Progress messages get printed live so the
    # user knows the tool is working during slower network calls.
    try:
        result = review_pull_request(
            client, owner, repo, number,
            progress=lambda msg: click.echo(msg, err=True),
        )
    except GitHubAPIError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    # Step 4: report the results.
    click.echo()  # Blank line separator between progress and findings.

    if not result.findings:
        click.echo(
            f"No issues found on changed lines. "
            f"({result.files_analyzed} file(s) analyzed, "
            f"{result.files_skipped} skipped)"
        )
        sys.exit(EXIT_OK)

    _print_findings(result.findings)
    click.echo(
        f"\nFound {len(result.findings)} issue(s) on changed lines. "
        f"({result.files_analyzed} file(s) analyzed, "
        f"{result.files_skipped} skipped)"
    )
    sys.exit(EXIT_FINDINGS)


if __name__ == "__main__":
    cli()