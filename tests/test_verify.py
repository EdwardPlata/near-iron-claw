"""Tests for the verify() health-check and its separation of concerns.

Key validity is proven via /chat/completions (not /models), matching the
guidance in CONNECTING.md that a public /models 200 does not prove the key.
"""

from __future__ import annotations

import httpx

from testkit import MODELS_BODY, chat_response
from testkit import mock_client as _client

CHAT_OK = chat_response("pong")

MODEL_COUNT = len(MODELS_BODY["data"])


def _route(request: httpx.Request) -> httpx.Response:
    """Healthy gateway: /models lists models, /chat/completions succeeds."""
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json=CHAT_OK)
    return httpx.Response(200, json=MODELS_BODY)


def test_verify_ok_when_key_valid():
    result = _client(_route).verify()
    assert result.ok is True
    assert result.gateway_reachable is True
    assert result.key_valid is True
    assert result.model_count == MODEL_COUNT


def test_verify_reachable_but_key_invalid():
    def handler(request: httpx.Request) -> httpx.Response:
        # /models is fine (key lists models), but chat rejects the key — the
        # exact false-positive CONNECTING.md warns about.
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(401, text="invalid key")
        return httpx.Response(200, json=MODELS_BODY)

    result = _client(handler).verify()
    assert result.gateway_reachable is True
    assert result.key_valid is False
    assert result.ok is False
    assert result.model_count == MODEL_COUNT  # still reported informationally
    assert result.errors


def test_verify_no_key_configured_only_checks_reachability():
    result = _client(_route, key=None).verify()
    assert result.gateway_reachable is True
    assert result.key_valid is None
    assert result.ok is False
    assert "no API key" in result.detail


def test_verify_gateway_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    result = _client(handler).verify()
    assert result.gateway_reachable is False
    assert result.key_valid is None
    assert result.ok is False


def test_verify_inconclusive_on_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(400, text="bad model")
        return httpx.Response(200, json=MODELS_BODY)

    result = _client(handler).verify()
    assert result.gateway_reachable is True
    assert result.key_valid is None
    assert "inconclusive" in result.detail


def test_verify_4xx_on_models_is_not_reachable():
    # A 404 on /models means a wrong base URL/path — not a healthy gateway.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    result = _client(handler).verify()
    assert result.gateway_reachable is False
    assert result.ok is False
    assert result.errors


def test_verify_to_dict_serializable():
    import json

    result = _client(_route).verify()
    assert json.loads(json.dumps(result.to_dict()))["ok"] is True
