"""
Tests for the bare except clause check.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_bare_except_is_flagged():
    """A bare `except:` should produce a finding."""
    source = """
def risky():
    try:
        do_thing()
    except:
        pass
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]

    assert len(bare) == 1
    assert bare[0].severity == Severity.WARNING


def test_specific_except_is_safe():
    """`except ValueError:` is fine and should NOT be flagged."""
    source = """
def safe():
    try:
        do_thing()
    except ValueError:
        pass
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]
    assert bare == []


def test_except_exception_is_safe():
    """`except Exception:` is acceptable, should NOT be flagged."""
    source = """
def acceptable():
    try:
        do_thing()
    except Exception:
        pass
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]
    assert bare == []


def test_except_with_alias_is_safe():
    """`except ValueError as e:` should NOT be flagged."""
    source = """
def with_alias():
    try:
        do_thing()
    except ValueError as e:
        print(e)
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]
    assert bare == []


def test_multiple_bare_excepts_each_flagged():
    """Each bare except in a file should get its own finding."""
    source = """
def first():
    try:
        a()
    except:
        pass

def second():
    try:
        b()
    except:
        pass
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]
    assert len(bare) == 2


def test_tuple_except_is_safe():
    """`except (ValueError, TypeError):` should NOT be flagged."""
    source = """
def multi():
    try:
        do_thing()
    except (ValueError, TypeError):
        pass
"""
    findings = CodeAnalyzer().analyze_source(source)
    bare = [f for f in findings if f.rule_id == "bare-except"]
    assert bare == []