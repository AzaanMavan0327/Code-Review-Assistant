"""
Tests for the mutable default arguments check.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_list_default_is_flagged():
    """`def f(x=[])` should produce an error finding."""
    source = "def f(x=[]):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]

    assert len(mutable) == 1
    assert mutable[0].severity == Severity.ERROR
    assert "'f'" in mutable[0].message


def test_dict_default_is_flagged():
    """`def f(x={})` should produce an error finding."""
    source = "def f(x={}):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert len(mutable) == 1


def test_set_literal_default_is_flagged():
    """`def f(x={1, 2})` should produce an error finding."""
    source = "def f(x={1, 2}):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert len(mutable) == 1


def test_list_constructor_default_is_flagged():
    """`def f(x=list())` is just as bad as `def f(x=[])`."""
    source = "def f(x=list()):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert len(mutable) == 1


def test_none_default_is_safe():
    """`def f(x=None)` is the correct pattern, should NOT be flagged."""
    source = "def f(x=None):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert mutable == []


def test_tuple_default_is_safe():
    """Tuples are immutable, so they're safe as defaults."""
    source = "def f(x=(1, 2, 3)):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert mutable == []


def test_int_default_is_safe():
    """Numbers and other immutables should NOT be flagged."""
    source = "def f(x=42):\n    return x\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert mutable == []


def test_fixture_file_finds_three_bugs():
    """The fixture has 3 buggy functions and 2 safe ones."""
    findings = CodeAnalyzer().analyze_file(
        "tests/fixtures/sample_code/mutable_default.py"
    )
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert len(mutable) == 3


def test_keyword_only_mutable_default_is_flagged():
    """Mutable defaults on keyword-only args should also be caught."""
    # The `*` makes everything after it keyword-only.
    source = "def f(*, items=[]):\n    return items\n"
    findings = CodeAnalyzer().analyze_source(source)
    mutable = [f for f in findings if f.rule_id == "mutable-default"]
    assert len(mutable) == 1