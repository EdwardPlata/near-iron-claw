"""Exception hierarchy for near-iron-claw.

All errors raised by the library derive from :class:`NearAIError`, so callers can
catch everything with a single ``except NearAIError``.
"""

from __future__ import annotations


class NearAIError(Exception):
    """Base class for all near-iron-claw errors."""


class ConfigError(NearAIError):
    """Configuration is missing or invalid (e.g. no/placeholder API key)."""


class APIError(NearAIError):
    """Base class for errors returned by, or while contacting, the gateway."""


class APIConnectionError(APIError):
    """The gateway could not be reached (DNS, TLS, timeout, connection refused)."""


class APIResponseError(APIError):
    """A 2xx response could not be parsed into the expected shape (non-JSON body,
    missing ``choices``, null content, etc.)."""


class APIStatusError(APIError):
    """The gateway returned a non-2xx HTTP status.

    Attributes:
        status_code: The HTTP status code.
        body: The raw (truncated) response body, useful for debugging.
    """

    def __init__(self, message: str, *, status_code: int, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AuthError(APIStatusError):
    """Authentication failed — the API key is missing, invalid, or expired (401/403)."""


class RateLimitError(APIStatusError):
    """The gateway rate-limited the request (429)."""
