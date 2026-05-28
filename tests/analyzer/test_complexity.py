"""
Tests for the cyclomatic complexity check.

Each test passes a short code snippet to the analyzer and asserts that
the right findings (or no findings) are produced. Using snippets as
strings is much faster than creating temp files and makes the tests
easy to read.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_simple_function_produces_no_finding():
    """A function with complexity 1 should pass cleanly."""
    source = """
def simple(x):
    return x + 1
"""
    findings = CodeAnalyzer().analyze_source(source)
    complexity_findings = [f for f in findings if f.rule_id == "complexity"]
    assert complexity_findings == []


def test_complex_function_produces_finding():
    """A function with complexity above the threshold should be flagged."""
    # Building 11 branch points: 1 base + 10 ifs = complexity 11.
    branches = "\n".join(f"    if x == {i}: pass" for i in range(10))
    source = f"def complex_func(x):\n{branches}\n    return x\n"

    findings = CodeAnalyzer().analyze_source(source)
    complexity_findings = [f for f in findings if f.rule_id == "complexity"]

    assert len(complexity_findings) == 1
    assert complexity_findings[0].severity == Severity.WARNING
    assert "complex_func" in complexity_findings[0].message


def test_function_at_threshold_is_not_flagged():
    """Functions exactly at the threshold should pass (we use strictly >)."""
    # 1 base + 9 ifs = complexity 10, exactly the threshold.
    branches = "\n".join(f"    if x == {i}: pass" for i in range(9))
    source = f"def borderline(x):\n{branches}\n    return x\n"

    findings = CodeAnalyzer().analyze_source(source)
    complexity_findings = [f for f in findings if f.rule_id == "complexity"]
    assert complexity_findings == []


def test_fixture_file_is_analyzed_correctly():
    """End-to-end test using the real fixture file on disk."""
    findings = CodeAnalyzer().analyze_file(
        "tests/fixtures/sample_code/complex_function.py"
    )
    complexity_findings = [f for f in findings if f.rule_id == "complexity"]

    # The fixture has one over-complex function (`process`) and one simple
    # one (`simple_function`). Only `process` should be flagged.
    assert len(complexity_findings) == 1
    assert "process" in complexity_findings[0].message


def test_boolean_operators_increase_complexity():
    """`and`/`or` chains should add to complexity."""
    # base 1 + one `if` (+1) + `a and b and c` adds 2 more = 4
    # That's well under the threshold, so it should NOT trigger.
    source = """
def uses_bool_ops(a, b, c):
    if a and b and c:
        return 1
    return 0
"""
    findings = CodeAnalyzer().analyze_source(source)
    assert [f for f in findings if f.rule_id == "complexity"] == []