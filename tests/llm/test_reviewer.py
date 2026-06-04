"""
Tests for the LLM reviewer.

We mock the Anthropic client so tests run instantly, never make real API
calls, and behave deterministically. This is the same pattern used in
test_client.py for the GitHub client.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.analyzer.base import Finding, Severity
from src.llm.reviewer import EnrichedFinding, LLMReviewer


def _make_mock_client(response_text: str) -> MagicMock:
    """
    Build a mock Anthropic client whose `messages.create` returns the
    given text as the response.

    The real Anthropic response has nested structure (response.content is
    a list of content blocks, each with a .text attribute). We replicate
    just enough of that structure for the reviewer to work.
    """
    content_block = MagicMock()
    content_block.text = response_text

    message = MagicMock()
    message.content = [content_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _sample_finding(line: int = 1, rule: str = "test-rule") -> Finding:
    """Helper: build a finding for use in tests."""
    return Finding(
        file_path="test.py",
        line=line,
        severity=Severity.WARNING,
        rule_id=rule,
        message="something is off",
    )


def test_empty_findings_returns_empty_list():
    """No findings means no API call; should return [] immediately."""
    client = _make_mock_client("")
    reviewer = LLMReviewer(client=client)

    result = reviewer.enrich([], {})

    assert result == []
    # Confirm we didn't waste an API call on nothing.
    client.messages.create.assert_not_called()


def test_well_formed_response_produces_enriched_findings():
    """A valid JSON response should be parsed into EnrichedFinding objects."""
    response = json.dumps({
        "enrichments": [
            {
                "finding_id": "finding_0",
                "priority": "high",
                "explanation": "This is dangerous.",
                "suggested_fix": "Use os.environ instead.",
            }
        ]
    })
    client = _make_mock_client(response)
    reviewer = LLMReviewer(client=client)

    findings = [_sample_finding()]
    source = {"test.py": "x = 1\n"}

    result = reviewer.enrich(findings, source)

    assert len(result) == 1
    assert isinstance(result[0], EnrichedFinding)
    assert result[0].priority == "high"
    assert result[0].explanation == "This is dangerous."
    assert result[0].suggested_fix == "Use os.environ instead."
    assert result[0].finding is findings[0]


def test_response_with_code_fences_is_parsed():
    """LLMs sometimes wrap JSON in ```json fences; we should tolerate that."""
    response = (
        "```json\n"
        + json.dumps({
            "enrichments": [
                {
                    "finding_id": "finding_0",
                    "priority": "low",
                    "explanation": "minor thing",
                    "suggested_fix": "remove it",
                }
            ]
        })
        + "\n```"
    )
    client = _make_mock_client(response)
    reviewer = LLMReviewer(client=client)

    result = reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})

    assert len(result) == 1
    assert result[0].priority == "low"
    assert result[0].explanation == "minor thing"


def test_malformed_json_returns_fallback():
    """If JSON parsing fails, we should return fallback enrichments."""
    client = _make_mock_client("not valid json at all {{{")
    reviewer = LLMReviewer(client=client)

    findings = [_sample_finding()]
    result = reviewer.enrich(findings, {"test.py": "x = 1\n"})

    # Still returned one result, didn't crash.
    assert len(result) == 1
    # The fallback explanation mentions the parse error.
    assert "Parse error" in result[0].explanation
    # The original finding is still there.
    assert result[0].finding is findings[0]


def test_missing_enrichments_key_returns_fallback():
    """Response without the 'enrichments' key should fall back gracefully."""
    response = json.dumps({"something_else": []})
    client = _make_mock_client(response)
    reviewer = LLMReviewer(client=client)

    result = reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})

    assert len(result) == 1
    assert "Parse error" in result[0].explanation


def test_partial_response_falls_back_for_missing_findings():
    """If the LLM skips one finding, that finding still gets a fallback."""
    response = json.dumps({
        "enrichments": [
            {
                "finding_id": "finding_0",
                "priority": "high",
                "explanation": "first one",
                "suggested_fix": "fix it",
            }
            # finding_1 is intentionally missing
        ]
    })
    client = _make_mock_client(response)
    reviewer = LLMReviewer(client=client)

    findings = [_sample_finding(line=1), _sample_finding(line=10)]
    result = reviewer.enrich(findings, {"test.py": "x = 1\n" * 20})

    # Both findings got results; the second one is a fallback.
    assert len(result) == 2
    assert result[0].explanation == "first one"
    assert "no enrichment returned" in result[1].explanation


def test_out_of_order_enrichments_are_matched_correctly():
    """Enrichments returned in reverse order should still match by id."""
    response = json.dumps({
        "enrichments": [
            {
                "finding_id": "finding_1",   # second finding's id
                "priority": "low",
                "explanation": "for second",
                "suggested_fix": "fix2",
            },
            {
                "finding_id": "finding_0",   # first finding's id
                "priority": "high",
                "explanation": "for first",
                "suggested_fix": "fix1",
            },
        ]
    })
    client = _make_mock_client(response)
    reviewer = LLMReviewer(client=client)

    findings = [_sample_finding(line=1), _sample_finding(line=10)]
    result = reviewer.enrich(findings, {"test.py": "x = 1\n" * 20})

    # Result order matches input order, even though LLM returned them reversed.
    assert result[0].explanation == "for first"
    assert result[1].explanation == "for second"


def test_code_context_is_extracted_around_finding_line():
    """The user message should include code context around each finding's line."""
    client = _make_mock_client(json.dumps({"enrichments": []}))
    reviewer = LLMReviewer(client=client)

    # Build a source file where line 10 is distinctive so we can spot it.
    source = "\n".join([f"line_{i}_content" for i in range(1, 21)])
    findings = [_sample_finding(line=10)]

    reviewer.enrich(findings, {"test.py": source})

    # Inspect the user message that got sent.
    call_args = client.messages.create.call_args
    user_message = call_args.kwargs["messages"][0]["content"]

    # The line we flagged should be in the context.
    assert "line_10_content" in user_message
    # And some neighbors (5 above, 5 below by default).
    assert "line_5_content" in user_message
    assert "line_15_content" in user_message


def test_api_error_returns_fallback():
    """If the Anthropic API raises, we should fall back gracefully."""
    from anthropic import APIError

    client = MagicMock()
    # APIError requires specific construction args; we mimic the type.
    error = APIError(
        message="rate limited",
        request=MagicMock(),
        body=None,
    )
    client.messages.create.side_effect = error

    reviewer = LLMReviewer(client=client)
    findings = [_sample_finding()]
    result = reviewer.enrich(findings, {"test.py": "x = 1\n"})

    assert len(result) == 1
    assert "API error" in result[0].explanation
    # Original finding is preserved so callers can still display it.
    assert result[0].finding is findings[0]


def test_fallback_priority_maps_from_severity():
    """When the LLM is unavailable, priority defaults to severity-based mapping."""
    client = _make_mock_client("not json")  # forces fallback
    reviewer = LLMReviewer(client=client)

    error_finding = Finding(
        file_path="x.py", line=1,
        severity=Severity.ERROR, rule_id="r", message="m",
    )
    warning_finding = Finding(
        file_path="x.py", line=2,
        severity=Severity.WARNING, rule_id="r", message="m",
    )
    info_finding = Finding(
        file_path="x.py", line=3,
        severity=Severity.INFO, rule_id="r", message="m",
    )

    result = reviewer.enrich(
        [error_finding, warning_finding, info_finding],
        {"x.py": "x\ny\nz\n"},
    )

    assert result[0].priority == "high"      # ERROR → high
    assert result[1].priority == "medium"    # WARNING → medium
    assert result[2].priority == "low"       # INFO → low


# ---- Cache integration tests ----


def test_cache_miss_calls_api_and_stores_response(tmp_path):
    """On a cache miss, we should call the API and save the response."""
    import json
    from src.llm.cache import ResponseCache

    response_text = json.dumps({
        "enrichments": [{
            "finding_id": "finding_0",
            "priority": "low",
            "explanation": "fresh from api",
            "suggested_fix": "",
        }]
    })
    client = _make_mock_client(response_text)
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    reviewer = LLMReviewer(client=client, cache=cache)
    result = reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})

    # API was called once.
    assert client.messages.create.call_count == 1
    # Response is what came back from the API.
    assert result[0].explanation == "fresh from api"

    # The response should now be in the cache for next time.
    # We verify by calling enrich again with the same inputs and
    # confirming the API isn't hit a second time.
    result2 = reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})
    assert client.messages.create.call_count == 1  # still 1, not 2
    assert result2[0].explanation == "fresh from api"


def test_cache_hit_skips_api_call(tmp_path):
    """When the cache already has a value, we should NOT call the API."""
    import json
    from src.llm.cache import ResponseCache

    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))
    client = _make_mock_client("never-used")

    # Pre-populate the cache. We need to compute the same key the
    # reviewer will compute, which means simulating what _serialize_findings
    # and _build_code_context would produce.
    reviewer_for_keys = LLMReviewer(client=client, cache=cache)
    findings = [_sample_finding()]
    source_by_file = {"test.py": "x = 1\n"}
    findings_json = reviewer_for_keys._serialize_findings(findings)
    code_context = reviewer_for_keys._build_code_context(findings, source_by_file)

    pre_cached = json.dumps({
        "enrichments": [{
            "finding_id": "finding_0",
            "priority": "medium",
            "explanation": "from cache",
            "suggested_fix": "",
        }]
    })
    cache.set(cache.make_key(findings_json, code_context), pre_cached)

    # Now use a fresh reviewer; cache hit means no API call.
    reviewer = LLMReviewer(client=client, cache=cache)
    result = reviewer.enrich(findings, source_by_file)

    client.messages.create.assert_not_called()
    assert result[0].explanation == "from cache"


def test_no_cache_means_every_call_hits_api(tmp_path):
    """Without a cache, identical requests should still hit the API."""
    import json

    response = json.dumps({
        "enrichments": [{
            "finding_id": "finding_0",
            "priority": "low",
            "explanation": "no cache",
            "suggested_fix": "",
        }]
    })
    client = _make_mock_client(response)

    # No cache argument; every call should call the API.
    reviewer = LLMReviewer(client=client)
    reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})
    reviewer.enrich([_sample_finding()], {"test.py": "x = 1\n"})

    assert client.messages.create.call_count == 2