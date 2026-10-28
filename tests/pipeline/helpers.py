"""Shared test helpers for the Pipeline Creator API tests.

Imported as a plain module (pytest puts this directory on sys.path), so tests use
``from helpers import ...`` rather than a package-relative import.
"""

from __future__ import annotations

import httpx

from near_iron_claw import NearAIClient, Settings

REAL_KEY = "sk-agent-realkey0000000000000000000000"

# A minimal, valid PipelineSpec the mocked LLM "returns" as chat content.
VALID_SPEC = {
    "spec_version": "1.0",
    "name": "designed-pipeline",
    "description": "designed by the (mocked) LLM",
    "goal": "OVERWRITTEN_BY_SERVER",
    "source": {"type": "OVERWRITTEN", "actor_id": "OVERWRITTEN"},
    "steps": [
        {"phase": "extract", "order": 1, "name": "extract"},
        {"phase": "transform", "order": 2, "name": "clean",
         "ops": [{"op": "limit", "count": 5}, {"op": "dedupe", "fields": ["id"]}]},
        {"phase": "load", "order": 3, "name": "load"},
    ],
    "load": {"destination": "return", "format": "json"},
    "tags": ["scrape"],
}


def llm_returning(content: str) -> NearAIClient:
    """A NearAIClient whose chat() returns ``content`` as the assistant message."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return NearAIClient(Settings(api_key=REAL_KEY), transport=httpx.MockTransport(handler))


def llm_status(status: int) -> NearAIClient:
    """A NearAIClient whose chat() upstream returns an error status (e.g. 401)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="nope")
    return NearAIClient(Settings(api_key=REAL_KEY), transport=httpx.MockTransport(handler))


def llm_valid() -> NearAIClient:
    import json

    return llm_returning(json.dumps(VALID_SPEC))
