"""
Data models for GitHub pull requests.

These are plain data containers (no behavior, no API calls) that describe
the pieces of a pull request we care about. Keeping them separate from the
code that fetches them (client.py) and the code that parses diffs
(diff_parser.py) means each module has one clear job.

This mirrors the design from Phase 1, where the `Finding` dataclass was the
shared vocabulary every analyzer module used. Here, these models are the
shared vocabulary for every GitHub module.
"""

from dataclasses import dataclass, field
from typing import List, Set


@dataclass(frozen=True)
class ChangedFile:
    """
    One file that was changed in a pull request.

    Attributes:
        filename: Path to the file within the repo (e.g. "src/utils.py").
        status: How the file changed: "added", "modified", "removed", etc.
        patch: The unified diff text for this file. May be empty for very
               large files or binary files, where GitHub omits the patch.
        changed_lines: The set of line numbers (in the NEW version of the
               file) that this PR added or modified. Populated by the diff
               parser. We only report findings on these lines, so we don't
               flag pre-existing issues the PR author didn't touch.
        contents: The full text of the file at the PR's head commit.
               Populated by the client when needed for analysis.
    """
    filename: str
    status: str
    patch: str = ""
    changed_lines: Set[int] = field(default_factory=set)
    contents: str = ""

    @property
    def is_python(self) -> bool:
        """True if this is a Python file we know how to analyze."""
        return self.filename.endswith(".py")

    @property
    def is_deleted(self) -> bool:
        """True if the file was removed in this PR (nothing to analyze)."""
        return self.status == "removed"


@dataclass(frozen=True)
class PullRequest:
    """
    A pull request and the files it changed.

    Attributes:
        owner: Repository owner (user or organization), e.g. "pallets".
        repo: Repository name, e.g. "flask".
        number: The PR number, e.g. 5432.
        title: The PR's title.
        head_sha: The commit SHA at the tip of the PR branch. Used to fetch
               file contents at exactly the version the PR proposes.
        files: The list of changed files.
    """
    owner: str
    repo: str
    number: int
    title: str
    head_sha: str
    files: List[ChangedFile] = field(default_factory=list)

    @property
    def python_files(self) -> List[ChangedFile]:
        """Only the changed Python files that still exist (not deleted)."""
        return [f for f in self.files if f.is_python and not f.is_deleted]

    @property
    def url(self) -> str:
        """Reconstruct the human-facing URL for this PR."""
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"