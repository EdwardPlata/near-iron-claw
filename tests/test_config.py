"""Tests for the config/settings loader."""

from __future__ import annotations

import pytest

from near_iron_claw import ConfigError, Settings
from near_iron_claw.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    looks_like_placeholder,
    redact,
)


def test_defaults_when_env_empty():
    s = Settings.load(env={}, use_dotenv=False)
    assert s.base_url == DEFAULT_BASE_URL
    assert s.model == DEFAULT_MODEL
    assert s.api_key is None
    assert s.has_key is False


def test_llm_vars_take_priority_over_openai_aliases():
    env = {
        "LLM_BASE_URL": "https://primary/v1/",
        "OPENAI_BASE_URL": "https://alias/v1",
        "LLM_API_KEY": "sk-agent-realkey000000000000000000",
        "LLM_MODEL": "openai/gpt-5.5",
    }
    s = Settings.load(env=env, use_dotenv=False)
    assert s.base_url == "https://primary/v1"  # trailing slash stripped
    assert s.model == "openai/gpt-5.5"
    assert s.has_key is True


def test_openai_and_near_aliases_used_as_fallback():
    env = {"OPENAI_API_KEY": "sk-agent-fromopenai0000000000000000"}
    assert Settings.load(env=env, use_dotenv=False).has_key
    env = {"NEAR_AI_API_KEY": "sk-agent-fromnear00000000000000000000"}
    assert Settings.load(env=env, use_dotenv=False).has_key


def test_require_key_raises_on_placeholder():
    s = Settings.load(env={"LLM_API_KEY": "sk-agent-xxxxxxxxxxxxxxxx"}, use_dotenv=False)
    assert s.has_key is False
    with pytest.raises(ConfigError):
        s.require_key()


def test_require_key_returns_real_key():
    key = "sk-agent-5f854cf322214777a985d4c63b9cd88a"
    s = Settings.load(env={"LLM_API_KEY": key}, use_dotenv=False)
    assert s.require_key() == key


def test_numeric_env_parsing_and_bad_values():
    s = Settings.load(env={"LLM_TIMEOUT": "12.5", "LLM_MAX_RETRIES": "4"}, use_dotenv=False)
    assert s.timeout == 12.5
    assert s.max_retries == 4
    bad = Settings.load(env={"LLM_TIMEOUT": "nope"}, use_dotenv=False)
    assert bad.timeout == 60.0


@pytest.mark.parametrize(
    "key,placeholder",
    [
        (None, True),
        ("", True),
        ("sk-agent-xxxxxxxxxxxx", True),
        ("your-key-here", True),
        ("sk-agent-realvalue000000000", False),
    ],
)
def test_looks_like_placeholder(key, placeholder):
    assert looks_like_placeholder(key) is placeholder


def test_redact_hides_secret_and_repr_never_leaks():
    key = "sk-agent-5f854cf322214777a985d4c63b9cd88a"
    red = redact(key)
    assert key not in red
    assert red.startswith("sk-agent-")
    assert "5f854cf3" not in redact(key)
    s = Settings(api_key=key)
    assert key not in repr(s)
    assert key not in str(s.redacted())


def test_redact_unset():
    assert redact(None) == "<unset>"
    assert redact("") == "<unset>"


def test_redact_fully_masks_short_secret():
    # A short/misconfigured key must not leak any raw characters.
    assert redact("abc") == "…"
    assert redact("shortkey") == "…"
    assert "abc" not in redact("abc")


def test_negative_max_retries_floored_to_zero():
    s = Settings.load(env={"LLM_MAX_RETRIES": "-3"}, use_dotenv=False)
    assert s.max_retries == 0
