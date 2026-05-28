"""
GitHub API client.

Wraps the GitHub REST API (via the PyGithub library) and returns our own
data models (PullRequest, ChangedFile) rather than PyGithub's types.

Why a wrapper? Two reasons:

1. Isolation. If we ever switch from PyGithub to a different library (or
   to raw HTTP), only this file changes. The rest of the code uses our
   own models and doesn't notice.

2. Testability. Tests can mock this thin layer easily, instead of trying
   to mock PyGithub's deeply nested object graph.

This is a common professional pattern: an "adapter" between an external
library and the rest of the application.
"""

from typing import Optional

from github import Github, GithubException

from src.config import get_github_token
from src.github.models import ChangedFile, PullRequest


class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails for any reason."""
    pass


class GitHubClient:
    """
    Fetches pull request data from GitHub.

    Usage:
        client = GitHubClient()
        pr = client.get_pull_request("pallets", "flask", 5432)
        print(pr.title, len(pr.files))
    """

    def __init__(self, token: Optional[str] = None) -> None:
        """
        Args:
            token: GitHub personal access token. If not provided, reads from
                   the GITHUB_TOKEN environment variable via config.py.
                   Accepting an explicit token makes tests easier: they can
                   inject a fake one without setting environment variables.
        """
        self._token = token or get_github_token()
        self._gh = Github(self._token)

    def get_pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        """
        Fetch a pull request and its changed files in one go.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            number: The pull request number.

        Returns:
            A fully populated PullRequest with its ChangedFile list.

        Raises:
            GitHubAPIError: If the PR doesn't exist, the token is invalid,
                            or any other API failure occurs.
        """
        try:
            repo_obj = self._gh.get_repo(f"{owner}/{repo}")
            pr_obj = repo_obj.get_pull(number)

            # PyGithub returns a paginated iterator for files; calling list()
            # forces it to fetch all pages. Most PRs have well under 100 files,
            # so this is fine. For very large PRs (1000+ files) we'd want to
            # paginate manually, but that's a rare edge case.
            files = [self._convert_file(f) for f in pr_obj.get_files()]

            return PullRequest(
                owner=owner,
                repo=repo,
                number=number,
                title=pr_obj.title,
                head_sha=pr_obj.head.sha,
                files=files,
            )
        except GithubException as e:
            # Re-raise as our own exception so callers don't need to know
            # about PyGithub. The original error becomes the chained cause.
            raise GitHubAPIError(
                f"Failed to fetch PR {owner}/{repo}#{number}: {e.data.get('message', str(e))}"
            ) from e

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        """
        Fetch the full text of a file at a specific commit.

        We use the PR's head SHA as the `ref` so we get the file exactly as
        the PR proposes it, not whatever's on the main branch now.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: File path within the repo.
            ref: Commit SHA, branch name, or tag.

        Returns:
            The file contents as a string (UTF-8 decoded).

        Raises:
            GitHubAPIError: On any API failure.
        """
        try:
            repo_obj = self._gh.get_repo(f"{owner}/{repo}")
            file_obj = repo_obj.get_contents(path, ref=ref)

            # `get_contents` can return a list for directories. We're asking
            # for a specific file path, so we should never see a list, but
            # guard against it to fail loudly if assumptions are wrong.
            if isinstance(file_obj, list):
                raise GitHubAPIError(f"Expected file, got directory: {path}")

            # decoded_content returns bytes; we want text. Source files are
            # almost always UTF-8 these days.
            return file_obj.decoded_content.decode("utf-8")
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to fetch {path} at {ref[:7]} in {owner}/{repo}: "
                f"{e.data.get('message', str(e))}"
            ) from e

    def _convert_file(self, gh_file) -> ChangedFile:
        """
        Convert PyGithub's File object to our ChangedFile model.

        Keeping this conversion in one private method means the mapping logic
        lives in one place. If PyGithub ever changes its field names, only
        this method needs to change.
        """
        # PyGithub uses None for missing patches (binary files, huge diffs).
        # Our model uses empty string for consistency.
        patch = gh_file.patch or ""

        return ChangedFile(
            filename=gh_file.filename,
            status=gh_file.status,
            patch=patch,
        )


# Module-level helper, not part of the client class. This is a pure function
# that doesn't need the client's state (the token), so it shouldn't be a
# method. Keeping it module-level also makes it easy to test in isolation.

import re


# Matches PR URLs like https://github.com/owner/repo/pull/123
# The trailing /files, /commits, etc. are allowed and ignored.
_PR_URL_PATTERN = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """
    Extract (owner, repo, number) from a GitHub PR URL.

    Examples of accepted URLs:
        https://github.com/pallets/flask/pull/5432
        https://github.com/pallets/flask/pull/5432/files
        http://github.com/pallets/flask/pull/5432

    Args:
        url: A GitHub PR URL.

    Returns:
        A tuple of (owner, repo, pr_number).

    Raises:
        ValueError: If the URL doesn't match the expected pattern. The error
                    message tells the user what a valid URL looks like.
    """
    match = _PR_URL_PATTERN.match(url.strip())
    if not match:
        raise ValueError(
            f"Not a valid GitHub PR URL: {url!r}\n"
            f"Expected format: https://github.com/OWNER/REPO/pull/NUMBER"
        )
    owner, repo, number = match.groups()
    return owner, repo, int(number)