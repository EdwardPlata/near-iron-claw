"""Fixtures for the Pipeline Creator API tests.

Everything is mocked: the LLM via ``NearAIClient`` + ``httpx.MockTransport``, and
the ingestion connectors via a second ``MockTransport``. The SSRF guard is patched
off so ``custom-http`` dry-runs don't perform real DNS. Shared builders live in
``helpers.py``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from near_iron_claw.pipeline import api as api_mod
from near_iron_claw.pipeline.store import InMemoryPipelineStore


@pytest.fixture
def build_client(monkeypatch):
    """Factory: returns (TestClient, store) with the given LLM + connector mocks."""
    # Custom-http dry-runs must not hit real DNS.
    monkeypatch.setattr("near_iron_claw.pipeline.connectors.assert_public_url", lambda url: None)

    def build(*, llm=None, http_handler=None, store=None):
        store = store or InMemoryPipelineStore()
        overrides = api_mod.app.dependency_overrides
        overrides[api_mod.get_store] = lambda: store
        if llm is not None:
            overrides[api_mod.get_nearai_client] = lambda: llm
        if http_handler is not None:
            overrides[api_mod.get_connector_http] = lambda: httpx.Client(
                transport=httpx.MockTransport(http_handler)
            )
        return TestClient(api_mod.app), store

    yield build
    api_mod.app.dependency_overrides.clear()
