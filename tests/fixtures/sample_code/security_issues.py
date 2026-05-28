"""
Test fixture with security issues.

Intentional issues for the analyzer to detect.
"""

import os


# Hardcoded secret: should be flagged
api_key = "sk-1234567890abcdef"

# Safe: loaded from environment
api_secret = os.environ.get("API_SECRET", "")

# Hardcoded secret with type annotation: should be flagged
password: str = "supersecret123"

# Safe: placeholder value, should NOT be flagged
default_token = "your_token_here"


def execute_user_code(code_string):
    # Dangerous: should be flagged
    result = eval(code_string)
    return result


def run_dynamic(snippet):
    # Dangerous: should be flagged
    exec(snippet)