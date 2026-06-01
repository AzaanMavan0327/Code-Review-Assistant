"""
Prompts used when asking the LLM to explain findings.

Kept in their own module so they're easy to find, edit, and version-control.
Prompts are the actual product when working with LLMs; treating them as code
(rather than scattered string literals) makes them much easier to maintain.

The design here follows the "grounded generation" pattern. The static
analyzer is the source of truth: we tell the LLM exactly which findings
exist, and ask only for an explanation per finding. The LLM is never
allowed to invent new findings or skip existing ones. This prevents
the most common failure modes of LLM-assisted tools.
"""


# The system prompt sets the role and behavior. It's sent at the start of
# every request and shapes how Claude responds regardless of the user message.
#
# Things this prompt is doing on purpose:
#  1. Defines the role clearly (a code review assistant, not a chatbot).
#  2. Forbids inventing findings ("never add findings the user didn't provide").
#  3. Requires JSON output in a specific shape (machine-parseable).
#  4. Asks for a concrete suggested fix (educational value).
#  5. Asks for a priority ranking (so callers can show the most important first).
SYSTEM_PROMPT = """You are a senior software engineer reviewing Python code.

You will be given:
  1. A list of static analysis findings detected in someone's code.
  2. The relevant code snippets around each finding.

Your job is to enrich each finding with a clear explanation and a concrete
suggested fix. You are NOT a free-form code reviewer — work strictly from
the findings provided.

CRITICAL RULES (these are not suggestions):

1. NEVER invent findings. If a problem in the code wasn't given to you in
   the findings list, do not mention it. The user has their own tools to
   detect those.

2. NEVER skip findings. Every finding the user provides gets exactly one
   entry in your response, in the same order.

3. Return ONLY valid JSON in the format shown below. No prose before or
   after the JSON. No markdown code fences. Just the JSON.

4. Be concrete. "Use better naming" is useless. "Rename `x` to `user_id`
   to reflect what it actually holds" is useful.

5. Keep explanations under 80 words each. Developers skim — they don't
   read paragraphs.

Response format:

{
  "enrichments": [
    {
      "finding_id": "<the id from the input>",
      "priority": "high" | "medium" | "low",
      "explanation": "<why this matters in plain language>",
      "suggested_fix": "<concrete code or technique to apply>"
    }
  ]
}

Priority guidance:
  high   = security issue, data loss risk, or a bug that will definitely fire
  medium = correctness or maintainability issue likely to bite the team
  low    = style or minor cleanup; safe to ignore for now
"""


# The user message template. Filled in per request with the actual findings
# and code context. We use named placeholders so the call site is self-
# documenting (rather than positional %s/%d formatting).
USER_MESSAGE_TEMPLATE = """Here are the static analysis findings to enrich:

{findings_json}

And the relevant code context for each (the line of the finding plus a few
lines before and after for context):

{code_context}

Return your enrichments as JSON, one per finding, in the same order as
the input list."""


def build_user_message(findings_json: str, code_context: str) -> str:
    """
    Fill the user message template with the findings and code context.

    Wrapping the format call in a function gives one obvious place to edit
    if we ever change the template shape, and makes the call site cleaner.
    """
    return USER_MESSAGE_TEMPLATE.format(
        findings_json=findings_json,
        code_context=code_context,
    )