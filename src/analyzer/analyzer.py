"""
Main analyzer orchestrator.

The `CodeAnalyzer` is the public entry point for analyzing source code.
It parses a file into an AST once, then runs every registered visitor
against that same AST. Parsing once and reusing the tree is more efficient
than re-parsing for each check.
"""

import ast
from pathlib import Path
from typing import List

from src.analyzer.base import Finding
from src.analyzer.visitors.complexity import ComplexityVisitor
from src.analyzer.visitors.mutable_defaults import MutableDefaultsVisitor
from src.analyzer.visitors.bare_except import BareExceptVisitor
from src.analyzer.visitors.unused_imports import UnusedImportsVisitor
from src.analyzer.visitors.function_length import FunctionLengthVisitor
from src.analyzer.visitors.hardcoded_secrets import HardcodedSecretsVisitor
from src.analyzer.visitors.dangerous_calls import DangerousCallsVisitor


class CodeAnalyzer:
    """
    Analyzes a Python source file and returns a list of findings.

    Usage:
        analyzer = CodeAnalyzer()
        findings = analyzer.analyze_file("path/to/file.py")
        for finding in findings:
            print(finding.format_console())
    """

    def analyze_file(self, file_path: str) -> List[Finding]:
        """
        Analyze a single Python file on disk.

        Args:
            file_path: Path to a .py file.

        Returns:
            All findings detected by all registered visitors. Empty list
            means no issues were found.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            SyntaxError: If the file isn't valid Python.
        """
        source = Path(file_path).read_text(encoding="utf-8")
        return self.analyze_source(source, file_path)

    def analyze_source(self, source: str, file_path: str = "<string>") -> List[Finding]:
        """
        Analyze source code provided as a string.

        Separating this from `analyze_file` makes testing easier: tests
        can pass code snippets directly without creating temp files.
        """
        tree = ast.parse(source, filename=file_path)

        # Each visitor is independent. Adding a new check later just means
        # appending a new visitor to this list. This is the open/closed
        # principle in action: open for extension, closed for modification.
        visitors = [
            ComplexityVisitor(file_path),
            MutableDefaultsVisitor(file_path),
            BareExceptVisitor(file_path),
            UnusedImportsVisitor(file_path),
            FunctionLengthVisitor(file_path),
            HardcodedSecretsVisitor(file_path),
            DangerousCallsVisitor(file_path),
        ]

        all_findings: List[Finding] = []
        for visitor in visitors:
            visitor.visit(tree)

            # Some visitors (like UnusedImportsVisitor) need a finalize step
            # after the full tree has been walked, because they can only
            # produce findings once they've seen everything. We call
            # `finalize()` on any visitor that defines it.
            if hasattr(visitor, "finalize"):
                visitor.finalize()

            all_findings.extend(visitor.findings)

        # Sort findings by line number so the output is predictable and
        # easy to read top-to-bottom.
        all_findings.sort(key=lambda f: f.line)
        return all_findings