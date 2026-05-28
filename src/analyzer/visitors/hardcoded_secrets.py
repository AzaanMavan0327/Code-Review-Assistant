"""
Hardcoded secrets check.

Detects API keys, passwords, tokens, and other secrets that have been
committed directly into source code. Hardcoded secrets are a major
security risk: anyone with read access to the repo (including everyone
on GitHub for public repos) can steal them.

Examples this catches:

    api_key = "sk-abc123def456ghi789"
    PASSWORD = "hunter2"
    aws_secret = "AKIAIOSFODNN7EXAMPLE"

The correct approach is to load secrets from environment variables or
a secret manager:

    api_key = os.environ["API_KEY"]

Detection strategy:
  1. Find assignments where the variable name suggests a secret
     (matches patterns like "*_key", "*password*", "*token*", etc.).
  2. Check that the assigned value is a string literal (not a function
     call or variable reference, which are safe).
  3. Optionally check that the string looks like a real secret rather
     than a placeholder like "" or "your_key_here".

This is intentionally conservative; we only flag obvious cases to keep
false positives low. A smarter tool would also detect specific provider
formats (Stripe's `sk_live_*`, AWS's `AKIA*`, etc.), but variable-name
based detection is a solid starting point.
"""

import ast
import re
from typing import List

from src.analyzer.base import Finding, Severity


# Variable names that suggest the value is a secret. Matched
# case-insensitively as substrings, so "API_KEY" and "my_api_key"
# both match the "api_key" pattern.
_SECRET_NAME_PATTERNS = [
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "private_key",
    "client_secret",
]

# Values that look like placeholders rather than real secrets.
# Anything matching these is ignored to reduce false positives.
_PLACEHOLDER_VALUES = {
    "",
    "your_key_here",
    "your_password_here",
    "changeme",
    "todo",
    "xxx",
    "...",
    "none",
    "null",
}

# Minimum length for a value to be considered a "real" secret.
# Most real API keys are at least 16 characters. Shorter strings
# are usually empty placeholders or labels.
_MIN_SECRET_LENGTH = 8


class HardcodedSecretsVisitor(ast.NodeVisitor):
    """
    Detects assignments where a secret-like variable name is set to a
    suspicious-looking string literal.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        """Handle `name = "value"` style assignments."""
        # `node.targets` is a list because Python allows `a = b = "value"`.
        # We check each target separately.
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._check_assignment(target.id, node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Handle `name: str = "value"` style assignments (with type hints)."""
        if isinstance(node.target, ast.Name) and node.value is not None:
            self._check_assignment(node.target.id, node.value, node.lineno)
        self.generic_visit(node)

    def _check_assignment(self, name: str, value: ast.expr, line: int) -> None:
        """Inspect one assignment to see if it looks like a hardcoded secret."""
        # Step 1: does the variable name suggest a secret?
        if not self._looks_like_secret_name(name):
            return

        # Step 2: is the value a string literal (and not something safe
        # like an env var lookup)?
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return

        string_value = value.value

        # Step 3: filter out obvious placeholders.
        if string_value.lower() in _PLACEHOLDER_VALUES:
            return
        if len(string_value) < _MIN_SECRET_LENGTH:
            return

        # All three checks passed; this looks like a real hardcoded secret.
        self.findings.append(Finding(
            file_path=self.file_path,
            line=line,
            severity=Severity.ERROR,
            rule_id="hardcoded-secret",
            message=(
                f"Variable '{name}' appears to contain a hardcoded secret. "
                f"Load it from an environment variable or secret manager "
                f"instead (e.g., os.environ['{name.upper()}'])."
            ),
        ))

    def _looks_like_secret_name(self, name: str) -> bool:
        """Return True if the variable name suggests it holds a secret."""
        lowered = name.lower()
        return any(pattern in lowered for pattern in _SECRET_NAME_PATTERNS)