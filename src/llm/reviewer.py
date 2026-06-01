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
"""

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from anthropic import Anthropic, APIError

from src.analyzer.base import Finding
from src.config import get_anthropic_api_key
from src.llm.prompts import SYSTEM_PROMPT, build_user_message


# Number of lines of context to include on either side of each finding.
# 5 above + 5 below = 11 lines total per finding, which is enough for
# Claude to understand the situation without being expensive.
_CONTEXT_LINES = 5


# The model to use. Sonnet is the daily-driver model: high quality,
# significantly cheaper than Opus, fast enough for interactive use.
# Update this string if Anthropic releases a newer Sonnet version.
_MODEL = "claude-sonnet-4-5"


# Max tokens for the response. Enough for ~10 enriched findings with
# detailed explanations and fixes. Keeping this bounded prevents runaway
# bills if something goes wrong with the prompt.
_MAX_TOKENS = 2000


@dataclass(frozen=True)
class EnrichedFinding:
    """
    A static analysis finding plus the LLM's explanation and suggested fix.

    The original `finding` is preserved so callers can still access the
    file path, line number, severity, etc. The new fields (`priority`,
    `explanation`, `suggested_fix`) come from the LLM.

    `priority` is the LLM's assessment of how urgent this is for the
    reviewer to fix — distinct from `severity`, which is set by the
    static analyzer. They overlap but aren't identical; the LLM has
    code context and can sometimes downgrade or upgrade urgency.
    """
    finding: Finding
    priority: str             # "high", "medium", or "low"
    explanation: str
    suggested_fix: str


class LLMReviewer:
    """
    Enriches static analysis findings with LLM-generated explanations.

    Usage:
        reviewer = LLMReviewer()
        enriched = reviewer.enrich(findings, source_code)
        for ef in enriched:
            print(ef.explanation)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[Anthropic] = None,
    ) -> None:
        """
        Args:
            api_key: Anthropic API key. If None, loads from environment
                via the config module.
            client: Pre-built Anthropic client. Mainly useful in tests,
                where you want to inject a mock client without going
                through real authentication. If provided, api_key is
                ignored.
        """
        if client is not None:
            self._client = client
        else:
            self._client = Anthropic(api_key=api_key or get_anthropic_api_key())

    def enrich(self, findings: List[Finding], source_by_file: Dict[str, str]) -> List[EnrichedFinding]:
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
            # No findings means no API call needed. Saves money and avoids
            # an awkward "explain nothing" prompt.
            return []

        # Build the structured inputs Claude will see.
        findings_json = self._serialize_findings(findings)
        code_context = self._build_code_context(findings, source_by_file)

        # Make the API call. Any failure returns fallback enrichments
        # rather than raising, so one LLM hiccup doesn't kill the tool.
        try:
            response_text = self._call_api(findings_json, code_context)
        except APIError as e:
            return self._fallback_enrichments(findings, reason=f"API error: {e}")

        # Parse the JSON response. Same fallback approach: if it's broken,
        # we still return useful output rather than crashing.
        try:
            enrichments_data = self._parse_response(response_text)
        except (ValueError, KeyError) as e:
            return self._fallback_enrichments(findings, reason=f"Parse error: {e}")

        return self._match_enrichments(findings, enrichments_data)

    def _serialize_findings(self, findings: List[Finding]) -> str:
        """
        Convert findings to a JSON string Claude can read.

        We give each finding a stable `id` (its index) so Claude can
        reference it in the response without us needing to do fuzzy
        matching on file paths and line numbers.
        """
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
        """
        Extract a few lines around each finding to give Claude context.

        Returns a single string with sections labeled by finding id, so
        Claude can map context back to the right finding when it composes
        its response.
        """
        sections = []
        for i, f in enumerate(findings):
            source = source_by_file.get(f.file_path, "")
            if not source:
                sections.append(f"finding_{i} ({f.file_path}:{f.line}): <source unavailable>")
                continue

            lines = source.splitlines()
            # Clamp to valid line indices. Lines are 1-indexed but our list
            # is 0-indexed, so subtract 1 when slicing.
            start = max(0, f.line - 1 - _CONTEXT_LINES)
            end = min(len(lines), f.line + _CONTEXT_LINES)

            # Number each line so Claude can see exactly which one was flagged.
            numbered = "\n".join(
                f"{n + 1:4d} | {lines[n]}"
                for n in range(start, end)
            )
            sections.append(
                f"finding_{i} ({f.file_path}:{f.line}):\n{numbered}"
            )

        return "\n\n".join(sections)

    def _call_api(self, findings_json: str, code_context: str) -> str:
        """Send the prompt to Claude and return the raw response text."""
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
        # The response has a list of content blocks; we asked for plain text
        # so there should be exactly one text block.
        return message.content[0].text

    def _parse_response(self, response_text: str) -> List[Dict]:
        """
        Parse Claude's JSON response into a list of enrichment dicts.

        Tries hard to handle slight format deviations:
        - Strips markdown code fences (```json ... ```) if present.
        - Tolerates leading/trailing whitespace.
        - Validates that the response has the expected "enrichments" key.

        Raises ValueError if the response isn't usable.
        """
        # Strip markdown code fences. LLMs sometimes wrap JSON in them
        # despite being told not to. The regex matches ```json or ``` on
        # either side of the actual content.
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
        one despite being told not to: any finding without a matching
        enrichment gets a fallback.
        """
        # Build a map of id -> enrichment dict for O(1) lookup.
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
        # Map severity to a sensible default priority when we have no LLM
        # input. Errors are high-priority by default; warnings are medium.
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