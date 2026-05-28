"""
Tests for the function length check.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_short_function_is_not_flagged():
    """A small function should pass cleanly."""
    source = """
def small():
    return 1
"""
    findings = CodeAnalyzer().analyze_source(source)
    length_findings = [f for f in findings if f.rule_id == "function-length"]
    assert length_findings == []


def test_long_function_is_flagged():
    """A function with more than 50 lines should be flagged."""
    # Build a function with 60 lines of `pass` statements.
    body = "\n".join("    pass" for _ in range(60))
    source = f"def long_func():\n{body}\n"

    findings = CodeAnalyzer().analyze_source(source)
    length_findings = [f for f in findings if f.rule_id == "function-length"]

    assert len(length_findings) == 1
    assert length_findings[0].severity == Severity.WARNING
    assert "long_func" in length_findings[0].message


def test_function_at_threshold_is_not_flagged():
    """A function exactly at 50 lines should NOT be flagged (we use strictly >)."""
    # 50 lines total: `def` line + 49 body lines = 50 lines.
    body = "\n".join("    pass" for _ in range(49))
    source = f"def borderline():\n{body}\n"

    findings = CodeAnalyzer().analyze_source(source)
    length_findings = [f for f in findings if f.rule_id == "function-length"]
    assert length_findings == []


def test_multiple_long_functions_each_flagged():
    """Each long function in a file should get its own finding."""
    body = "\n".join("    pass" for _ in range(60))
    source = f"def first():\n{body}\n\ndef second():\n{body}\n"

    findings = CodeAnalyzer().analyze_source(source)
    length_findings = [f for f in findings if f.rule_id == "function-length"]
    assert len(length_findings) == 2