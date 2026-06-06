"""
Tests for the GitHub Action runner.

Two sets of tests:

  1. load_action_context: uses monkeypatch to control env vars and
     verifies parsing and validation logic.

  2. run_action: mocks the client, reviewer, and poster so we can
     verify the orchestration without making any real network calls.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.action.runner import ActionContext, load_action_context, run_action
from src.analyzer.base import Finding, Severity
from src.review import ReviewResult


# ---- Helpers ----


def _write_event(tmp_path, pr_number: int = 42) -> str:
    """Write a minimal GitHub event JSON file and return its path."""
    payload = {
        "pull_request": {
            "number": pr_number,
            "head": {"sha": "abc123"},
        }
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payload), encoding="utf-8")
    return str(event_path)


def _set_action_env(monkeypatch, event_path, *, with_anthropic=False):
    """Set the env vars that GitHub Actions would set when invoking us."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", event_path)
    if with_anthropic:
        monkeypatch.setenv("INPUT_ANTHROPIC_API_KEY", "sk-ant-fake")
    else:
        # Make sure no stale value is around from another test or the
        # developer's shell.
        monkeypatch.delenv("INPUT_ANTHROPIC_API_KEY", raising=False)


# ---- load_action_context tests ----


def test_loads_valid_environment(monkeypatch, tmp_path):
    """All required vars present should produce a populated ActionContext."""
    event_path = _write_event(tmp_path, pr_number=42)
    _set_action_env(monkeypatch, event_path)

    ctx = load_action_context()

    assert ctx.github_token == "ghp_fake"
    assert ctx.owner == "owner"
    assert ctx.repo == "repo"
    assert ctx.pr_number == 42
    assert ctx.anthropic_api_key is None


def test_anthropic_key_when_provided(monkeypatch, tmp_path):
    """INPUT_ANTHROPIC_API_KEY should be picked up if set."""
    event_path = _write_event(tmp_path)
    _set_action_env(monkeypatch, event_path, with_anthropic=True)

    ctx = load_action_context()

    assert ctx.anthropic_api_key == "sk-ant-fake"


def test_missing_token_raises(monkeypatch, tmp_path):
    """No GITHUB_TOKEN should raise a clear error."""
    event_path = _write_event(tmp_path)
    _set_action_env(monkeypatch, event_path)
    monkeypatch.delenv("GITHUB_TOKEN")

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        load_action_context()


def test_wrong_event_type_raises(monkeypatch, tmp_path):
    """Events other than pull_request should be rejected."""
    event_path = _write_event(tmp_path)
    _set_action_env(monkeypatch, event_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    with pytest.raises(RuntimeError, match="pull_request"):
        load_action_context()


def test_malformed_repository_raises(monkeypatch, tmp_path):
    """GITHUB_REPOSITORY without a slash should be rejected."""
    event_path = _write_event(tmp_path)
    _set_action_env(monkeypatch, event_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "no-slash-here")

    with pytest.raises(RuntimeError, match="GITHUB_REPOSITORY"):
        load_action_context()


def test_pull_request_target_event_is_accepted(monkeypatch, tmp_path):
    """pull_request_target should also be recognized."""
    event_path = _write_event(tmp_path)
    _set_action_env(monkeypatch, event_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")

    ctx = load_action_context()
    assert ctx.pr_number == 42


def test_missing_pr_number_in_event_raises(monkeypatch, tmp_path):
    """An event JSON without pull_request.number should be rejected."""
    bad_event = tmp_path / "event.json"
    bad_event.write_text(json.dumps({"pull_request": {}}), encoding="utf-8")
    _set_action_env(monkeypatch, str(bad_event))

    with pytest.raises(RuntimeError, match="pull_request.number"):
        load_action_context()


def test_malformed_event_json_raises(monkeypatch, tmp_path):
    """An event payload that isn't valid JSON should raise JSONDecodeError."""
    bad_event = tmp_path / "event.json"
    bad_event.write_text("not valid json at all", encoding="utf-8")
    _set_action_env(monkeypatch, str(bad_event))

    with pytest.raises(json.JSONDecodeError):
        load_action_context()


# ---- run_action tests ----


def _make_context(*, with_anthropic: bool = False) -> ActionContext:
    """Build a context suitable for run_action tests."""
    return ActionContext(
        github_token="ghp_fake",
        owner="o",
        repo="r",
        pr_number=1,
        anthropic_api_key="sk-ant-fake" if with_anthropic else None,
    )


def _sample_finding() -> Finding:
    return Finding(
        file_path="src/a.py",
        line=1,
        severity=Severity.ERROR,
        rule_id="dangerous-call",
        message="Use of eval()",
    )


@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_no_findings_means_no_post(
    mock_review_fn, mock_client_cls, mock_poster_cls,
):
    """A clean PR (no findings) should NOT trigger a comment post."""
    mock_review_fn.return_value = ReviewResult(
        pr_title="Clean PR",
        files_analyzed=1,
        files_skipped=0,
        findings=[],
        source_by_file={},
        head_sha="abc",
    )

    rc = run_action(_make_context())

    assert rc == 0
    mock_poster_cls.return_value.post.assert_not_called()


@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_findings_get_posted(mock_review_fn, mock_client_cls, mock_poster_cls):
    """Findings present should trigger a poster.post call with the right args."""
    mock_review_fn.return_value = ReviewResult(
        pr_title="Has issues",
        files_analyzed=1,
        files_skipped=0,
        findings=[_sample_finding()],
        source_by_file={"src/a.py": "x = eval('1')\n"},
        head_sha="deadbeef",
    )

    rc = run_action(_make_context())

    assert rc == 0
    mock_poster_cls.return_value.post.assert_called_once()
    kwargs = mock_poster_cls.return_value.post.call_args.kwargs
    assert kwargs["owner"] == "o"
    assert kwargs["pull_number"] == 1
    assert kwargs["commit_sha"] == "deadbeef"
    assert len(kwargs["findings"]) == 1


@patch("src.action.runner.LLMReviewer")
@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_anthropic_key_triggers_enrichment(
    mock_review_fn, mock_client_cls, mock_poster_cls, mock_reviewer_cls,
):
    """When an Anthropic key is set, findings get enriched before posting."""
    mock_review_fn.return_value = ReviewResult(
        pr_title="Has issues",
        files_analyzed=1,
        files_skipped=0,
        findings=[_sample_finding()],
        source_by_file={"src/a.py": "x = eval('1')\n"},
        head_sha="abc",
    )
    # Mocked reviewer returns... whatever; we just verify it was called.
    mock_reviewer_cls.return_value.enrich.return_value = []

    rc = run_action(_make_context(with_anthropic=True))

    # Reviewer was constructed with the right key and its enrich was called.
    mock_reviewer_cls.assert_called_once_with(api_key="sk-ant-fake")
    mock_reviewer_cls.return_value.enrich.assert_called_once()
    assert rc == 0


@patch("src.action.runner.LLMReviewer")
@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_llm_failure_falls_back_to_plain_findings(
    mock_review_fn, mock_client_cls, mock_poster_cls, mock_reviewer_cls,
):
    """If the LLM raises, we should still post the plain findings."""
    findings = [_sample_finding()]
    mock_review_fn.return_value = ReviewResult(
        pr_title="t", files_analyzed=1, files_skipped=0,
        findings=findings,
        source_by_file={"src/a.py": "x\n"},
        head_sha="abc",
    )
    # Reviewer constructor succeeds, but enrich raises.
    mock_reviewer_cls.return_value.enrich.side_effect = RuntimeError("LLM down")

    rc = run_action(_make_context(with_anthropic=True))

    # Despite the LLM failure, we still posted (with plain findings).
    assert rc == 0
    mock_poster_cls.return_value.post.assert_called_once()
    posted = mock_poster_cls.return_value.post.call_args.kwargs["findings"]
    assert posted == findings


@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_pipeline_error_returns_nonzero(
    mock_review_fn, mock_client_cls, mock_poster_cls,
):
    """A GitHub API error during the pipeline should return exit code 1."""
    from src.github.client import GitHubAPIError
    mock_review_fn.side_effect = GitHubAPIError("Not found")

    rc = run_action(_make_context())

    assert rc == 1
    mock_poster_cls.return_value.post.assert_not_called()


@patch("src.action.runner.ReviewPoster")
@patch("src.action.runner.GitHubClient")
@patch("src.action.runner.review_pull_request")
def test_post_error_returns_nonzero(
    mock_review_fn, mock_client_cls, mock_poster_cls,
):
    """A GitHub API error during posting should return exit code 1."""
    from src.github.client import GitHubAPIError
    mock_review_fn.return_value = ReviewResult(
        pr_title="t", files_analyzed=1, files_skipped=0,
        findings=[_sample_finding()],
        source_by_file={"src/a.py": "x\n"},
        head_sha="abc",
    )
    mock_poster_cls.return_value.post.side_effect = GitHubAPIError("denied")

    rc = run_action(_make_context())

    assert rc == 1