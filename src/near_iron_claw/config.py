"""Configuration loading for near-iron-claw.

Resolves the NEAR AI Cloud connection settings from a ``.env`` file and/or the
process environment, applying the OpenAI-SDK and NEAR-native aliases documented in
``CONNECTING.md``. Secrets are never rendered in full — use :meth:`Settings.redacted`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ConfigError

DEFAULT_BASE_URL = "https://cloud-api.near.ai/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

# Substrings that indicate a placeholder rather than a real key.
_PLACEHOLDER_MARKERS = ("xxxx", "your-key", "changeme", "replace")


def _first_env(env: Mapping[str, str], *names: str) -> str | None:
    """Return the first non-empty value among ``names`` in ``env``."""
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def redact(secret: str | None) -> str:
    """Return a display-safe version of a secret, revealing only a short prefix.

    ``sk-agent-5f854cf3...`` -> ``sk-agent-…88a`` style, never the full value.
    Short/misconfigured secrets are masked entirely so no raw characters leak.
    """
    if not secret:
        return "<unset>"
    if len(secret) <= 12:
        return "…"  # fully mask — revealing any chars of a short key leaks too much
    return f"{secret[:9]}…{secret[-3:]}"


def looks_like_placeholder(key: str | None) -> bool:
    """True if ``key`` is empty or an obvious placeholder from ``.env.example``."""
    if not key:
        return True
    lowered = key.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Settings:
    """Resolved connection settings.

    Attributes:
        base_url: Gateway base URL, e.g. ``https://cloud-api.near.ai/v1``.
        api_key: Bearer token (``sk-agent-…``); ``None`` if unset.
        model: Default model slug for chat completions.
        timeout: Per-request timeout in seconds.
        max_retries: Retry attempts for transient failures.
    """

    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    max_retries: int = 2

    @classmethod
    def load(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        dotenv_path: str | None = None,
        use_dotenv: bool = True,
    ) -> Settings:
        """Load settings from ``.env`` (if present) merged with the environment.

        Real environment variables take precedence over ``.env`` file values.
        """
        merged: dict[str, str] = {}
        if use_dotenv and env is None:
            try:
                from dotenv import dotenv_values

                merged.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
            except ImportError:  # pragma: no cover - python-dotenv is a declared dep
                pass
        source = env if env is not None else os.environ
        merged.update({k: v for k, v in source.items() if v is not None})

        base_url = _first_env(merged, "LLM_BASE_URL", "OPENAI_BASE_URL") or DEFAULT_BASE_URL
        api_key = _first_env(merged, "LLM_API_KEY", "OPENAI_API_KEY", "NEAR_AI_API_KEY")
        model = _first_env(merged, "LLM_MODEL", "OPENAI_MODEL") or DEFAULT_MODEL

        timeout = _as_float(_first_env(merged, "LLM_TIMEOUT"), 60.0)
        # Floor at 0 — a negative value would zero out the attempt loop entirely.
        max_retries = max(0, int(_as_float(_first_env(merged, "LLM_MAX_RETRIES"), 2.0)))

        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
        )

    def require_key(self) -> str:
        """Return the API key or raise :class:`ConfigError` if missing/placeholder."""
        if looks_like_placeholder(self.api_key):
            raise ConfigError(
                "No valid API key. Set LLM_API_KEY (or OPENAI_API_KEY / NEAR_AI_API_KEY) "
                "in .env to a real sk-agent-… key from https://cloud.near.ai."
            )
        assert self.api_key is not None  # narrowed by looks_like_placeholder
        return self.api_key

    @property
    def has_key(self) -> bool:
        """True if a non-placeholder key is configured."""
        return not looks_like_placeholder(self.api_key)

    def redacted(self) -> dict[str, object]:
        """A dict view of the settings safe for printing/logging."""
        return {
            "base_url": self.base_url,
            "api_key": redact(self.api_key),
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "has_valid_key": self.has_key,
        }

    def __repr__(self) -> str:  # never leak the key
        return (
            f"Settings(base_url={self.base_url!r}, api_key={redact(self.api_key)!r}, "
            f"model={self.model!r}, timeout={self.timeout!r}, max_retries={self.max_retries!r})"
        )


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
