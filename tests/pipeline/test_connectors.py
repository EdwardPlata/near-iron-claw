"""Tests for the ingestion connectors (Apify + custom-http), all mocked."""

from __future__ import annotations

import httpx
import pytest

from near_iron_claw.pipeline import connectors
from near_iron_claw.pipeline.connectors import ConnectorError, fetch_sample
from near_iron_claw.pipeline.models import (
    ApifyActorChannel,
    ApifyDatasetChannel,
    CustomHttpChannel,
)

ITEMS = [{"id": 1}, {"id": 2}, {"id": 3}]


def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_apify_actor_run_sync(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=ITEMS)

    ch = ApifyActorChannel(actor_id="apify/web-scraper", apify_token="apify_tok")
    out = fetch_sample(ch, {"apify_token": "apify_tok"}, sample_size=2, http=_http(handler))
    assert out == ITEMS
    assert "acts/apify~web-scraper/run-sync-get-dataset-items" in seen["url"]
    assert "limit=2" in seen["url"]
    assert seen["auth"] == "Bearer apify_tok"


def test_apify_dataset_fetch():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "datasets/DS123/items" in str(request.url)
        return httpx.Response(200, json=ITEMS)

    ch = ApifyDatasetChannel(dataset_id="DS123")
    out = fetch_sample(ch, {"apify_token": "t"}, sample_size=5, http=_http(handler))
    assert out == ITEMS


def test_apify_missing_token_is_validation_error():
    ch = ApifyDatasetChannel(dataset_id="DS")
    http = _http(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ConnectorError) as exc:
        fetch_sample(ch, {"apify_token": None}, sample_size=5, http=http)
    assert exc.value.code == "validation_error"


def test_apify_401_maps_to_unprocessable():
    ch = ApifyDatasetChannel(dataset_id="DS", apify_token="bad")
    with pytest.raises(ConnectorError) as exc:
        fetch_sample(ch, {"apify_token": "bad"}, sample_size=5,
                     http=_http(lambda r: httpx.Response(401, text="no")))
    assert exc.value.code == "unprocessable"


def test_custom_http_extracts_records_path(monkeypatch):
    monkeypatch.setattr(connectors, "assert_public_url", lambda url: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"items": ITEMS}})

    ch = CustomHttpChannel(url="https://api.example.com/x", records_path="data.items")
    out = fetch_sample(ch, {"headers": {}}, sample_size=2, http=_http(handler))
    assert out == ITEMS[:2]


def test_custom_http_bad_records_path(monkeypatch):
    monkeypatch.setattr(connectors, "assert_public_url", lambda url: None)
    ch = CustomHttpChannel(url="https://api.example.com/x", records_path="nope")
    with pytest.raises(ConnectorError):
        fetch_sample(ch, {"headers": {}}, sample_size=2,
                     http=_http(lambda r: httpx.Response(200, json={"data": []})))


def test_ssrf_guard_blocks_private_and_bad_scheme():
    # Real guard (not patched): loopback + non-http scheme must be rejected.
    with pytest.raises(ConnectorError) as e1:
        connectors.assert_public_url("http://127.0.0.1/admin")
    assert e1.value.code == "validation_error"
    with pytest.raises(ConnectorError):
        connectors.assert_public_url("file:///etc/passwd")


def test_ssrf_guard_blocks_metadata_ip():
    with pytest.raises(ConnectorError):
        connectors.assert_public_url("http://169.254.169.254/latest/meta-data/")


def test_ssrf_guard_rejects_out_of_range_port_cleanly():
    # Regression: an out-of-range port must raise ConnectorError (400), not a bare
    # ValueError that surfaces as a 500.
    with pytest.raises(ConnectorError) as exc:
        connectors.assert_public_url("http://example.com:99999/x")
    assert exc.value.code == "validation_error"
