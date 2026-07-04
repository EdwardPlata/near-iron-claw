"""Synchronous client for the NEAR AI Cloud (hosted IronClaw) gateway.

The gateway is OpenAI-compatible, so this is a thin, dependency-light wrapper over
``httpx`` exposing the handful of endpoints this project needs: listing models,
chat completions (blocking + streaming), and a health check.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .errors import (
    APIConnectionError,
    APIError,
    APIResponseError,
    APIStatusError,
    AuthError,
    RateLimitError,
)

__all__ = ["NearAIClient", "ChatMessage", "VerifyResult"]

# A chat message is the OpenAI shape: {"role": ..., "content": ...}.
ChatMessage = Mapping[str, str]

# 429 (rate limited) is safe to retry for any method — the request was rejected,
# not processed. 5xx may mean the completion was already generated and billed, so
# it is only retried for idempotent (GET/HEAD) methods to avoid duplicate work.
_RETRY_ANY_METHOD = {429}
_RETRY_IDEMPOTENT_ONLY = {500, 502, 503, 504}
_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class VerifyResult:
    """Outcome of :meth:`NearAIClient.verify`.

    ``gateway_reachable`` can be true while ``key_valid`` is false — mirroring the
    guidance in CONNECTING.md that a public ``/models`` 200 does not prove the key.
    """

    gateway_reachable: bool
    key_valid: bool | None  # None = not checked (no key configured)
    model_count: int | None = None
    detail: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.gateway_reachable and self.key_valid is True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "gateway_reachable": self.gateway_reachable,
            "key_valid": self.key_valid,
            "model_count": self.model_count,
            "detail": self.detail,
            "errors": self.errors,
        }


class NearAIClient:
    """Client for the NEAR AI Cloud OpenAI-compatible gateway.

    Example::

        from near_iron_claw import NearAIClient, Settings

        client = NearAIClient(Settings.load())
        print(client.chat([{"role": "user", "content": "ping"}]))
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        # ``transport`` is the injection point tests use (httpx.MockTransport).
        self._http = httpx.Client(
            base_url=self.settings.base_url,
            timeout=self.settings.timeout,
            transport=transport,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> NearAIClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internal helpers --------------------------------------------------

    def _headers(self, *, auth: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.settings.require_key()}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        # For streaming responses the body has not been read yet; accessing
        # ``.text`` would raise httpx.ResponseNotRead, so read it first.
        try:
            body = response.text[:500]
        except httpx.ResponseNotRead:
            response.read()
            body = response.text[:500]
        message = f"{response.request.method} {response.request.url} -> HTTP {response.status_code}"
        if response.status_code in (401, 403):
            raise AuthError(
                f"{message}: authentication failed (invalid or expired API key). "
                "Get a fresh key at https://cloud.near.ai.",
                status_code=response.status_code,
                body=body,
            )
        if response.status_code == 429:
            raise RateLimitError(message, status_code=response.status_code, body=body)
        raise APIStatusError(message, status_code=response.status_code, body=body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json_body: Mapping[str, Any] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        """Send a request with bounded retries on transient failures."""
        last_exc: Exception | None = None
        attempts = self.settings.max_retries + 1
        for attempt in range(attempts):
            try:
                request = self._http.build_request(
                    method,
                    path,
                    headers=self._headers(auth=auth),
                    json=json_body,
                )
                response = self._http.send(request, stream=stream)
            except httpx.HTTPError as exc:
                last_exc = APIConnectionError(f"Could not reach gateway at {self.settings.base_url}: {exc}")
                if attempt < attempts - 1:
                    time.sleep(_backoff(attempt))
                    continue
                raise last_exc from exc

            retryable = response.status_code in _RETRY_ANY_METHOD or (
                method.upper() in _IDEMPOTENT_METHODS
                and response.status_code in _RETRY_IDEMPOTENT_ONLY
            )
            if retryable and attempt < attempts - 1:
                if stream:
                    response.close()
                time.sleep(_backoff(attempt))
                continue
            return response
        # Unreachable, but keeps type-checkers happy.
        raise last_exc or APIConnectionError("request failed")

    # -- public API --------------------------------------------------------

    def list_models(self) -> list[str]:
        """Return the sorted list of model ids exposed by the gateway (``GET /models``)."""
        response = self._request("GET", "/models", auth=self.settings.has_key)
        self._raise_for_status(response)
        data = _parse_json(response).get("data", [])
        return sorted(m["id"] for m in data if isinstance(m, dict) and "id" in m)

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> str:
        """Run a blocking chat completion and return the assistant's text content."""
        payload = self._chat_payload(messages, model, max_tokens, temperature, extra, stream=False)
        response = self._request("POST", "/chat/completions", json_body=payload)
        self._raise_for_status(response)
        return _extract_message_content(_parse_json(response))

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Iterator[str]:
        """Stream a chat completion, yielding incremental content deltas (SSE)."""
        payload = self._chat_payload(messages, model, max_tokens, temperature, extra, stream=True)
        response = self._request("POST", "/chat/completions", json_body=payload, stream=True)
        try:
            self._raise_for_status(response)
            yield from _iter_sse_content(response.iter_lines())
        finally:
            response.close()

    def verify(self) -> VerifyResult:
        """Health-check the connection.

        Reports gateway reachability and key validity *separately*. Per
        CONNECTING.md, a public ``GET /models`` 200 does **not** prove the key
        works — so key validity is checked with a minimal ``/chat/completions``
        call, which is the only endpoint that truly exercises the credential.
        Without a configured key, only reachability is checked.
        """
        errors: list[str] = []
        # Step 1: reachability via unauthenticated /models (public per CONNECTING.md).
        try:
            public = self._request("GET", "/models", auth=False)
        except APIConnectionError as exc:
            return VerifyResult(False, None, detail="gateway unreachable", errors=[str(exc)])

        # 401/403 still means the endpoint exists (auth-related, not a bad path);
        # 404/405/5xx mean the base URL/path is wrong or the gateway is down.
        reachable = public.is_success or public.status_code in (401, 403)
        if not reachable:
            errors.append(
                f"/models returned HTTP {public.status_code} — check LLM_BASE_URL"
            )

        # Best-effort model count (informational only; does not prove the key).
        model_count: int | None = None
        if public.is_success:
            try:
                model_count = len(public.json().get("data", []))
            except ValueError:  # pragma: no cover - non-JSON body
                model_count = None

        if not self.settings.has_key:
            return VerifyResult(
                reachable,
                None,
                model_count=model_count,
                detail="gateway reachable; no API key configured to validate",
                errors=errors,
            )

        # Step 2: prove the key with a minimal chat completion (the real test).
        try:
            self.chat([{"role": "user", "content": "ping"}], max_tokens=1)
            return VerifyResult(
                True, True, model_count=model_count, detail="gateway reachable; key valid"
            )
        except AuthError as exc:
            errors.append(str(exc))
            return VerifyResult(
                reachable, False, model_count=model_count,
                detail="gateway reachable; key invalid or expired", errors=errors,
            )
        except APIError as exc:  # RateLimit / status / connection / malformed body
            errors.append(str(exc))
            return VerifyResult(
                reachable, None, model_count=model_count,
                detail="key check inconclusive", errors=errors,
            )

    # -- payload construction ---------------------------------------------

    def _chat_payload(
        self,
        messages: Sequence[ChatMessage],
        model: str | None,
        max_tokens: int | None,
        temperature: float | None,
        extra: Mapping[str, Any] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": list(messages),
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if extra:
            payload.update(extra)
        return payload


def _parse_json(response: httpx.Response) -> dict[str, Any]:
    """Parse a JSON body, raising a typed :class:`APIResponseError` on non-JSON.

    Keeps the ``NearAIError`` contract intact when a proxy/CDN returns a 200 with
    an HTML error/maintenance page instead of the expected JSON.
    """
    try:
        return response.json()
    except ValueError as exc:  # includes json.JSONDecodeError
        raise APIResponseError(
            f"gateway returned a non-JSON body (HTTP {response.status_code}) "
            f"from {response.request.url}"
        ) from exc


def _extract_message_content(data: Mapping[str, Any]) -> str:
    """Pull ``choices[0].message.content`` from a completion, with typed errors.

    Raises :class:`APIResponseError` for a malformed shape (missing/empty
    ``choices``) or a null ``content`` (e.g. a filtered or tool-call response),
    rather than leaking a raw ``KeyError``/``IndexError`` to the caller.
    """
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        preview = json.dumps(data)[:200] if isinstance(data, dict) else repr(data)[:200]
        raise APIResponseError(f"unexpected chat completion shape: {preview}") from exc
    if content is None:
        raise APIResponseError(
            "chat completion returned null content (filtered response or tool call)"
        )
    return content


def _backoff(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, … capped at 8s."""
    return min(0.5 * (2 ** attempt), 8.0)


def _iter_sse_content(lines: Iterable[str]) -> Iterator[str]:
    """Parse an OpenAI-style SSE stream, yielding non-empty content deltas."""
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices", []):
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield piece
