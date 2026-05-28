"""
Function length check.

Flags functions longer than a threshold number of lines. Long functions
are harder to test, read, and modify, since they usually do too many
things at once.

Industry rule of thumb: functions should fit on one screen, roughly
50 lines. Some teams use stricter limits (25-30 lines).

We measure "logical" length using start and end line numbers, which
includes blank lines and comments. That's a slight overcount, but it's
simple and consistent.
"""

import ast
from typing import List

from src.analyzer.base import Finding, Severity


# Threshold in lines. Functions longer than this are flagged.
LENGTH_THRESHOLD = 50


class FunctionLengthVisitor(ast.NodeVisitor):
    """
    Detects functions that span more than LENGTH_THRESHOLD lines.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_length(node)
        # Keep walking so nested functions and methods get checked too.
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_length(node)
        self.generic_visit(node)

    def _check_length(self, node: ast.FunctionDef) -> None:
        """Measure a single function and emit a finding if it's too long."""
        # `end_lineno` was added in Python 3.8. It's the line number of the
        # last line of the function body. We add 1 because the count is
        # inclusive on both ends: a function from line 10 to line 12 spans
        # 3 lines (10, 11, 12), so 12 - 10 + 1 = 3.
        if node.end_lineno is None:
            return  # Defensive: should never happen on Python 3.8+.

        length = node.end_lineno - node.lineno + 1

        if length > LENGTH_THRESHOLD:
            self.findings.append(Finding(
                file_path=self.file_path,
                line=node.lineno,
                severity=Severity.WARNING,
                rule_id="function-length",
                message=(
                    f"Function '{node.name}' is {length} lines long "
                    f"(threshold: {LENGTH_THRESHOLD}). Consider splitting "
                    f"it into smaller functions."
                ),
            ))