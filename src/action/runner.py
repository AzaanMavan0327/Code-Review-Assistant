"""
GitHub Action runner.

This is the entry point that gets executed when your Action runs on a
pull request. It reads context from the environment that GitHub sets
automatically, runs the review pipeline, optionally enriches findings
with LLM explanations, and posts results back as PR comments.

Environment variables GitHub Actions sets for us:

  GITHUB_TOKEN          Auth token, automatically provided.
  GITHUB_REPOSITORY     "owner/repo" string.
  GITHUB_EVENT_NAME     Event that triggered the workflow.
  GITHUB_EVENT_PATH     Path to JSON file containing event details.

Inputs declared in action.yml (Day 15) are surfaced as INPUT_<NAME>
env vars by GitHub. We currently use:

  INPUT_ANTHROPIC_API_KEY   Optional. Enables LLM explanations.

Run as: python -m src.action.runner
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.action.poster import ReviewPoster
from src.github.client import GitHubAPIError, GitHubClient
from src.llm.reviewer import LLMReviewer
from src.review import review_pull_request


# Events we can review. "pull_request_target" is included because some
# repos use it for security reasons (runs with the base repo's token
# rather than the fork's, useful for actions that need write access).
_SUPPORTED_EVENTS = {"pull_request", "pull_request_target"}


@dataclass
class ActionContext:
    """
    Resolved context from the GitHub Actions environment.

    Building this once at startup means the rest of the code can stay
    free of os.environ lookups, which makes it easier to test.
    """
    github_token: str
    owner: str
    repo: str
    pr_number: int
    anthropic_api_key: Optional[str]


def load_action_context() -> ActionContext:
    """
    Read and validate the Action's context from environment variables.

    Raises:
        RuntimeError: if a required env var is missing or invalid.
        json.JSONDecodeError: if the event payload isn't valid JSON.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN env var is not set. "
            "Your workflow needs `permissions: pull-requests: write` "
            "to grant this automatically."
        )

    repo_str = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo_str:
        raise RuntimeError(
            f"GITHUB_REPOSITORY env var is invalid: {repo_str!r}. "
            f"Expected format 'owner/repo'."
        )
    owner, repo = repo_str.split("/", 1)

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name not in _SUPPORTED_EVENTS:
        raise RuntimeError(
            f"Unsupported event: {event_name!r}. "
            f"This action only handles {sorted(_SUPPORTED_EVENTS)}."
        )

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH env var is not set.")

    # Read the event payload. GitHub writes this to a file rather than an
    # env var because it can be quite large (full PR description, file lists,
    # etc.).
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr_data = payload.get("pull_request") or {}
    pr_number = pr_data.get("number")
    if not isinstance(pr_number, int):
        raise RuntimeError(
            f"Event payload missing pull_request.number "
            f"(got {pr_number!r}). Is this really a pull_request event?"
        )

    # Optional. If not set, we run in static-analysis-only mode (no LLM).
    # GitHub Actions surfaces declared inputs as INPUT_<NAME> env vars.
    anthropic_key = os.environ.get("INPUT_ANTHROPIC_API_KEY") or None

    return ActionContext(
        github_token=token,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        anthropic_api_key=anthropic_key,
    )


def run_action(context: ActionContext) -> int:
    """
    Execute the action with the given context.

    Args:
        context: Resolved Action context.

    Returns:
        Exit code. 0 = success, 1 = failure.
    """
    logger = logging.getLogger(__name__)

    client = GitHubClient(token=context.github_token)

    # Run the review pipeline (Phase 2).
    logger.info(
        f"Reviewing PR {context.owner}/{context.repo}#{context.pr_number}"
    )
    try:
        result = review_pull_request(
            client=client,
            owner=context.owner,
            repo=context.repo,
            number=context.pr_number,
            progress=lambda msg: logger.info(msg),
        )
    except GitHubAPIError as e:
        logger.error(f"Failed to review PR: {e}")
        return 1

    logger.info(
        f"Analysis complete: {len(result.findings)} finding(s) on changed lines"
    )

    # No findings? Don't post anything - keeps clean PRs clean.
    if not result.findings:
        logger.info("No issues found, skipping comment post.")
        return 0

    # If an Anthropic key is configured, run findings through the LLM
    # for enrichment. Otherwise post plain findings.
    findings_to_post = result.findings
    if context.anthropic_api_key:
        logger.info("Enriching findings with LLM explanations...")
        try:
            reviewer = LLMReviewer(api_key=context.anthropic_api_key)
            findings_to_post = reviewer.enrich(
                result.findings, result.source_by_file
            )
        except Exception as e:
            # If the LLM fails for any reason, log it and fall back to
            # plain findings. We never block a review on the LLM.
            logger.warning(f"LLM enrichment failed: {e}. Posting plain findings.")
            findings_to_post = result.findings

    # Post the review.
    poster = ReviewPoster(client)
    try:
        poster.post(
            owner=context.owner,
            repo=context.repo,
            pull_number=context.pr_number,
            commit_sha=result.head_sha,
            findings=findings_to_post,
        )
    except GitHubAPIError as e:
        logger.error(f"Failed to post review: {e}")
        return 1

    logger.info(f"Posted review with {len(findings_to_post)} comment(s).")
    return 0


def main() -> int:
    """
    Top-level entry point. Sets up logging, loads context, runs the action.

    Returns:
        Exit code suitable for sys.exit().
    """
    # Configure logging once at startup. The format includes timestamps
    # and severity so Action logs are easy to scan.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        context = load_action_context()
    except (RuntimeError, json.JSONDecodeError, OSError) as e:
        # Use the GitHub Actions error-annotation syntax so the error
        # shows up prominently in the Actions UI, not just in the logs.
        print(f"::error::{e}", file=sys.stderr)
        return 1

    return run_action(context)


if __name__ == "__main__":
    sys.exit(main())