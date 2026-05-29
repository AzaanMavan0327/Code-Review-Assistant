"""
Pull request review pipeline.

Ties together the GitHub client, diff parser, and static analyzer to
produce a list of findings scoped to the lines a PR actually changed.

Keeping this in its own module (rather than inside the CLI) means:
1. It's easy to test without involving click or stdout.
2. The Phase 4 GitHub Action can call this directly, without going
   through the CLI's argument parsing.

The pipeline:
  1. Fetch the PR and its changed files.
  2. Parse each file's patch to find which lines were added/modified.
  3. For each changed Python file, fetch the full file contents.
  4. Run the static analyzer on each file.
  5. Filter findings to only those on changed lines.
"""

from typing import Callable, List, Optional

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Finding
from src.github.client import GitHubAPIError, GitHubClient
from src.github.diff_parser import annotate_pull_request


# Type alias for the progress callback. Takes a status message string.
# Returning nothing keeps the contract simple. Tests can pass None.
ProgressCallback = Callable[[str], None]


class ReviewResult:
    """
    Result of reviewing a pull request.

    Bundles the findings together with some metadata about the PR, so
    callers (CLI, GitHub Action) can show useful context without having
    to fetch the PR data again.
    """

    def __init__(
        self,
        pr_title: str,
        files_analyzed: int,
        files_skipped: int,
        findings: List[Finding],
    ) -> None:
        self.pr_title = pr_title
        self.files_analyzed = files_analyzed
        self.files_skipped = files_skipped
        self.findings = findings


def review_pull_request(
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    progress: Optional[ProgressCallback] = None,
) -> ReviewResult:
    """
    Run the full review pipeline on one pull request.

    Args:
        client: GitHubClient used for all API calls.
        owner, repo, number: identifies the pull request.
        progress: optional callback invoked with status messages. Lets the
                  CLI print progress without coupling this module to stdout.
                  If None, the pipeline runs silently.

    Returns:
        A ReviewResult containing all findings on changed lines.

    Raises:
        GitHubAPIError: if the PR cannot be fetched at all. Per-file errors
                        are caught internally and result in skipped files
                        rather than aborting the entire review.
    """
    # Helper that quietly does nothing if no callback was provided.
    # Avoids `if progress: progress(...)` scattered everywhere.
    def report(msg: str) -> None:
        if progress is not None:
            progress(msg)

    report(f"Fetching PR {owner}/{repo}#{number}...")
    pr = client.get_pull_request(owner, repo, number)
    report(f"PR title: {pr.title}")
    report(f"Files changed: {len(pr.files)}, Python files: {len(pr.python_files)}")

    if not pr.python_files:
        return ReviewResult(
            pr_title=pr.title,
            files_analyzed=0,
            files_skipped=0,
            findings=[],
        )

    # Annotate every file with the set of line numbers that changed.
    # We do this in one pass before fetching contents, because the diff
    # parsing is cheap and lets us skip files where nothing changed
    # (e.g., a renamed file with no content edits).
    pr = annotate_pull_request(pr)

    analyzer = CodeAnalyzer()
    all_findings: List[Finding] = []
    files_analyzed = 0
    files_skipped = 0

    for changed_file in pr.python_files:
        # If a file's diff is empty (rename only, binary, etc.), there are
        # no changed lines to report on, so skip without fetching contents.
        if not changed_file.changed_lines:
            report(f"Skipping {changed_file.filename} (no changed lines)")
            files_skipped += 1
            continue

        report(f"Analyzing {changed_file.filename}...")

        try:
            contents = client.get_file_content(
                owner, repo, changed_file.filename, pr.head_sha
            )
        except GitHubAPIError as e:
            # One file failing to fetch shouldn't kill the whole review.
            # Skip it and continue with the others.
            report(f"  Could not fetch {changed_file.filename}: {e}")
            files_skipped += 1
            continue

        try:
            findings = analyzer.analyze_source(contents, changed_file.filename)
        except SyntaxError:
            # The file isn't valid Python. Could be a syntax error in the
            # PR itself, or a .py file that's actually a template. Either
            # way, skip rather than crash.
            report(f"  Skipping {changed_file.filename} (not valid Python)")
            files_skipped += 1
            continue

        # Filter to only findings on lines this PR actually touched.
        # This is the whole point of Phase 2: don't flag pre-existing
        # issues the author didn't write.
        scoped = [f for f in findings if f.line in changed_file.changed_lines]
        all_findings.extend(scoped)
        files_analyzed += 1

    # Sort findings for predictable, top-to-bottom output.
    all_findings.sort(key=lambda f: (f.file_path, f.line))

    return ReviewResult(
        pr_title=pr.title,
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
        findings=all_findings,
    )