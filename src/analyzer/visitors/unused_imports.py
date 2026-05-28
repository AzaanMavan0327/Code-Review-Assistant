"""
Unused imports check.

Catches imports that are never used in the file:

    import json          # used below
    import os            # NEVER USED  <- flagged
    from typing import List, Dict   # Dict NEVER USED  <- flagged

    data = json.loads(text)
    result: List[int] = []

Unused imports are dead weight: they slow startup, clutter the namespace,
and confuse readers who wonder why something was imported.

Implementation strategy:
  1. First pass: collect every name imported in the file.
  2. Second pass: collect every name referenced anywhere in the file.
  3. Any imported name that wasn't referenced is unused.

This two-pass approach is needed because an import on line 1 might be
used much later in the file. We can't know if an import is unused until
we've seen the whole file.
"""

import ast
from typing import Dict, List, Set

from src.analyzer.base import Finding, Severity


class UnusedImportsVisitor(ast.NodeVisitor):
    """
    Detects imports whose names are never referenced in the file.

    Handles these import forms:
        import x              -> name "x" is added
        import x as y         -> name "y" is added (x is not visible)
        from m import a, b    -> names "a" and "b" are added
        from m import a as c  -> name "c" is added (a is not visible)
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.findings: List[Finding] = []

        # Maps each imported name to the AST node where it was imported.
        # We need the node to get the line number for the finding.
        self._imports: Dict[str, ast.AST] = {}

        # Every name that's actually referenced somewhere in the file.
        self._used_names: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        """Handle `import x` and `import x as y`."""
        for alias in node.names:
            # `alias.asname` is the "as" name; falls back to the real name.
            # For `import os.path`, we only care about the top-level name "os".
            name = alias.asname or alias.name.split(".")[0]
            self._imports[name] = node
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Handle `from module import x` and `from module import x as y`."""
        for alias in node.names:
            # Skip `from x import *`; we can't tell what names it brought in
            # without resolving the module, which is too much work for now.
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self._imports[name] = node
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Record every variable/name reference."""
        # `ast.Load` means the name is being read (used).
        # `ast.Store` would mean it's being assigned to.
        # We only care about reads, since that's what makes an import "used".
        if isinstance(node.ctx, ast.Load):
            self._used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Record attribute accesses like `os.path` or `json.loads`."""
        # For `os.path.join`, we need to find the base name "os" and mark
        # it as used. We walk down the attribute chain to find the root Name.
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name):
            self._used_names.add(current.id)
        self.generic_visit(node)

    def finalize(self) -> None:
        """
        Compare imports against used names and emit findings.

        Must be called after `visit()` has run on the whole tree, because
        we can't know an import is unused until we've scanned everything.
        """
        for name, node in self._imports.items():
            if name not in self._used_names:
                self.findings.append(Finding(
                    file_path=self.file_path,
                    line=node.lineno,
                    severity=Severity.INFO,
                    rule_id="unused-import",
                    message=(
                        f"Imported name '{name}' is never used. "
                        f"Remove the import to keep the file clean."
                    ),
                ))