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

The result includes the source code we fetched, so downstream consumers
(like the LLM reviewer) don't have to re-fetch the same files.
"""

from typing import Callable, Dict, List, Optional

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Finding
from src.github.client import GitHubAPIError, GitHubClient
from src.github.diff_parser import annotate_pull_request


# Type alias for the progress callback. Takes a status message string.
ProgressCallback = Callable[[str], None]


class ReviewResult:
    """
    Result of reviewing a pull request.

    Bundles findings together with metadata about the PR and the source
    code we fetched, so callers (CLI, GitHub Action, LLM enrichment)
    don't need to re-fetch anything.
    """

    def __init__(
        self,
        pr_title: str,
        files_analyzed: int,
        files_skipped: int,
        findings: List[Finding],
        source_by_file: Optional[Dict[str, str]] = None,
    ) -> None:
        self.pr_title = pr_title
        self.files_analyzed = files_analyzed
        self.files_skipped = files_skipped
        self.findings = findings
        # Maps file path -> full source text. Used by LLM enrichment to
        # extract code context around each finding. Defaults to {} so
        # tests written before this field was added still work.
        self.source_by_file = source_by_file or {}


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
        progress: optional callback invoked with status messages.

    Returns:
        A ReviewResult containing all findings on changed lines.

    Raises:
        GitHubAPIError: if the PR cannot be fetched at all. Per-file errors
                        are caught internally and result in skipped files.
    """
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
            source_by_file={},
        )

    pr = annotate_pull_request(pr)

    analyzer = CodeAnalyzer()
    all_findings: List[Finding] = []
    source_by_file: Dict[str, str] = {}
    files_analyzed = 0
    files_skipped = 0

    for changed_file in pr.python_files:
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
            report(f"  Could not fetch {changed_file.filename}: {e}")
            files_skipped += 1
            continue

        try:
            findings = analyzer.analyze_source(contents, changed_file.filename)
        except SyntaxError:
            report(f"  Skipping {changed_file.filename} (not valid Python)")
            files_skipped += 1
            continue

        scoped = [f for f in findings if f.line in changed_file.changed_lines]
        all_findings.extend(scoped)
        # Keep the source around so callers (especially the LLM enricher)
        # can use it without re-fetching.
        source_by_file[changed_file.filename] = contents
        files_analyzed += 1

    all_findings.sort(key=lambda f: (f.file_path, f.line))

    return ReviewResult(
        pr_title=pr.title,
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
        findings=all_findings,
        source_by_file=source_by_file,
    )