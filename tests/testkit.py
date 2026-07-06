"""Shared test builders (constants + mock helpers).

A plain module rather than conftest.py so it has a unique importable name (there
are two conftest.py files in this tree). pytest puts tests/ on sys.path, so test
modules use ``from testkit import MODELS_BODY, chat_response, mock_client``.
"""

from __future__ import annotations

from typing import Callable, Optional

import httpx

from near_iron_claw import NearAIClient, Settings

Handler = Callable[[httpx.Request], httpx.Response]

REAL_KEY = "sk-agent-realkey0000000000000000000000"

MODELS_BODY = {
    "data": [
        {"id": "openai/gpt-5.5"},
        {"id": "anthropic/claude-opus-4-7"},
        {"id": "deepseek/deepseek-v3.2"},
    ]
}


def chat_response(content: str) -> dict:
    """Minimal OpenAI-shaped chat completion response body."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def mock_client(handler: Handler, *, key: Optional[str] = REAL_KEY) -> NearAIClient:
    """A NearAIClient wired to a MockTransport handler (no fixtures needed)."""
    return NearAIClient(Settings(api_key=key), transport=httpx.MockTransport(handler))
