"""
Posts findings as inline review comments on a GitHub pull request.

Turns the output of the review pipeline into actual GitHub PR comments.
Each finding becomes one inline comment anchored to its specific line.
A single overall summary comment is also posted.

Design choice: the `event` is always "COMMENT", never "REQUEST_CHANGES" or
"APPROVE". An automated tool shouldn't block merges or approve work —
those decisions belong to humans. Posting as comments means our findings
inform the human reviewer without overstepping.

This module is the bridge between Phase 3's output (findings, possibly
enriched by the LLM) and Phase 4's real-world deployment as a GitHub
Action that actually shows up on PRs.
"""

from typing import List, Sequence, Union

from src.analyzer.base import Finding, Severity
from src.github.client import GitHubClient
from src.llm.reviewer import EnrichedFinding


# Emoji shown next to each severity in plain-findings mode. GitHub
# renders these inline in markdown.
_SEVERITY_EMOJI = {
    Severity.INFO: "ℹ️",
    Severity.WARNING: "⚠️",
    Severity.ERROR: "🚨",
}

# Emoji for each LLM-assigned priority in enriched-findings mode.
_PRIORITY_EMOJI = {
    "high": "🔴",
    "medium": "🟡",
    "low": "🔵",
}


# Type alias: an item to post as a comment can be either a plain Finding
# or an EnrichedFinding. The poster detects the type and formats accordingly.
PostableFinding = Union[Finding, EnrichedFinding]


def _format_plain_comment(finding: Finding) -> str:
    """Format a plain finding (no LLM enrichment) as a markdown comment."""
    emoji = _SEVERITY_EMOJI.get(finding.severity, "")
    severity_label = finding.severity.value.upper()
    return (
        f"{emoji} **{severity_label}: `{finding.rule_id}`**\n\n"
        f"{finding.message}"
    )


def _format_enriched_comment(ef: EnrichedFinding) -> str:
    """Format an LLM-enriched finding as a markdown comment."""
    f = ef.finding
    emoji = _PRIORITY_EMOJI.get(ef.priority.lower(), "")
    priority_label = ef.priority.upper()

    # Build the comment section by section. Joining with newlines gives
    # us clean, predictable output even when some sections are empty.
    parts = [
        f"{emoji} **{priority_label} priority: `{f.rule_id}`**",
        "",
        f.message,
    ]

    if ef.explanation:
        parts.extend([
            "",
            "**Why this matters:**",
            ef.explanation,
        ])

    if ef.suggested_fix:
        parts.extend([
            "",
            "**Suggested fix:**",
            ef.suggested_fix,
        ])

    return "\n".join(parts)


def _format_comment(item: PostableFinding) -> str:
    """Pick the right formatter based on the item's type."""
    if isinstance(item, EnrichedFinding):
        return _format_enriched_comment(item)
    return _format_plain_comment(item)


def _format_summary(count: int) -> str:
    """Format the overall review summary comment."""
    plural = "issue" if count == 1 else "issues"
    return (
        f"🤖 **Code Review Assistant** found {count} {plural} "
        f"on changed lines.\n\n"
        f"See the inline comments below for details. "
        f"This is an automated review — a human should still review the PR."
    )


def _get_finding(item: PostableFinding) -> Finding:
    """Extract the underlying Finding from either type."""
    return item.finding if isinstance(item, EnrichedFinding) else item


class ReviewPoster:
    """
    Posts findings as inline review comments on a pull request.

    Usage:
        poster = ReviewPoster(github_client)
        poster.post(
            owner="me", repo="my-repo", pull_number=42,
            commit_sha="abc123...",
            findings=enriched_findings,
        )
    """

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def post(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_sha: str,
        findings: Sequence[PostableFinding],
    ) -> None:
        """
        Post a review containing one inline comment per finding.

        Args:
            owner, repo, pull_number: identifies the PR.
            commit_sha: the commit at the PR's head. Comments are anchored
                here so they stay in the right place if the PR is updated.
            findings: a list of Finding or EnrichedFinding objects. Mixing
                both types in the same list works — each is formatted
                according to its type.

        If `findings` is empty, NO review is posted. This avoids spamming
        clean PRs with a "no issues found" comment every time the action
        runs. A clean PR is a clean PR.
        """
        if not findings:
            return

        comments = []
        for item in findings:
            finding = _get_finding(item)
            comments.append({
                "path": finding.file_path,
                "line": finding.line,
                # "RIGHT" means the comment is on the new version of the file.
                # ("LEFT" would put it on the pre-PR version, which doesn't
                # make sense for our use case — we're commenting on the
                # author's new code, not on code they removed.)
                "side": "RIGHT",
                "body": _format_comment(item),
            })

        self._client.post_pr_review(
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            commit_sha=commit_sha,
            summary=_format_summary(len(findings)),
            comments=comments,
        )