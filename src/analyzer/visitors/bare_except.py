"""
Bare except clause check.

A "bare" except looks like this:

    try:
        do_something()
    except:           # <- catches EVERYTHING, including KeyboardInterrupt
        pass

This is dangerous for two reasons:

1. It catches `KeyboardInterrupt` and `SystemExit`, which means users
   can't Ctrl+C out of your program and `sys.exit()` calls get swallowed.

2. It hides real bugs. If `do_something()` raises an unexpected error,
   you'll never know because the except clause silently eats it.

The fix is to catch a specific exception, or at least `Exception` (which
excludes the system-level exceptions mentioned above):

    try:
        do_something()
    except ValueError as e:
        log.warning("bad value: %s", e)
"""

import ast
from typing import List

from src.analyzer.base import Finding, Severity


class BareExceptVisitor(ast.NodeVisitor):
    """
    Flags `except:` clauses that don't specify an exception type.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # `node.type` is the exception class being caught. When the user
        # writes a bare `except:`, this attribute is None. That's our signal.
        if node.type is None:
            self.findings.append(Finding(
                file_path=self.file_path,
                line=node.lineno,
                severity=Severity.WARNING,
                rule_id="bare-except",
                message=(
                    "Bare 'except:' clause catches all exceptions including "
                    "KeyboardInterrupt and SystemExit, and can hide bugs. "
                    "Catch a specific exception type, or use 'except Exception:' "
                    "if you really need to catch everything."
                ),
            ))

        # Continue visiting children so nested try/except blocks are checked.
        self.generic_visit(node)