"""Optional live smoke test against the real NEAR AI Cloud gateway.

Skipped automatically unless a valid (non-placeholder) key is configured via
.env / environment. Run explicitly with:  pytest -m live
"""

from __future__ import annotations

import pytest

from near_iron_claw import NearAIClient, Settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_client():
    settings = Settings.load()
    if not settings.has_key:
        pytest.skip("no valid API key configured; set LLM_API_KEY in .env to run live tests")
    return NearAIClient(settings)


def test_live_verify(live_client):
    result = live_client.verify()
    assert result.gateway_reachable is True
    # If the committed key is expired this asserts a helpful failure rather than a crash.
    assert result.key_valid is True, f"key invalid: {result.errors}"


def test_live_chat_roundtrip(live_client):
    reply = live_client.chat(
        [{"role": "user", "content": "Reply with the single word: pong"}],
        max_tokens=8,
    )
    assert isinstance(reply, str) and reply.strip()
