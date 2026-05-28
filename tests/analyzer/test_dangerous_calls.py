"""
Tests for the dangerous calls check.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_eval_call_is_flagged():
    """`eval(x)` should produce an error finding."""
    source = 'result = eval("1 + 1")\n'
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]

    assert len(dangerous) == 1
    assert dangerous[0].severity == Severity.ERROR
    assert "eval" in dangerous[0].message


def test_exec_call_is_flagged():
    """`exec(x)` should produce an error finding."""
    source = 'exec("print(\'hello\')")\n'
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]
    assert len(dangerous) == 1
    assert "exec" in dangerous[0].message


def test_safe_calls_are_not_flagged():
    """Normal function calls should NOT be flagged."""
    source = """
print("hello")
result = sum([1, 2, 3])
data = json.loads("{}")
"""
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]
    assert dangerous == []


def test_attribute_eval_is_not_flagged():
    """`obj.eval(x)` should NOT be flagged (it's not the built-in eval)."""
    source = """
model.eval()
self.eval()
"""
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]
    assert dangerous == []


def test_multiple_dangerous_calls_each_flagged():
    """Each call in a file should get its own finding."""
    source = """
a = eval("1+1")
b = exec("x = 2")
c = eval("3+3")
"""
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]
    assert len(dangerous) == 3


def test_dangerous_call_in_nested_context():
    """Dangerous calls inside functions/loops should also be flagged."""
    source = """
def process(items):
    for item in items:
        result = eval(item)
        print(result)
"""
    findings = CodeAnalyzer().analyze_source(source)
    dangerous = [f for f in findings if f.rule_id == "dangerous-call"]
    assert len(dangerous) == 1