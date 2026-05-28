"""
Tests for the hardcoded secrets check.
"""

from src.analyzer.analyzer import CodeAnalyzer
from src.analyzer.base import Severity


def test_api_key_literal_is_flagged():
    """`api_key = "sk-abc123..."` should be flagged as a secret."""
    source = 'api_key = "sk-abc123def456ghi789"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]

    assert len(secrets) == 1
    assert secrets[0].severity == Severity.ERROR
    assert "api_key" in secrets[0].message


def test_password_literal_is_flagged():
    """`password = "hunter2longenough"` should be flagged."""
    source = 'password = "hunter2longenough"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert len(secrets) == 1


def test_uppercase_constant_is_flagged():
    """`API_KEY = "..."` (uppercase) should also be flagged."""
    source = 'API_KEY = "sk-abc123def456"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert len(secrets) == 1


def test_typed_assignment_is_flagged():
    """`api_key: str = "..."` (with type annotation) should be flagged."""
    source = 'api_key: str = "sk-abc123def456"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert len(secrets) == 1


def test_env_var_lookup_is_safe():
    """Loading from env vars should NOT be flagged."""
    source = """
import os
api_key = os.environ["API_KEY"]
"""
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secrets == []


def test_function_call_is_safe():
    """Assignments from function calls should NOT be flagged."""
    source = 'api_key = get_api_key()\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secrets == []


def test_placeholder_value_is_ignored():
    """Obvious placeholder values should NOT be flagged."""
    source = 'api_key = "your_key_here"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secrets == []


def test_short_value_is_ignored():
    """Strings shorter than the minimum length should NOT be flagged."""
    # 5 chars, below the threshold of 8
    source = 'password = "abcde"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secrets == []


def test_non_secret_variable_name_is_safe():
    """Strings assigned to non-secret-looking names should NOT be flagged."""
    source = 'greeting = "Hello, world! This is a long message."\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert secrets == []


def test_token_variable_is_flagged():
    """Variables containing 'token' should be flagged."""
    source = 'auth_token = "abcdef1234567890"\n'
    findings = CodeAnalyzer().analyze_source(source)
    secrets = [f for f in findings if f.rule_id == "hardcoded-secret"]
    assert len(secrets) == 1