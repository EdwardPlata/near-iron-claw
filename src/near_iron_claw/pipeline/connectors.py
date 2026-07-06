"""Ingestion connectors: fetch a bounded sample from a channel.

Sync ``httpx`` (matching :class:`near_iron_claw.client.NearAIClient`); the
``http`` client is injected so tests can supply an ``httpx.MockTransport``.

Supported channels (see :mod:`.models`):
  * ``apify-actor``   → ``POST /v2/acts/{id}/run-sync-get-dataset-items``
  * ``apify-dataset`` → ``GET  /v2/datasets/{id}/items``
  * ``custom-http``   → the user's URL (SSRF-guarded) + dot-path record extraction
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from .models import (
    ApifyActorChannel,
    ApifyDatasetChannel,
    Channel,
    CustomHttpChannel,
)

APIFY_BASE = "https://api.apify.com/v2"


class ConnectorError(Exception):
    """A channel could not be fetched. ``code`` maps to an API error code."""

    def __init__(self, message: str, *, code: str = "unprocessable") -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# SSRF guard (module-level so tests can monkeypatch it)
# --------------------------------------------------------------------------- #


def assert_public_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to private/loopback/link-local
    ranges (blocks SSRF to internal services and the cloud metadata endpoint)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ConnectorError(f"unsupported URL scheme: {parts.scheme!r}", code="validation_error")
    host = parts.hostname
    if not host:
        raise ConnectorError("URL has no host", code="validation_error")
    try:
        port = parts.port  # raises ValueError for an out-of-range port (e.g. :99999)
    except ValueError as exc:
        raise ConnectorError(f"invalid port in URL: {exc}", code="validation_error") from exc
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ConnectorError(f"cannot resolve host {host!r}: {exc}", code="unprocessable") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ConnectorError(
                f"host {host!r} resolves to a non-public address ({ip})", code="validation_error"
            )


# --------------------------------------------------------------------------- #
# Apify
# --------------------------------------------------------------------------- #


def _apify_token(secrets: dict[str, Any]) -> str:
    token = secrets.get("apify_token") or os.environ.get("APIFY_TOKEN")
    if not token:
        raise ConnectorError(
            "no Apify token — pass `apify_token` or set the APIFY_TOKEN env var",
            code="validation_error",
        )
    return token


def _apify_actor_path(actor_id: str) -> str:
    # The API path expects the `username~actor-name` form (slash -> tilde).
    return actor_id.replace("/", "~")


def _fetch_apify_actor(
    channel: ApifyActorChannel, secrets: dict[str, Any], sample_size: int, http: httpx.Client
) -> list[dict[str, Any]]:
    token = _apify_token(secrets)
    url = f"{APIFY_BASE}/acts/{_apify_actor_path(channel.actor_id)}/run-sync-get-dataset-items"
    resp = http.post(
        url,
        params={"format": "json", "clean": "true", "limit": sample_size},
        headers={"Authorization": f"Bearer {token}"},
        json=channel.run_input,
    )
    return _apify_json(resp)


def _fetch_apify_dataset(
    channel: ApifyDatasetChannel, secrets: dict[str, Any], sample_size: int, http: httpx.Client
) -> list[dict[str, Any]]:
    token = _apify_token(secrets)
    url = f"{APIFY_BASE}/datasets/{channel.dataset_id}/items"
    resp = http.get(
        url,
        params={"format": "json", "clean": "true", "limit": sample_size},
        headers={"Authorization": f"Bearer {token}"},
    )
    return _apify_json(resp)


def _apify_json(resp: httpx.Response) -> list[dict[str, Any]]:
    if resp.status_code in (401, 403):
        raise ConnectorError("Apify rejected the token (invalid or expired)", code="unprocessable")
    if not resp.is_success:
        raise ConnectorError(
            f"Apify returned HTTP {resp.status_code}: {resp.text[:200]}", code="unprocessable"
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise ConnectorError("Apify returned a non-JSON body", code="unprocessable") from exc
    if not isinstance(data, list):
        raise ConnectorError("Apify response was not a list of items", code="unprocessable")
    return [r for r in data if isinstance(r, dict)]


# --------------------------------------------------------------------------- #
# Custom HTTP
# --------------------------------------------------------------------------- #


def _dig(data: Any, path: str) -> Any:
    """Follow a dot-path (e.g. 'data.items') into nested dicts."""
    if not path:
        return data
    cur = data
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            raise ConnectorError(f"records_path {path!r} not found in response", code="unprocessable")
    return cur


def _fetch_custom_http(
    channel: CustomHttpChannel, secrets: dict[str, Any], sample_size: int, http: httpx.Client
) -> list[dict[str, Any]]:
    assert_public_url(channel.url)
    headers = dict(secrets.get("headers") or channel.headers or {})
    try:
        resp = http.request(
            channel.method,
            channel.url,
            headers=headers,
            json=channel.body if channel.method == "POST" else None,
        )
    except httpx.HTTPError as exc:
        raise ConnectorError(f"request to custom endpoint failed: {exc}", code="unprocessable") from exc
    if not resp.is_success:
        raise ConnectorError(
            f"custom endpoint returned HTTP {resp.status_code}", code="unprocessable"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ConnectorError("custom endpoint returned a non-JSON body", code="unprocessable") from exc
    records = _dig(payload, channel.records_path)
    if not isinstance(records, list):
        raise ConnectorError(
            "resolved records are not a JSON list — check records_path", code="unprocessable"
        )
    return [r for r in records if isinstance(r, dict)][:sample_size]


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def fetch_sample(
    channel: Channel,
    secrets: dict[str, Any],
    *,
    sample_size: int,
    http: httpx.Client,
) -> list[dict[str, Any]]:
    """Fetch up to ``sample_size`` records from the channel."""
    if isinstance(channel, ApifyActorChannel):
        return _fetch_apify_actor(channel, secrets, sample_size, http)
    if isinstance(channel, ApifyDatasetChannel):
        return _fetch_apify_dataset(channel, secrets, sample_size, http)
    if isinstance(channel, CustomHttpChannel):
        return _fetch_custom_http(channel, secrets, sample_size, http)
    raise ConnectorError(f"unknown channel type: {type(channel).__name__}", code="validation_error")


CHANNEL_CATALOG: list[dict[str, Any]] = [
    {
        "type": "apify-actor",
        "display_name": "Apify Actor",
        "description": "Run an Apify actor and read its dataset output.",
        "required_fields": ["actor_id"],
        "optional_fields": ["run_input", "apify_token"],
    },
    {
        "type": "apify-dataset",
        "display_name": "Apify Dataset",
        "description": "Read from an existing Apify dataset by id.",
        "required_fields": ["dataset_id"],
        "optional_fields": ["apify_token"],
    },
    {
        "type": "custom-http",
        "display_name": "Custom HTTP Endpoint",
        "description": "Fetch records from any HTTP(S) endpoint you control.",
        "required_fields": ["url"],
        "optional_fields": ["method", "headers", "body", "records_path"],
    },
]


def make_http_client(timeout: float = 45.0, transport: Optional[httpx.BaseTransport] = None) -> httpx.Client:
    """Build the httpx client connectors use (tests inject a MockTransport)."""
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
