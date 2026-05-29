"""
Tests for the review pipeline.

These tests use a mock GitHubClient so we don't hit the real API. The
pipeline glues together components we've already tested in isolation
(analyzer, diff parser, client), so these tests focus on the glue:
filtering to changed lines, skipping files that can't be analyzed,
and producing the right ReviewResult metadata.
"""

from unittest.mock import MagicMock

from src.github.client import GitHubAPIError
from src.github.models import ChangedFile, PullRequest
from src.review import review_pull_request


def _make_mock_client(pr: PullRequest, file_contents: dict) -> MagicMock:
    """Build a mock GitHubClient that returns the given PR and file contents."""
    client = MagicMock()
    client.get_pull_request.return_value = pr
    client.get_file_content.side_effect = lambda owner, repo, path, ref: (
        file_contents.get(path, "")
    )
    return client


def test_no_python_files_returns_empty_result():
    """A PR with no Python files should return zero findings, zero analyzed."""
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Docs only", head_sha="abc",
        files=[ChangedFile(filename="README.md", status="modified", patch="...")],
    )
    client = _make_mock_client(pr, {})

    result = review_pull_request(client, "o", "r", 1)

    assert result.findings == []
    assert result.files_analyzed == 0
    assert result.pr_title == "Docs only"


def test_findings_outside_changed_lines_are_filtered():
    """Pre-existing issues the PR didn't touch should NOT be reported."""
    # The PR adds one line that uses eval(). The file also has an OLDER
    # eval() that wasn't touched. Only the new one should appear.
    file_contents = {
        "src/a.py": (
            "x = eval('old')\n"     # line 1 - PRE-EXISTING, should NOT be flagged
            "y = 2\n"               # line 2
            "z = eval('new')\n"     # line 3 - CHANGED, should be flagged
        )
    }
    # Patch claims line 3 is the only added line.
    patch = "\n".join([
        "@@ -1,2 +1,3 @@",
        " x = eval('old')",
        " y = 2",
        "+z = eval('new')",
        "",
    ])
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Add eval", head_sha="abc",
        files=[ChangedFile(filename="src/a.py", status="modified", patch=patch)],
    )
    client = _make_mock_client(pr, file_contents)

    result = review_pull_request(client, "o", "r", 1)

    # Should find exactly one finding (the new eval), not the old one.
    eval_findings = [f for f in result.findings if f.rule_id == "dangerous-call"]
    assert len(eval_findings) == 1
    assert eval_findings[0].line == 3


def test_findings_on_changed_lines_are_kept():
    """Issues on lines the PR added should be reported."""
    file_contents = {
        "src/a.py": (
            "import os\n"           # line 1 - unchanged
            "api_key = 'sk-abc1234567890'\n"  # line 2 - changed, should flag
        )
    }
    patch = "\n".join([
        "@@ -1,1 +1,2 @@",
        " import os",
        "+api_key = 'sk-abc1234567890'",
        "",
    ])
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Add secret", head_sha="abc",
        files=[ChangedFile(filename="src/a.py", status="modified", patch=patch)],
    )
    client = _make_mock_client(pr, file_contents)

    result = review_pull_request(client, "o", "r", 1)

    secrets = [f for f in result.findings if f.rule_id == "hardcoded-secret"]
    assert len(secrets) == 1
    assert secrets[0].line == 2
    assert result.files_analyzed == 1


def test_non_python_files_are_ignored():
    """Markdown, JSON, and other non-Python files should never be analyzed."""
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Mixed PR", head_sha="abc",
        files=[
            ChangedFile(
                filename="README.md", status="modified",
                patch="@@ -1,1 +1,1 @@\n-old\n+new\n",
            ),
            ChangedFile(
                filename="config.json", status="modified",
                patch="@@ -1,1 +1,1 @@\n-{}\n+{\"k\": 1}\n",
            ),
        ],
    )
    client = _make_mock_client(pr, {})

    result = review_pull_request(client, "o", "r", 1)

    # No Python files means no API calls to fetch contents.
    client.get_file_content.assert_not_called()
    assert result.files_analyzed == 0


def test_file_fetch_failure_skips_file():
    """If one file can't be fetched, others should still be analyzed."""
    patch = "@@ -0,0 +1,1 @@\n+x = 1\n"
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Two files", head_sha="abc",
        files=[
            ChangedFile(filename="src/good.py", status="added", patch=patch),
            ChangedFile(filename="src/bad.py", status="added", patch=patch),
        ],
    )

    client = MagicMock()
    client.get_pull_request.return_value = pr

    # First call works, second fails.
    def fetch(owner, repo, path, ref):
        if path == "src/good.py":
            return "x = 1\n"
        raise GitHubAPIError("Access denied")

    client.get_file_content.side_effect = fetch

    result = review_pull_request(client, "o", "r", 1)

    # One file analyzed successfully, one skipped due to fetch error.
    assert result.files_analyzed == 1
    assert result.files_skipped == 1


def test_invalid_python_file_is_skipped():
    """Files that aren't valid Python should be skipped, not crash."""
    patch = "@@ -0,0 +1,1 @@\n+not valid python!@#$\n"
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Broken", head_sha="abc",
        files=[
            ChangedFile(filename="src/broken.py", status="added", patch=patch),
        ],
    )
    client = _make_mock_client(pr, {"src/broken.py": "not valid python!@#$"})

    result = review_pull_request(client, "o", "r", 1)

    # Did not crash, did not produce findings, counted as skipped.
    assert result.findings == []
    assert result.files_analyzed == 0
    assert result.files_skipped == 1


def test_progress_callback_is_called():
    """The progress callback should fire with status messages."""
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Test", head_sha="abc",
        files=[],
    )
    client = _make_mock_client(pr, {})

    messages = []
    review_pull_request(client, "o", "r", 1, progress=messages.append)

    # At minimum: a "fetching" message and a "title" message.
    assert any("Fetching" in m for m in messages)
    assert any("Test" in m for m in messages)


def test_no_progress_callback_is_silent():
    """Passing None for progress should run silently without crashing."""
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Test", head_sha="abc",
        files=[],
    )
    client = _make_mock_client(pr, {})

    # Should not raise. Result is what we care about; output is suppressed.
    result = review_pull_request(client, "o", "r", 1, progress=None)
    assert result.findings == []


def test_findings_are_sorted_by_file_and_line():
    """Output should be sorted by file path then line number."""
    contents = {
        "src/b.py": "import os\n" + ("api_key = 'sk-aaaaaaaaaa'\n"),
        "src/a.py": "import os\n" + ("api_key = 'sk-bbbbbbbbbb'\n"),
    }
    patch = "\n".join([
        "@@ -1,1 +1,2 @@",
        " import os",
        "+api_key = 'sk-secret-here'",
        "",
    ])
    pr = PullRequest(
        owner="o", repo="r", number=1, title="Multi-file", head_sha="abc",
        files=[
            # Note: b.py listed FIRST to ensure sorting works regardless of input order.
            ChangedFile(filename="src/b.py", status="modified", patch=patch),
            ChangedFile(filename="src/a.py", status="modified", patch=patch),
        ],
    )
    client = _make_mock_client(pr, contents)

    result = review_pull_request(client, "o", "r", 1)

    # a.py should come before b.py alphabetically.
    assert len(result.findings) >= 2
    file_paths_in_order = [f.file_path for f in result.findings]
    assert file_paths_in_order == sorted(file_paths_in_order)