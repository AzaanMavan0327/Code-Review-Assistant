"""
Tests for the GitHub client.

These tests use mocks instead of making real API calls. Mocking has three
benefits:

1. Tests run in milliseconds, not seconds.
2. Tests don't need network access and never hit GitHub's rate limits.
3. Tests are deterministic: a real PR could be edited or deleted, but a
   mocked response is always the same.

We use unittest.mock (from the standard library) to replace PyGithub's
classes with fake objects that return whatever data each test needs.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.github.client import GitHubClient, GitHubAPIError, parse_pr_url


# ---- parse_pr_url tests ----
# Pure function, no mocking needed.


def test_parse_pr_url_basic():
    """A standard PR URL should parse into its three parts."""
    owner, repo, number = parse_pr_url("https://github.com/pallets/flask/pull/5432")
    assert owner == "pallets"
    assert repo == "flask"
    assert number == 5432


def test_parse_pr_url_with_trailing_path():
    """URLs with /files or /commits suffixes should still parse."""
    owner, repo, number = parse_pr_url(
        "https://github.com/pallets/flask/pull/5432/files"
    )
    assert (owner, repo, number) == ("pallets", "flask", 5432)


def test_parse_pr_url_http_scheme():
    """Plain http (not just https) should be accepted."""
    owner, repo, number = parse_pr_url("http://github.com/x/y/pull/1")
    assert (owner, repo, number) == ("x", "y", 1)


def test_parse_pr_url_with_whitespace():
    """Leading/trailing whitespace should be tolerated."""
    owner, repo, number = parse_pr_url("  https://github.com/a/b/pull/9  ")
    assert (owner, repo, number) == ("a", "b", 9)


def test_parse_pr_url_invalid():
    """Non-PR URLs should raise a ValueError with a helpful message."""
    with pytest.raises(ValueError, match="valid GitHub PR URL"):
        parse_pr_url("https://example.com/not-a-pr")


def test_parse_pr_url_issue_url_rejected():
    """Issue URLs (with /issues/) should be rejected, not silently accepted."""
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/pallets/flask/issues/5432")


# ---- GitHubClient tests ----
# Use mocks so we never actually call the API.


def _make_mock_file(filename: str, status: str, patch: str = "+ added line"):
    """Helper: build a fake PyGithub File object."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.status = status
    mock_file.patch = patch
    return mock_file


@patch("src.github.client.Github")
def test_get_pull_request_returns_populated_model(mock_github_class):
    """A successful API call should produce a fully populated PullRequest."""
    # Build a fake PR object that PyGithub would return.
    mock_pr = MagicMock()
    mock_pr.title = "Fix off-by-one error"
    mock_pr.head.sha = "abc123def456"
    mock_pr.get_files.return_value = [
        _make_mock_file("src/utils.py", "modified"),
        _make_mock_file("README.md", "modified"),
    ]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr

    mock_github_instance = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_github_instance

    # Now run the client and verify it built the model correctly.
    client = GitHubClient(token="fake_token")
    pr = client.get_pull_request("pallets", "flask", 5432)

    assert pr.owner == "pallets"
    assert pr.repo == "flask"
    assert pr.number == 5432
    assert pr.title == "Fix off-by-one error"
    assert pr.head_sha == "abc123def456"
    assert len(pr.files) == 2
    assert pr.files[0].filename == "src/utils.py"
    assert pr.files[0].status == "modified"


@patch("src.github.client.Github")
def test_get_pull_request_wraps_api_errors(mock_github_class):
    """PyGithub exceptions should be re-raised as GitHubAPIError."""
    from github import GithubException

    mock_github_instance = MagicMock()
    # Simulate a 404 when the PR doesn't exist.
    mock_github_instance.get_repo.side_effect = GithubException(
        404, {"message": "Not Found"}, {}
    )
    mock_github_class.return_value = mock_github_instance

    client = GitHubClient(token="fake_token")

    with pytest.raises(GitHubAPIError, match="Not Found"):
        client.get_pull_request("nope", "nope", 999)


@patch("src.github.client.Github")
def test_get_file_content_returns_decoded_string(mock_github_class):
    """File contents should be returned as UTF-8 text, not bytes."""
    mock_file = MagicMock()
    mock_file.decoded_content = b"print('hello world')\n"

    mock_repo = MagicMock()
    mock_repo.get_contents.return_value = mock_file

    mock_github_instance = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_github_instance

    client = GitHubClient(token="fake_token")
    content = client.get_file_content("owner", "repo", "src/x.py", "abc123")

    assert content == "print('hello world')\n"


@patch("src.github.client.Github")
def test_get_file_content_rejects_directory(mock_github_class):
    """If the API returns a list (directory), we should fail loudly."""
    mock_repo = MagicMock()
    mock_repo.get_contents.return_value = [MagicMock(), MagicMock()]

    mock_github_instance = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_github_instance

    client = GitHubClient(token="fake_token")

    with pytest.raises(GitHubAPIError, match="Expected file, got directory"):
        client.get_file_content("owner", "repo", "src/", "abc123")


@patch("src.github.client.Github")
def test_missing_patch_becomes_empty_string(mock_github_class):
    """Files where PyGithub returns patch=None should yield empty string."""
    mock_file = _make_mock_file("big.bin", "added", patch=None)
    mock_pr = MagicMock()
    mock_pr.title = "Add binary asset"
    mock_pr.head.sha = "deadbeef"
    mock_pr.get_files.return_value = [mock_file]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr

    mock_github_instance = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_github_instance

    client = GitHubClient(token="fake_token")
    pr = client.get_pull_request("o", "r", 1)

    assert pr.files[0].patch == ""