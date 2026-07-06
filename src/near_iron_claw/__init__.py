"""near-iron-claw — a Python client + CLI for NEAR AI Cloud (hosted IronClaw).

NEAR AI Cloud is an OpenAI-compatible gateway at https://cloud-api.near.ai/v1.
See CONNECTING.md and SPEC.md for details.
"""

from __future__ import annotations

from .client import ChatMessage, NearAIClient, VerifyResult
from .config import Settings
from .errors import (
    APIConnectionError,
    APIError,
    APIResponseError,
    APIStatusError,
    AuthError,
    ConfigError,
    NearAIError,
    RateLimitError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "NearAIClient",
    "Settings",
    "ChatMessage",
    "VerifyResult",
    "NearAIError",
    "ConfigError",
    "APIError",
    "APIConnectionError",
    "APIResponseError",
    "APIStatusError",
    "AuthError",
    "RateLimitError",
]
