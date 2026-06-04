"""
Tests for the command-line interface.

We use click's CliRunner to invoke commands as if from the shell. The
reviewer and GitHub client get mocked where needed so tests stay fast,
offline, and free (no API calls = no costs).

These tests complement the unit tests on individual modules. The unit
tests verify each component works; these verify the components are
wired together correctly through the CLI.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.analyzer.base import Finding, Severity
from src.cli import cli, EXIT_OK, EXIT_FINDINGS, EXIT_ERROR
from src.llm.reviewer import EnrichedFinding


# ---- analyze subcommand ----


def test_analyze_clean_file_exits_zero(tmp_path):
    """A file with no issues should exit 0 with a clean message."""
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("def hello():\n    return 1\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(clean_file)])

    assert result.exit_code == EXIT_OK
    assert "No issues found" in result.output


def test_analyze_file_with_issues_exits_one(tmp_path):
    """A file with issues should exit 1 and list them."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def f(items=[]):\n    return items\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(bad_file)])

    assert result.exit_code == EXIT_FINDINGS
    # The output should mention the rule that fired.
    assert "mutable-default" in result.output
    # And the summary line.
    assert "Found 1 issue" in result.output


def test_analyze_invalid_python_exits_with_error(tmp_path):
    """A file that exists but isn't valid Python should exit 2."""
    bad_file = tmp_path / "syntax_error.py"
    # Unmatched paren = SyntaxError when parsed.
    bad_file.write_text("def f(:\n    pass\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(bad_file)])

    assert result.exit_code == EXIT_ERROR
    assert "not valid Python" in result.output


def test_analyze_nonexistent_file_fails(tmp_path):
    """Click should reject a path that doesn't exist before we even run."""
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(tmp_path / "does-not-exist.py")])

    # Click's `type=click.Path(exists=True)` produces a usage error,
    # which is exit code 2 by click's convention.
    assert result.exit_code != EXIT_OK


@patch("src.cli._build_reviewer")
def test_analyze_with_explain_invokes_llm(mock_build_reviewer, tmp_path):
    """--explain should call the reviewer and render enriched output."""
    # Build a real bad file so the analyzer produces a real finding.
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def f(items=[]):\n    return items\n")

    # Mock the reviewer to return a fake enriched finding instead of
    # making a real API call. The CLI doesn't care that the finding
    # in the EnrichedFinding doesn't match what the analyzer found;
    # it just renders whatever the reviewer returns.
    fake_finding = Finding(
        file_path=str(bad_file),
        line=1,
        severity=Severity.ERROR,
        rule_id="mutable-default",
        message="Function 'f' uses a mutable default argument.",
    )
    mock_reviewer = MagicMock()
    mock_reviewer.enrich.return_value = [
        EnrichedFinding(
            finding=fake_finding,
            priority="high",
            explanation="Mutable defaults are shared across calls.",
            suggested_fix="Use None and create the list inside.",
        )
    ]
    mock_build_reviewer.return_value = mock_reviewer

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", str(bad_file), "--explain"])

    # The reviewer should have been built and called exactly once.
    mock_build_reviewer.assert_called_once()
    mock_reviewer.enrich.assert_called_once()

    # Output should include the enrichment.
    assert "Mutable defaults are shared across calls." in result.output
    assert "Use None and create the list inside." in result.output
    # Priority label rendered.
    assert "HIGH" in result.output
    # Section headers rendered.
    assert "Why this matters" in result.output
    assert "Suggested fix" in result.output


# ---- review subcommand ----


def test_review_invalid_url_exits_with_error():
    """An invalid PR URL should exit 2 with a helpful message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "not-a-real-url"])

    assert result.exit_code == EXIT_ERROR
    assert "valid GitHub PR URL" in result.output


@patch("src.cli.review_pull_request")
@patch("src.cli.GitHubClient")
def test_review_with_no_findings_exits_zero(mock_client_class, mock_review_fn):
    """A PR with no findings should exit 0 with a clean message."""
    from src.review import ReviewResult

    mock_review_fn.return_value = ReviewResult(
        pr_title="Some PR",
        files_analyzed=1,
        files_skipped=0,
        findings=[],
        source_by_file={},
    )

    runner = CliRunner()
    result = runner.invoke(cli, [
        "review", "https://github.com/o/r/pull/1",
    ])

    assert result.exit_code == EXIT_OK
    assert "No issues found" in result.output


@patch("src.cli.review_pull_request")
@patch("src.cli.GitHubClient")
def test_review_with_findings_exits_one(mock_client_class, mock_review_fn):
    """A PR with findings should exit 1 and print them."""
    from src.review import ReviewResult

    mock_review_fn.return_value = ReviewResult(
        pr_title="Has issues",
        files_analyzed=1,
        files_skipped=0,
        findings=[
            Finding(
                file_path="src/x.py", line=5,
                severity=Severity.ERROR, rule_id="dangerous-call",
                message="Use of eval()",
            )
        ],
        source_by_file={"src/x.py": "x = eval('1')\n"},
    )

    runner = CliRunner()
    result = runner.invoke(cli, [
        "review", "https://github.com/o/r/pull/1",
    ])

    assert result.exit_code == EXIT_FINDINGS
    assert "dangerous-call" in result.output
    assert "Found 1 issue" in result.output


@patch("src.cli._build_reviewer")
@patch("src.cli.review_pull_request")
@patch("src.cli.GitHubClient")
def test_review_with_explain_invokes_llm(
    mock_client_class, mock_review_fn, mock_build_reviewer
):
    """review --explain should pipe findings through the LLM reviewer."""
    from src.review import ReviewResult

    real_finding = Finding(
        file_path="src/x.py", line=5,
        severity=Severity.ERROR, rule_id="dangerous-call",
        message="Use of eval()",
    )
    mock_review_fn.return_value = ReviewResult(
        pr_title="Has issues",
        files_analyzed=1,
        files_skipped=0,
        findings=[real_finding],
        source_by_file={"src/x.py": "x = eval('1')\n"},
    )

    mock_reviewer = MagicMock()
    mock_reviewer.enrich.return_value = [
        EnrichedFinding(
            finding=real_finding,
            priority="high",
            explanation="eval is dangerous.",
            suggested_fix="Use ast.literal_eval.",
        )
    ]
    mock_build_reviewer.return_value = mock_reviewer

    runner = CliRunner()
    result = runner.invoke(cli, [
        "review", "https://github.com/o/r/pull/1", "--explain",
    ])

    assert result.exit_code == EXIT_FINDINGS
    mock_reviewer.enrich.assert_called_once()
    assert "eval is dangerous." in result.output
    assert "Use ast.literal_eval." in result.output