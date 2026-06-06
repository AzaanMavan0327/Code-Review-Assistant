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
"""

import re
from typing import Dict, List, Optional

from github import Github, GithubException

from src.config import get_github_token
from src.github.models import ChangedFile, PullRequest


class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails for any reason."""
    pass


class GitHubClient:
    """
    Fetches and posts to GitHub pull requests.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        """
        Args:
            token: GitHub personal access token. If not provided, reads from
                   the GITHUB_TOKEN environment variable via config.py.
        """
        self._token = token or get_github_token()
        self._gh = Github(self._token)

    def get_pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        """Fetch a pull request and its changed files in one go."""
        try:
            repo_obj = self._gh.get_repo(f"{owner}/{repo}")
            pr_obj = repo_obj.get_pull(number)

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
            raise GitHubAPIError(
                f"Failed to fetch PR {owner}/{repo}#{number}: "
                f"{e.data.get('message', str(e))}"
            ) from e

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        """Fetch the full text of a file at a specific commit."""
        try:
            repo_obj = self._gh.get_repo(f"{owner}/{repo}")
            file_obj = repo_obj.get_contents(path, ref=ref)

            if isinstance(file_obj, list):
                raise GitHubAPIError(f"Expected file, got directory: {path}")

            return file_obj.decoded_content.decode("utf-8")
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to fetch {path} at {ref[:7]} in {owner}/{repo}: "
                f"{e.data.get('message', str(e))}"
            ) from e

    def post_pr_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_sha: str,
        summary: str,
        comments: List[Dict],
    ) -> None:
        """
        Post a review with inline comments to a pull request.

        Uses GitHub's "Create a review" endpoint. The `event` field is
        always "COMMENT" — we never approve or request changes from an
        automated tool, because a human should make those decisions.

        Args:
            owner, repo, pull_number: identifies the PR.
            commit_sha: SHA of the commit the comments are anchored to.
                Anchoring to a specific commit means the comments stay
                in the right place even if the PR is later updated.
            summary: Overall review body (markdown supported).
            comments: List of dicts with keys 'path', 'line', 'side', 'body'.
                'side' should usually be 'RIGHT' (referring to the new
                version of the file).

        Raises:
            GitHubAPIError: on any API failure.
        """
        try:
            repo_obj = self._gh.get_repo(f"{owner}/{repo}")
            pull = repo_obj.get_pull(pull_number)
            commit = repo_obj.get_commit(commit_sha)

            pull.create_review(
                commit=commit,
                body=summary,
                event="COMMENT",
                comments=comments,
            )
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to post review to {owner}/{repo}#{pull_number}: "
                f"{e.data.get('message', str(e))}"
            ) from e

    def _convert_file(self, gh_file) -> ChangedFile:
        """Convert PyGithub's File object to our ChangedFile model."""
        patch = gh_file.patch or ""

        return ChangedFile(
            filename=gh_file.filename,
            status=gh_file.status,
            patch=patch,
        )


# Matches PR URLs like https://github.com/owner/repo/pull/123
_PR_URL_PATTERN = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, number) from a GitHub PR URL."""
    match = _PR_URL_PATTERN.match(url.strip())
    if not match:
        raise ValueError(
            f"Not a valid GitHub PR URL: {url!r}\n"
            f"Expected format: https://github.com/OWNER/REPO/pull/NUMBER"
        )
    owner, repo, number = match.groups()
    return owner, repo, int(number)