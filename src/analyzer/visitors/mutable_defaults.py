"""
Mutable default argument check.

This catches one of the most common Python bugs:

    def add_item(item, items=[]):  # BUG: list is shared across all calls
        items.append(item)
        return items

The default `[]` is created ONCE when the function is defined, not each time
the function is called. So every call that doesn't pass `items` mutates the
same shared list, leading to confusing behavior:

    add_item(1)  # returns [1]
    add_item(2)  # returns [1, 2]  <- surprise!

The correct pattern is to use `None` as the default and create a fresh
mutable inside the function:

    def add_item(item, items=None):
        if items is None:
            items = []
        items.append(item)
        return items
"""

import ast
from typing import List

from src.analyzer.base import Finding, Severity


# AST node types that represent mutable literals. Tuples and frozensets
# are intentionally NOT here because they're immutable and safe as defaults.
_MUTABLE_LITERAL_TYPES = (ast.List, ast.Dict, ast.Set)

# Names of constructors that return mutable objects. If someone writes
# `def f(x=list())` that's just as buggy as `def f(x=[])`.
_MUTABLE_CONSTRUCTORS = {"list", "dict", "set"}


class MutableDefaultsVisitor(ast.NodeVisitor):
    """
    Scans function definitions for mutable default arguments.

    Flags both literal defaults (`[]`, `{}`, `set()`) and constructor
    calls (`list()`, `dict()`, `set()`).
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_defaults(node)
        # Keep walking so nested function definitions get checked too.
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_defaults(node)
        self.generic_visit(node)

    def _check_defaults(self, node: ast.FunctionDef) -> None:
        """Inspect each default value in this function's signature."""
        # `node.args.defaults` contains defaults for positional args.
        # `node.args.kw_defaults` contains defaults for keyword-only args.
        # We check both because both can have mutable default bugs.
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                # `kw_defaults` uses None as a placeholder for keyword-only
                # args that have no default. Skip those.
                continue

            if self._is_mutable_default(default):
                self.findings.append(Finding(
                    file_path=self.file_path,
                    line=default.lineno,
                    severity=Severity.ERROR,
                    rule_id="mutable-default",
                    message=(
                        f"Function '{node.name}' uses a mutable default "
                        f"argument. Defaults are shared across all calls, "
                        f"which causes subtle bugs. Use None as the default "
                        f"and create the mutable inside the function."
                    ),
                ))

    def _is_mutable_default(self, node: ast.expr) -> bool:
        """Return True if this AST node represents a mutable value."""
        # Case 1: literal mutables like [], {}, {1, 2}
        if isinstance(node, _MUTABLE_LITERAL_TYPES):
            return True

        # Case 2: constructor calls like list(), dict(), set()
        # We only catch the bare names; `collections.OrderedDict()` is not
        # flagged because that requires resolving imports, which is more
        # work than this simple check should do.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _MUTABLE_CONSTRUCTORS:
                return True

        return False