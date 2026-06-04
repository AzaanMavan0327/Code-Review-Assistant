"""
LLM-powered finding enrichment.

The `LLMReviewer` takes a list of findings from the static analyzer and
asks Claude to generate a clear explanation and concrete suggested fix
for each one. The static analyzer remains the source of truth; the LLM
only enriches what's already there.

Design notes:

  - "Grounded generation" pattern: the LLM never produces findings of
    its own. It explains and prioritizes; that's it. This prevents
    hallucinations and makes the output reproducible.

  - Code context: for each finding, we send Claude a few lines around the
    finding's line number, not the entire file. Less context means cheaper
    requests, faster responses, and Claude focuses on the right spot.

  - Defensive JSON parsing: LLMs occasionally return malformed JSON or
    wrap their output in markdown code fences. We strip fences and try
    to parse, and if parsing fails we return the original findings
    unmodified rather than crashing the whole tool.

  - Optional caching: if a ResponseCache is provided, we hash each
    (findings, context) pair and reuse the previous LLM response. Saves
    money during development and makes the CLI feel instant on re-runs.
"""

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from anthropic import Anthropic, APIError

from src.analyzer.base import Finding
from src.config import get_anthropic_api_key
from src.llm.cache import ResponseCache
from src.llm.prompts import SYSTEM_PROMPT, build_user_message


# Number of lines of context to include on either side of each finding.
# 5 above + 5 below = 11 lines total per finding.
_CONTEXT_LINES = 5


# The model to use. Sonnet is the daily-driver model: high quality,
# significantly cheaper than Opus, fast enough for interactive use.
_MODEL = "claude-sonnet-4-5"


# Max tokens for the response. Enough for ~10 enriched findings with
# detailed explanations. Bounding this prevents runaway bills if
# something goes wrong with the prompt.
_MAX_TOKENS = 2000


@dataclass(frozen=True)
class EnrichedFinding:
    """
    A static analysis finding plus the LLM's explanation and suggested fix.

    `priority` is the LLM's assessment of how urgent this is, which can
    differ from `severity` (set by the static analyzer). The analyzer
    decides "this is technically an error"; the LLM decides "this is
    actually important right now."
    """
    finding: Finding
    priority: str             # "high", "medium", or "low"
    explanation: str
    suggested_fix: str


class LLMReviewer:
    """
    Enriches static analysis findings with LLM-generated explanations.

    Usage:
        reviewer = LLMReviewer(cache=ResponseCache())
        enriched = reviewer.enrich(findings, source_by_file)
        for ef in enriched:
            print(ef.explanation)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[Anthropic] = None,
        cache: Optional[ResponseCache] = None,
    ) -> None:
        """
        Args:
            api_key: Anthropic API key. If None, loads from environment.
            client: Pre-built Anthropic client. Mainly useful in tests
                to inject a mock without going through real authentication.
                If provided, api_key is ignored.
            cache: Optional ResponseCache. If provided, identical inputs
                return the previous response instead of calling the API.
                If None, every call hits the API.
        """
        if client is not None:
            self._client = client
        else:
            self._client = Anthropic(api_key=api_key or get_anthropic_api_key())
        self._cache = cache

    def enrich(
        self,
        findings: List[Finding],
        source_by_file: Dict[str, str],
    ) -> List[EnrichedFinding]:
        """
        Call Claude to enrich the given findings.

        Args:
            findings: The findings to enrich. Order is preserved in the output.
            source_by_file: Maps file paths to their full source code. Used
                to extract a small window of context around each finding.

        Returns:
            One EnrichedFinding per input finding, in the same order. If
            the API call fails or the response can't be parsed, returns
            "fallback" EnrichedFinding objects that wrap the originals
            without real explanations. The tool stays useful even when
            the LLM is unavailable.
        """
        if not findings:
            return []

        findings_json = self._serialize_findings(findings)
        code_context = self._build_code_context(findings, source_by_file)

        try:
            response_text = self._call_api(findings_json, code_context)
        except APIError as e:
            return self._fallback_enrichments(findings, reason=f"API error: {e}")

        try:
            enrichments_data = self._parse_response(response_text)
        except (ValueError, KeyError) as e:
            return self._fallback_enrichments(findings, reason=f"Parse error: {e}")

        return self._match_enrichments(findings, enrichments_data)

    def _serialize_findings(self, findings: List[Finding]) -> str:
        """Convert findings to a JSON string Claude can read."""
        payload = [
            {
                "id": f"finding_{i}",
                "file": f.file_path,
                "line": f.line,
                "severity": f.severity.value,
                "rule": f.rule_id,
                "message": f.message,
            }
            for i, f in enumerate(findings)
        ]
        return json.dumps(payload, indent=2)

    def _build_code_context(
        self,
        findings: List[Finding],
        source_by_file: Dict[str, str],
    ) -> str:
        """Extract a few lines around each finding for the LLM."""
        sections = []
        for i, f in enumerate(findings):
            source = source_by_file.get(f.file_path, "")
            if not source:
                sections.append(f"finding_{i} ({f.file_path}:{f.line}): <source unavailable>")
                continue

            lines = source.splitlines()
            start = max(0, f.line - 1 - _CONTEXT_LINES)
            end = min(len(lines), f.line + _CONTEXT_LINES)

            numbered = "\n".join(
                f"{n + 1:4d} | {lines[n]}"
                for n in range(start, end)
            )
            sections.append(
                f"finding_{i} ({f.file_path}:{f.line}):\n{numbered}"
            )

        return "\n\n".join(sections)

    def _call_api(self, findings_json: str, code_context: str) -> str:
        """
        Send the prompt to Claude and return the raw response text.

        If a cache is configured, check it first. On miss, call the API
        and store the response for next time.
        """
        cache_key = None
        if self._cache is not None:
            cache_key = self._cache.make_key(findings_json, code_context)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Cache miss (or no cache configured); make the real API call.
        message = self._client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_user_message(findings_json, code_context),
                }
            ],
        )
        response_text = message.content[0].text

        # Store for next time, but only if we have a cache.
        if self._cache is not None and cache_key is not None:
            self._cache.set(cache_key, response_text)

        return response_text

    def _parse_response(self, response_text: str) -> List[Dict]:
        """
        Parse Claude's JSON response into a list of enrichment dicts.

        Strips markdown code fences if present (some responses come back
        wrapped in ```json...```), then validates the expected shape.
        """
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response_text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"response was not valid JSON: {e}") from e

        if not isinstance(data, dict) or "enrichments" not in data:
            raise ValueError("response missing 'enrichments' key")

        enrichments = data["enrichments"]
        if not isinstance(enrichments, list):
            raise ValueError("'enrichments' was not a list")

        return enrichments

    def _match_enrichments(
        self,
        findings: List[Finding],
        enrichments_data: List[Dict],
    ) -> List[EnrichedFinding]:
        """
        Pair each finding with its enrichment by matching ids.

        Robust to the LLM returning enrichments out of order, or skipping
        one despite being told not to.
        """
        by_id = {e.get("finding_id"): e for e in enrichments_data}

        result = []
        for i, finding in enumerate(findings):
            enrich = by_id.get(f"finding_{i}")
            if enrich is None:
                result.append(self._fallback_for_one(finding, "no enrichment returned"))
                continue

            result.append(EnrichedFinding(
                finding=finding,
                priority=enrich.get("priority", "medium"),
                explanation=enrich.get("explanation", ""),
                suggested_fix=enrich.get("suggested_fix", ""),
            ))

        return result

    def _fallback_enrichments(
        self,
        findings: List[Finding],
        reason: str,
    ) -> List[EnrichedFinding]:
        """Return fallback enrichments for every finding when the API fails."""
        return [self._fallback_for_one(f, reason) for f in findings]

    def _fallback_for_one(self, finding: Finding, reason: str) -> EnrichedFinding:
        """Build a fallback EnrichedFinding that wraps the original finding."""
        priority_default = {
            "error": "high",
            "warning": "medium",
            "info": "low",
        }.get(finding.severity.value, "medium")

        return EnrichedFinding(
            finding=finding,
            priority=priority_default,
            explanation=f"(LLM enrichment unavailable: {reason})",
            suggested_fix="",
        )