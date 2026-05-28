"""
Core data types shared across the analyzer.

A `Finding` represents a single issue detected in source code. Every visitor
(complexity check, mutable default check, etc.) produces a list of these.
Keeping the data structure small and stable means we can add new checks
without changing the rest of the system.
"""

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """
    How serious a finding is.

    Inheriting from `str` (in addition to `Enum`) means the values serialize
    cleanly to JSON later, when we send findings to the LLM.
    """
    INFO = "info"          # Style suggestions; safe to ignore
    WARNING = "warning"    # Likely problems worth fixing
    ERROR = "error"        # Bugs or security issues; should be fixed


@dataclass(frozen=True)
class Finding:
    """
    One issue detected in source code.

    Marked `frozen=True` so instances are immutable and hashable. Immutability
    prevents accidental mutation after a finding is created, and hashability
    lets us deduplicate findings using a set if needed.

    Attributes:
        file_path: Path to the file the issue was found in.
        line: 1-indexed line number (matches what editors and GitHub show).
        severity: How serious the issue is.
        rule_id: Short identifier like "complexity" or "mutable-default".
                 Used for filtering and for the LLM to reference.
        message: Human-readable description of the issue.
    """
    file_path: str
    line: int
    severity: Severity
    rule_id: str
    message: str

    def format_console(self) -> str:
        """Format this finding for terminal output."""
        return (
            f"{self.file_path}:{self.line}:"
            f"{self.severity.value.upper()}:"
            f"{self.rule_id} - {self.message}"
        )