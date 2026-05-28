"""
Dangerous function call check.

Flags calls to functions that execute arbitrary code, which are common
sources of security vulnerabilities:

    eval(user_input)   # Executes user_input as Python; arbitrary code execution
    exec(some_string)  # Same risk, but evaluates statements not expressions

If `user_input` is ever controlled by an attacker, eval/exec lets them
run any code they want with the privileges of your program.

There are legitimate uses (e.g., a REPL, a templating engine), but in
99% of cases these calls are a red flag. We flag them as errors so the
reviewer can confirm the use is intentional and safe.
"""

import ast
from typing import List

from src.analyzer.base import Finding, Severity


# Function names that are dangerous because they execute arbitrary code.
# Stored as a set for O(1) membership checks.
_DANGEROUS_CALLS = {"eval", "exec"}


class DangerousCallsVisitor(ast.NodeVisitor):
    """
    Detects calls to dangerous built-in functions.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect every function call in the file."""
        # `node.func` is the thing being called. For a bare call like
        # `eval(x)`, this is an ast.Name. For attribute calls like
        # `obj.eval(x)`, it's an ast.Attribute, and we don't flag those
        # because they're not the built-in eval.
        if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_CALLS:
            self.findings.append(Finding(
                file_path=self.file_path,
                line=node.lineno,
                severity=Severity.ERROR,
                rule_id="dangerous-call",
                message=(
                    f"Use of '{node.func.id}()' can execute arbitrary code "
                    f"and is a security risk if the input is not fully "
                    f"trusted. Consider safer alternatives like ast.literal_eval() "
                    f"for parsing data, or json.loads() for JSON."
                ),
            ))

        # Keep walking so nested calls are checked too.
        self.generic_visit(node)