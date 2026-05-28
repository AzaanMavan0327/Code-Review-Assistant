"""
Cyclomatic complexity check.

Cyclomatic complexity counts the number of independent paths through a
function. Each branch point (if, for, while, etc.) adds one path. Higher
complexity means the function is harder to test and reason about.

Industry rule of thumb: complexity above 10 is a warning sign.

Reference: McCabe, T.J. (1976). "A Complexity Measure."
"""

import ast
from typing import List

from src.analyzer.base import Finding, Severity


# Threshold above which we flag a function. 10 is the common industry default.
COMPLEXITY_THRESHOLD = 10


class _FunctionComplexityCounter(ast.NodeVisitor):
    """
    Counts complexity inside a single function.

    Starts at 1 (the function itself is one path) and adds 1 for each
    branch point encountered. The leading underscore in the class name
    signals "this is internal to this module; don't import it elsewhere."
    """

    def __init__(self) -> None:
        # Every function starts with complexity 1 (one path through it).
        self.complexity = 1

    # Each `visit_X` method is called automatically when the visitor
    # encounters an AST node of type X. This is the visitor pattern,
    # built into Python's `ast` module.

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)  # Keep walking deeper into nested code.

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Each `except` clause is a separate path through the function.
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # `and`/`or` short-circuit, so each additional operand is a branch.
        # `a and b and c` has two BoolOp operands beyond the first, so +2.
        self.complexity += len(node.values) - 1
        self.generic_visit(node)


class ComplexityVisitor(ast.NodeVisitor):
    """
    Top-level visitor that scans an entire file for high-complexity functions.

    For each function definition it encounters, it runs a fresh
    `_FunctionComplexityCounter` and emits a Finding if the threshold
    is exceeded.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        # Note: we do NOT call generic_visit here, because we don't want
        # to count complexity for nested functions as part of the outer one.
        # Instead, we explicitly scan the body for nested function defs.
        for child in ast.walk(node):
            if isinstance(child, ast.FunctionDef) and child is not node:
                self._check_function(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Async functions need the same treatment as regular functions.
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef) -> None:
        """Run the complexity counter on one function and record a finding."""
        counter = _FunctionComplexityCounter()
        counter.visit(node)

        if counter.complexity > COMPLEXITY_THRESHOLD:
            self.findings.append(Finding(
                file_path=self.file_path,
                line=node.lineno,
                severity=Severity.WARNING,
                rule_id="complexity",
                message=(
                    f"Function '{node.name}' has cyclomatic complexity of "
                    f"{counter.complexity} (threshold: {COMPLEXITY_THRESHOLD}). "
                    f"Consider breaking it into smaller functions."
                ),
            ))