"""
Unified diff parser.

GitHub's API gives us the diff for each changed file as a unified diff
patch (the same format `git diff` produces). This module extracts the
set of line numbers in the NEW version of each file that were added or
modified by the PR.

We use the `unidiff` library to handle the heavy lifting (parsing the
@@ headers, tracking line offsets through multiple hunks). Our job is
to wrap that into something simple: a set of line numbers per file.

Why "added or modified" rather than just "changed"? Because the new
file doesn't have "removed" lines anymore. From the new file's
perspective, every line was either copied from the old file
(unchanged context) or freshly written (added). We flag the freshly
written ones.

Edge cases this handles:
- Binary files: no patch is provided, so we return an empty set.
- Renamed files with no content change: also empty (nothing to flag).
- Multiple hunks per file: unidiff handles line tracking for us.
- Files with no patch at all: return empty (defensive).
"""

from typing import Set

from unidiff import PatchSet

from src.github.models import ChangedFile, PullRequest


def extract_changed_lines(patch_text: str) -> Set[int]:
    """
    Return the set of line numbers (in the NEW file) that were added or
    modified in this patch.

    Args:
        patch_text: A unified diff for a single file. Looks like the output
                    of `git diff -- path/to/file.py`.

    Returns:
        A set of 1-indexed line numbers. Empty set if the patch is empty,
        binary, or unparseable.
    """
    if not patch_text or not patch_text.strip():
        # Empty or whitespace-only patches happen for binary files, file
        # renames without content changes, and other edge cases.
        return set()

    # unidiff expects the patch to be a complete unified diff, including
    # the "---"/"+++" file header lines. GitHub's API omits those, so
    # we synthesize a minimal header before parsing.
    # This is a known quirk of working with GitHub's patch format.
    if not patch_text.startswith("---"):
        patch_text = "--- a/file\n+++ b/file\n" + patch_text

    try:
        patch_set = PatchSet(patch_text)
    except Exception:
        # unidiff can raise various exceptions on malformed input. We
        # treat any failure as "no changed lines we can identify",
        # which is safe: we'll just report nothing rather than crash.
        return set()

    changed: Set[int] = set()
    for patched_file in patch_set:
        for hunk in patched_file:
            for line in hunk:
                # `line.is_added` is True for lines starting with "+".
                # `line.target_line_no` is the line number in the NEW file.
                # (`source_line_no` would be the OLD line number, which we
                # don't care about since we're analyzing the new version.)
                if line.is_added and line.target_line_no is not None:
                    changed.add(line.target_line_no)
    return changed


def annotate_pull_request(pr: PullRequest) -> PullRequest:
    """
    Return a copy of `pr` where each ChangedFile has its `changed_lines`
    field populated from its patch.

    Why return a copy instead of mutating? Our models are frozen
    dataclasses (immutable). Returning a new object is the only way
    to "update" them, and the immutability prevents bugs where one
    part of the code accidentally modifies another part's data.
    """
    annotated_files = []
    for f in pr.files:
        changed_lines = extract_changed_lines(f.patch)
        # Build a new ChangedFile with the same data plus the parsed lines.
        # We can't use dataclasses.replace on frozen dataclasses cleanly
        # when the set type is involved, so we construct it directly.
        annotated_files.append(ChangedFile(
            filename=f.filename,
            status=f.status,
            patch=f.patch,
            changed_lines=changed_lines,
            contents=f.contents,
        ))

    return PullRequest(
        owner=pr.owner,
        repo=pr.repo,
        number=pr.number,
        title=pr.title,
        head_sha=pr.head_sha,
        files=annotated_files,
    )