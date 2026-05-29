"""
Tests for the diff parser.

These tests use synthetic patches (small strings) and one realistic inline
sample. No network calls; no PyGithub needed.

We inline the multi-hunk sample rather than read from disk because file
line endings and whitespace can vary across platforms (Windows CRLF vs
Unix LF), and the unified diff format is sensitive to both.
"""

from src.github.diff_parser import extract_changed_lines, annotate_pull_request
from src.github.models import ChangedFile, PullRequest


def test_empty_patch_returns_empty_set():
    """Empty patch text should return an empty set, not raise."""
    assert extract_changed_lines("") == set()
    assert extract_changed_lines("   ") == set()


def test_simple_addition():
    """A single added line should produce one line number."""
    patch = """@@ -1,2 +1,3 @@
 line one
+line added
 line two
"""
    assert extract_changed_lines(patch) == {2}


def test_multiple_added_lines_in_one_hunk():
    """Multiple consecutive added lines should all be captured."""
    patch = """@@ -1,2 +1,5 @@
 first
+second
+third
+fourth
 fifth
"""
    assert extract_changed_lines(patch) == {2, 3, 4}


def test_removed_lines_are_ignored():
    """Lines that were only removed should NOT appear in the result."""
    patch = """@@ -1,3 +1,1 @@
 stays
-removed1
-removed2
"""
    assert extract_changed_lines(patch) == set()


def test_replaced_line_counts_as_added():
    """A modified line (remove + add) should count as added."""
    patch = """@@ -1,1 +1,1 @@
-old version
+new version
"""
    assert extract_changed_lines(patch) == {1}


def test_multiple_hunks():
    """Multiple hunks in the same file should be combined into one set."""
    patch = """@@ -1,2 +1,3 @@
 line one
+added at top
 line two
@@ -10,1 +11,2 @@
 line ten
+added later
"""
    assert extract_changed_lines(patch) == {2, 12}


def test_realistic_multi_hunk_patch():
    """A realistic patch resembling what GitHub's API returns.

    Two important details for anyone editing this:

    1. Blank context lines must be " \\n" (single space + newline), not
       truly empty lines. We use list-join so this stays explicit.

    2. The hunk header counts must match the hunk content exactly.
       For "@@ -A,B +C,D @@", B is the number of old-file lines in the
       hunk (context + removes) and D is the number of new-file lines
       in the hunk (context + adds). The unidiff library is strict
       about this and returns nothing if the counts disagree.
    """
    # Hunk 1: header "@@ -1,4 +1,6 @@"
    #   Old file: 4 lines (3 context + 1 remove). Lines 1-4.
    #   New file: 6 lines (3 context + 3 add - 1 remove gives 6 total). Lines 1-6.
    #   Added at new-file lines: 2, 3, 6.
    #
    # Hunk 2: header "@@ -20,2 +22,4 @@"
    #   Old file: 2 lines (2 context). Lines 20-21.
    #   New file: 4 lines (2 context + 2 add). Lines 22-25.
    #   Added at new-file lines: 24, 25.
    patch = "\n".join([
        "@@ -1,4 +1,6 @@",
        " import os",
        "+import sys",
        "+import json",
        " ",                          # blank CONTEXT line (note the space)
        " def main():",
        "-    pass",
        "+    return os.getcwd()",
        "@@ -20,2 +22,4 @@ def helper():",
        "     return result",
        " ",                          # blank CONTEXT line
        "+def new_helper():",
        "+    return None",
        "",                           # trailing newline
    ])
    assert extract_changed_lines(patch) == {2, 3, 6, 24, 25}


def test_malformed_patch_returns_empty_set():
    """Garbage input should not crash; should return empty set."""
    assert extract_changed_lines("this is not a diff at all") == set()


def test_annotate_pull_request_populates_changed_lines():
    """annotate_pull_request should fill in changed_lines for each file."""
    file1 = ChangedFile(
        filename="src/a.py",
        status="modified",
        patch="@@ -1,1 +1,2 @@\n existing\n+added\n",
    )
    file2 = ChangedFile(
        filename="src/b.py",
        status="modified",
        patch="@@ -1,2 +1,3 @@\n one\n+two-and-a-half\n two\n",
    )

    pr = PullRequest(
        owner="x", repo="y", number=1, title="t", head_sha="abc",
        files=[file1, file2],
    )

    annotated = annotate_pull_request(pr)

    assert annotated.files[0].changed_lines == {2}
    assert annotated.files[1].changed_lines == {2}
    # Original PR object is unchanged (immutability).
    assert pr.files[0].changed_lines == set()


def test_annotate_preserves_other_fields():
    """annotate_pull_request should not lose data from the original PR."""
    file1 = ChangedFile(
        filename="src/a.py", status="added", patch="@@ -0,0 +1,1 @@\n+hi\n",
        contents="hi",
    )
    pr = PullRequest(
        owner="x", repo="y", number=1, title="Title", head_sha="abc123",
        files=[file1],
    )

    annotated = annotate_pull_request(pr)

    assert annotated.owner == "x"
    assert annotated.title == "Title"
    assert annotated.head_sha == "abc123"
    assert annotated.files[0].filename == "src/a.py"
    assert annotated.files[0].status == "added"
    assert annotated.files[0].contents == "hi"
    assert annotated.files[0].changed_lines == {1}


def test_binary_file_returns_empty():
    """Binary files have no useful patch; should not crash."""
    file1 = ChangedFile(filename="image.png", status="added", patch="")
    pr = PullRequest(
        owner="x", repo="y", number=1, title="t", head_sha="abc",
        files=[file1],
    )

    annotated = annotate_pull_request(pr)
    assert annotated.files[0].changed_lines == set()