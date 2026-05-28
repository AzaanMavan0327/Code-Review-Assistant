"""
Configuration loading.

Centralizes how the application reads its settings from the environment.
Secrets (like API tokens) live in a `.env` file that is never committed to
version control. This module loads that file and exposes the values through
simple, validated accessors.

Using a single config module (rather than scattering os.environ calls across
the codebase) means there's one obvious place to look when something is
misconfigured, and one place to add validation.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


# Load variables from a .env file into the environment, if one exists.
# This is called once at import time. In production (like a GitHub Action),
# there may be no .env file and the variables come from the real environment
# instead; load_dotenv simply does nothing in that case.
load_dotenv()


class ConfigError(Exception):
    """Raised when a required configuration value is missing."""
    pass


def get_github_token() -> str:
    """
    Return the GitHub personal access token.

    Reads the GITHUB_TOKEN environment variable. Raises a clear error if it's
    missing, so the user gets an actionable message instead of a confusing
    failure deep inside an API call later.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ConfigError(
            "GITHUB_TOKEN is not set. Create a .env file in the project root "
            "with the line: GITHUB_TOKEN=your_token_here\n"
            "You can generate a token at https://github.com/settings/tokens"
        )
    return token


def get_anthropic_api_key() -> str:
    """
    Return the Anthropic API key.

    Only needed in Phase 3 (LLM integration). Raises a clear error if it's
    missing so the failure is easy to diagnose.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file: "
            "ANTHROPIC_API_KEY=your_key_here\n"
            "You can generate a key at https://console.anthropic.com/settings/keys"
        )
    return key


def get_log_level() -> str:
    """
    Return the configured log level, defaulting to INFO.

    Unlike the secrets above, this is optional and has a sensible default,
    so it never raises.
    """
    return os.environ.get("LOG_LEVEL", "INFO").upper()