"""
Tests for the GitHub data models.

These models are pure data containers, so the tests just confirm the
helper properties (is_python, python_files, url, etc.) behave correctly.
"""

from src.github.models import ChangedFile, PullRequest


def test_changed_file_is_python():
    """A .py file should be recognized as Python."""
    f = ChangedFile(filename="src/utils.py", status="modified")
    assert f.is_python is True


def test_changed_file_is_not_python():
    """A non-.py file should not be recognized as Python."""
    f = ChangedFile(filename="README.md", status="modified")
    assert f.is_python is False


def test_changed_file_is_deleted():
    """A removed file should be marked as deleted."""
    f = ChangedFile(filename="old.py", status="removed")
    assert f.is_deleted is True


def test_changed_file_not_deleted_when_modified():
    """A modified file should not be marked as deleted."""
    f = ChangedFile(filename="new.py", status="modified")
    assert f.is_deleted is False


def test_pull_request_python_files_filters_correctly():
    """python_files should return only non-deleted Python files."""
    pr = PullRequest(
        owner="pallets",
        repo="flask",
        number=123,
        title="Fix bug",
        head_sha="abc123",
        files=[
            ChangedFile(filename="src/app.py", status="modified"),
            ChangedFile(filename="README.md", status="modified"),
            ChangedFile(filename="src/old.py", status="removed"),
            ChangedFile(filename="src/new.py", status="added"),
        ],
    )
    python_files = pr.python_files

    # Should include app.py and new.py, but NOT README.md (not Python)
    # or old.py (deleted).
    assert len(python_files) == 2
    filenames = {f.filename for f in python_files}
    assert filenames == {"src/app.py", "src/new.py"}


def test_pull_request_url_is_reconstructed():
    """The url property should rebuild the PR's GitHub URL."""
    pr = PullRequest(
        owner="pallets",
        repo="flask",
        number=5432,
        title="Some change",
        head_sha="def456",
    )
    assert pr.url == "https://github.com/pallets/flask/pull/5432"


def test_changed_file_defaults():
    """Optional fields should have sensible defaults."""
    f = ChangedFile(filename="x.py", status="added")
    assert f.patch == ""
    assert f.changed_lines == set()
    assert f.contents == ""