"""Tests for NearAIClient against a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from near_iron_claw import (
    APIConnectionError,
    APIResponseError,
    APIStatusError,
    AuthError,
    NearAIClient,
    RateLimitError,
    Settings,
)

MODELS_BODY = {
    "data": [
        {"id": "openai/gpt-5.5"},
        {"id": "anthropic/claude-opus-4-7"},
        {"id": "deepseek/deepseek-v3.2"},
    ]
}


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_list_models_sorted(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=MODELS_BODY)

    client = make_client(handler)
    assert client.list_models() == [
        "anthropic/claude-opus-4-7",
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.5",
    ]


def test_chat_sends_auth_and_payload(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_chat_response("pong"))

    client = make_client(handler)
    reply = client.chat(
        [{"role": "user", "content": "ping"}], max_tokens=16, temperature=0.2
    )
    assert reply == "pong"
    assert seen["auth"] == "Bearer sk-agent-testkey0000000000000000000000"
    assert seen["body"]["max_tokens"] == 16
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["stream"] is False


def test_chat_uses_default_model_and_override(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read())["model"] == "openai/gpt-5.5"
        return httpx.Response(200, json=_chat_response("ok"))

    client = make_client(handler)
    assert client.chat([{"role": "user", "content": "x"}], model="openai/gpt-5.5") == "ok"


def test_auth_error_raised_on_401(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "invalid_api_key"}})

    client = make_client(handler)
    with pytest.raises(AuthError) as exc:
        client.chat([{"role": "user", "content": "hi"}])
    assert exc.value.status_code == 401


def test_generic_status_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    with pytest.raises(APIStatusError) as exc:
        make_client(handler).chat([{"role": "user", "content": "hi"}])
    assert exc.value.status_code == 400
    assert exc.value.body == "bad request"


def test_rate_limit_retried_then_succeeds(make_client):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=_chat_response("recovered"))

    # max_retries=1 in the fixture settings -> 2 attempts total.
    client = make_client(handler)
    assert client.chat([{"role": "user", "content": "hi"}]) == "recovered"
    assert calls["n"] == 2


def test_rate_limit_exhausted_raises(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    with pytest.raises(RateLimitError):
        make_client(handler).chat([{"role": "user", "content": "hi"}])


def test_connection_error_wrapped(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(APIConnectionError):
        make_client(handler).list_models()


def test_stream_chat_yields_deltas(make_client):
    sse = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read())["stream"] is True
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    client = make_client(handler)
    pieces = list(client.stream_chat([{"role": "user", "content": "hi"}]))
    assert "".join(pieces) == "Hello"


def test_context_manager_closes():
    client = NearAIClient(
        Settings(api_key="sk-agent-realkey0000000000000000"),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MODELS_BODY)),
    )
    with client as c:
        assert c.list_models()


def test_post_5xx_not_retried_no_duplicate_billing(make_client):
    # POST is non-idempotent: a 5xx must NOT be retried (would re-bill a completion).
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    with pytest.raises(APIStatusError):
        make_client(handler).chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1  # sent exactly once, no retry


def test_get_5xx_is_retried(make_client):
    # GET /models is idempotent, so a transient 5xx is safe to retry.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=MODELS_BODY)

    assert make_client(handler).list_models()
    assert calls["n"] == 2


def test_non_json_body_raises_api_response_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(APIResponseError):
        make_client(handler).list_models()


def test_chat_malformed_shape_raises_api_response_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})  # empty choices

    with pytest.raises(APIResponseError):
        make_client(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_null_content_raises_api_response_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    with pytest.raises(APIResponseError):
        make_client(handler).chat([{"role": "user", "content": "hi"}])


def test_stream_error_status_raises_typed_error_not_response_not_read(make_client):
    # Regression: an error status on a streaming request must surface AuthError,
    # not a raw httpx.ResponseNotRead from reading an unread streaming body.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid key")

    client = make_client(handler)
    with pytest.raises(AuthError):
        list(client.stream_chat([{"role": "user", "content": "hi"}]))
