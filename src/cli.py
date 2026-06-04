"""
Command-line interface for the code review assistant.

Two subcommands:

    analyze   - Run static analysis on a local Python file.
    review    - Fetch a real GitHub pull request, analyze its changed
                Python files, and report findings scoped to changed lines.

Both support an --explain flag that uses Claude to add human-readable
explanations and suggested fixes for each finding.

Run from the project root:
    python -m src.cli analyze path/to/file.py
    python -m src.cli analyze path/to/file.py --explain
    python -m src.cli review https://github.com/owner/repo/pull/123
    python -m src.cli review https://github.com/owner/repo/pull/123 --explain
"""

import sys
from pathlib import Path
from typing import Iterable, List

import click

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Finding, Severity
from src.config import ConfigError
from src.github.client import GitHubAPIError, GitHubClient, parse_pr_url
from src.llm.cache import ResponseCache
from src.llm.reviewer import EnrichedFinding, LLMReviewer
from src.review import review_pull_request


# Exit codes follow the Unix convention.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


# Severity-to-color map for plain output.
_SEVERITY_COLORS = {
    Severity.INFO: "blue",
    Severity.WARNING: "yellow",
    Severity.ERROR: "red",
}

# Priority-to-color map for enriched output. Used for the "Priority: HIGH"
# line, which is the LLM's assessment of urgency.
_PRIORITY_COLORS = {
    "high": "red",
    "medium": "yellow",
    "low": "blue",
}


def _print_findings(findings: Iterable[Finding]) -> None:
    """Print findings to the terminal with color-coded severity."""
    for finding in findings:
        color = _SEVERITY_COLORS.get(finding.severity, "white")
        prefix = f"{finding.file_path}:{finding.line}:"
        severity_text = click.style(
            finding.severity.value.upper(), fg=color, bold=True
        )
        suffix = f":{finding.rule_id} - {finding.message}"
        click.echo(prefix + severity_text + suffix)


def _print_enriched_findings(enriched: List[EnrichedFinding]) -> None:
    """
    Print enriched findings with LLM explanations and suggested fixes.

    Output format per finding:
        file:line:SEVERITY:rule
          original analyzer message

          Priority: HIGH

          Why this matters:
            <LLM explanation>

          Suggested fix:
            <LLM-generated fix>
    """
    for ef in enriched:
        f = ef.finding
        # Header line: same format as plain output for consistency.
        severity_color = _SEVERITY_COLORS.get(f.severity, "white")
        prefix = f"{f.file_path}:{f.line}:"
        severity_text = click.style(
            f.severity.value.upper(), fg=severity_color, bold=True
        )
        click.echo(prefix + severity_text + f":{f.rule_id}")
        click.echo(f"  {f.message}")
        click.echo()

        # Priority line.
        prio_color = _PRIORITY_COLORS.get(ef.priority.lower(), "white")
        priority_label = click.style(ef.priority.upper(), fg=prio_color, bold=True)
        click.echo(f"  Priority: {priority_label}")
        click.echo()

        # Explanation block.
        if ef.explanation:
            click.echo(click.style("  Why this matters:", fg="cyan", bold=True))
            for line in ef.explanation.splitlines() or [ef.explanation]:
                click.echo(f"    {line}")
            click.echo()

        # Suggested fix block (skipped when empty, e.g. in fallback mode).
        if ef.suggested_fix:
            click.echo(click.style("  Suggested fix:", fg="cyan", bold=True))
            for line in ef.suggested_fix.splitlines():
                click.echo(f"    {line}")
            click.echo()


def _build_reviewer() -> LLMReviewer:
    """
    Construct an LLMReviewer with caching enabled.

    Centralized here so both subcommands use identical configuration.
    """
    return LLMReviewer(cache=ResponseCache())


@click.group()
def cli() -> None:
    """Code review assistant - static analysis with LLM-powered explanations."""
    pass


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--explain",
    is_flag=True,
    help="Add LLM-generated explanations and suggested fixes for each finding.",
)
def analyze(file_path: str, explain: bool) -> None:
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

    # Plain output (no --explain): print findings and exit.
    if not explain:
        _print_findings(findings)
        click.echo(f"\nFound {len(findings)} issue(s) in {file_path}.")
        sys.exit(EXIT_FINDINGS)

    # --explain path: enrich findings via LLM, then print enriched output.
    try:
        reviewer = _build_reviewer()
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    # We need the source code so the LLM has context around each finding.
    source = Path(file_path).read_text(encoding="utf-8")
    source_by_file = {file_path: source}

    click.echo("Enriching findings with LLM explanations...", err=True)
    enriched = reviewer.enrich(findings, source_by_file)

    _print_enriched_findings(enriched)
    click.echo(f"\nFound {len(findings)} issue(s) in {file_path}.")
    sys.exit(EXIT_FINDINGS)


@cli.command()
@click.argument("pr_url")
@click.option(
    "--explain",
    is_flag=True,
    help="Add LLM-generated explanations and suggested fixes for each finding.",
)
def review(pr_url: str, explain: bool) -> None:
    """
    Review a real GitHub pull request.

    Fetches the PR, identifies which lines were changed, and runs the
    static analyzer on each changed Python file. Reports only findings
    on lines this PR actually added or modified.

    PR_URL is a GitHub pull request URL, like:
        https://github.com/owner/repo/pull/123
    """
    try:
        owner, repo, number = parse_pr_url(pr_url)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    try:
        client = GitHubClient()
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    try:
        result = review_pull_request(
            client, owner, repo, number,
            progress=lambda msg: click.echo(msg, err=True),
        )
    except GitHubAPIError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    click.echo()  # Blank line separator between progress and findings.

    if not result.findings:
        click.echo(
            f"No issues found on changed lines. "
            f"({result.files_analyzed} file(s) analyzed, "
            f"{result.files_skipped} skipped)"
        )
        sys.exit(EXIT_OK)

    # Plain output (no --explain): print findings and exit.
    if not explain:
        _print_findings(result.findings)
        click.echo(
            f"\nFound {len(result.findings)} issue(s) on changed lines. "
            f"({result.files_analyzed} file(s) analyzed, "
            f"{result.files_skipped} skipped)"
        )
        sys.exit(EXIT_FINDINGS)

    # --explain path: enrich and print rich output.
    try:
        reviewer = _build_reviewer()
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(EXIT_ERROR)

    click.echo("Enriching findings with LLM explanations...", err=True)
    enriched = reviewer.enrich(result.findings, result.source_by_file)

    _print_enriched_findings(enriched)
    click.echo(
        f"\nFound {len(result.findings)} issue(s) on changed lines. "
        f"({result.files_analyzed} file(s) analyzed, "
        f"{result.files_skipped} skipped)"
    )
    sys.exit(EXIT_FINDINGS)


if __name__ == "__main__":
    cli()