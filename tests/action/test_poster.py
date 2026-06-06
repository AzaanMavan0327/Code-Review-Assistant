"""
Tests for the review poster.

The poster's job is to format findings as markdown and call the client's
post_pr_review method. We mock the client so no real API calls happen,
then verify the poster sent the right shape of data.
"""

from unittest.mock import MagicMock

from src.action.poster import (
    ReviewPoster,
    _format_enriched_comment,
    _format_plain_comment,
    _format_summary,
)
from src.analyzer.base import Finding, Severity
from src.llm.reviewer import EnrichedFinding


# ---- Comment formatting tests ----
# These exercise the markdown output without involving the client at all.


def test_plain_comment_includes_severity_and_rule():
    """A plain finding's comment should mention its severity and rule."""
    f = Finding(
        file_path="src/a.py", line=10,
        severity=Severity.ERROR,
        rule_id="dangerous-call",
        message="Use of eval() is risky.",
    )

    md = _format_plain_comment(f)

    assert "ERROR" in md
    assert "dangerous-call" in md
    assert "Use of eval() is risky." in md


def test_enriched_comment_includes_priority_explanation_and_fix():
    """An enriched finding's comment should include all LLM additions."""
    f = Finding(
        file_path="src/a.py", line=10,
        severity=Severity.ERROR, rule_id="dangerous-call",
        message="Use of eval() is risky.",
    )
    ef = EnrichedFinding(
        finding=f,
        priority="high",
        explanation="If input is untrusted, attackers can run code.",
        suggested_fix="Use ast.literal_eval() instead.",
    )

    md = _format_enriched_comment(ef)

    assert "HIGH" in md
    assert "dangerous-call" in md
    assert "Use of eval() is risky." in md
    assert "Why this matters" in md
    assert "If input is untrusted" in md
    assert "Suggested fix" in md
    assert "ast.literal_eval()" in md


def test_enriched_comment_skips_empty_sections():
    """Empty explanation or suggested_fix should not produce empty sections."""
    f = Finding(
        file_path="x.py", line=1,
        severity=Severity.WARNING, rule_id="r", message="m",
    )
    ef = EnrichedFinding(
        finding=f, priority="low",
        explanation="",         # empty
        suggested_fix="",       # empty
    )

    md = _format_enriched_comment(ef)

    # Headers for empty sections should NOT appear.
    assert "Why this matters" not in md
    assert "Suggested fix" not in md
    # The priority and rule should still be there.
    assert "LOW" in md
    assert "r" in md


def test_summary_uses_correct_pluralization():
    """The summary should say 'issue' for 1 and 'issues' for everything else."""
    assert "1 issue " in _format_summary(1)
    assert "issues" in _format_summary(2)
    assert "issues" in _format_summary(10)


# ---- ReviewPoster tests ----


def _sample_finding(line: int = 1, file: str = "src/a.py") -> Finding:
    return Finding(
        file_path=file, line=line,
        severity=Severity.ERROR, rule_id="test-rule",
        message="something",
    )


def test_empty_findings_does_not_post():
    """Empty findings list should NOT trigger an API call."""
    client = MagicMock()
    poster = ReviewPoster(client)

    poster.post(
        owner="o", repo="r", pull_number=1,
        commit_sha="abc", findings=[],
    )

    client.post_pr_review.assert_not_called()


def test_post_calls_client_with_correct_arguments():
    """A successful post should pass the right data to the client."""
    client = MagicMock()
    poster = ReviewPoster(client)

    findings = [
        _sample_finding(line=5, file="src/a.py"),
        _sample_finding(line=12, file="src/b.py"),
    ]

    poster.post(
        owner="me", repo="my-repo", pull_number=42,
        commit_sha="deadbeef", findings=findings,
    )

    # Exactly one API call.
    client.post_pr_review.assert_called_once()

    # Inspect the arguments.
    kwargs = client.post_pr_review.call_args.kwargs
    assert kwargs["owner"] == "me"
    assert kwargs["repo"] == "my-repo"
    assert kwargs["pull_number"] == 42
    assert kwargs["commit_sha"] == "deadbeef"

    # Two comments, in the same order as the findings.
    assert len(kwargs["comments"]) == 2
    assert kwargs["comments"][0]["path"] == "src/a.py"
    assert kwargs["comments"][0]["line"] == 5
    assert kwargs["comments"][0]["side"] == "RIGHT"
    assert kwargs["comments"][1]["path"] == "src/b.py"
    assert kwargs["comments"][1]["line"] == 12

    # Summary should mention the count.
    assert "2 issues" in kwargs["summary"]


def test_plain_and_enriched_can_be_mixed_in_same_post():
    """The poster should handle Finding and EnrichedFinding in the same call."""
    client = MagicMock()
    poster = ReviewPoster(client)

    plain = _sample_finding(line=1)
    enriched = EnrichedFinding(
        finding=_sample_finding(line=2),
        priority="medium",
        explanation="why",
        suggested_fix="how",
    )

    poster.post(
        owner="o", repo="r", pull_number=1,
        commit_sha="abc",
        findings=[plain, enriched],
    )

    kwargs = client.post_pr_review.call_args.kwargs
    comments = kwargs["comments"]
    assert len(comments) == 2

    # First comment is plain — should NOT have "Why this matters".
    assert "Why this matters" not in comments[0]["body"]
    # Second comment is enriched — SHOULD have it.
    assert "Why this matters" in comments[1]["body"]
    assert "how" in comments[1]["body"]


def test_comment_uses_RIGHT_side():
    """Comments should be anchored to the new version of the file."""
    client = MagicMock()
    poster = ReviewPoster(client)

    poster.post(
        owner="o", repo="r", pull_number=1,
        commit_sha="abc",
        findings=[_sample_finding()],
    )

    kwargs = client.post_pr_review.call_args.kwargs
    assert all(c["side"] == "RIGHT" for c in kwargs["comments"])


def test_single_finding_uses_singular_in_summary():
    """A single finding should say 'issue', not 'issues'."""
    client = MagicMock()
    poster = ReviewPoster(client)

    poster.post(
        owner="o", repo="r", pull_number=1,
        commit_sha="abc",
        findings=[_sample_finding()],
    )

    kwargs = client.post_pr_review.call_args.kwargs
    assert "1 issue " in kwargs["summary"]
    assert "issues" not in kwargs["summary"]