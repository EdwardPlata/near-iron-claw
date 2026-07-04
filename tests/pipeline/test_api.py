"""End-to-end API tests via FastAPI TestClient (all upstreams mocked)."""

from __future__ import annotations

import json

import httpx
from helpers import llm_status, llm_valid

from near_iron_claw.pipeline import api as api_mod

APIFY_ITEMS = [{"id": 1, "sku": "A"}, {"id": 2, "sku": "B"}, {"id": 2, "sku": "B"}]


def _create_body(token="apify-secret-xyz"):
    return {
        "goal": "scrape products and dedupe by sku",
        "channel": {"type": "apify-actor", "actor_id": "apify/web-scraper", "apify_token": token},
        "options": {"output_format": "json"},
    }


def test_health(build_client):
    tc, _ = build_client()
    r = tc.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "has_key" in body["llm"]


def test_list_channels(build_client):
    tc, _ = build_client()
    r = tc.get("/v1/channels")
    assert r.status_code == 200
    types = {c["type"] for c in r.json()["channels"]}
    assert types == {"apify-actor", "apify-dataset", "custom-http"}


def test_create_pipeline_llm(build_client):
    tc, store = build_client(llm=llm_valid())
    r = tc.post("/v1/pipelines", json=_create_body())
    assert r.status_code == 201
    body = r.json()
    assert body["meta"]["llm_used"] is True
    assert body["status"] == "ready"
    # secret must NOT be stored or echoed
    assert "apify-secret-xyz" not in json.dumps(body)
    assert store.get(body["pipeline_id"]) is not None
    # stored channel is scrubbed
    assert "apify_token" not in json.dumps(store.get(body["pipeline_id"]).channel)


def test_create_pipeline_degrades_without_key(build_client):
    tc, _ = build_client(llm=llm_status(401))
    r = tc.post("/v1/pipelines", json=_create_body())
    assert r.status_code == 201  # always created
    body = r.json()
    assert body["meta"]["llm_used"] is False
    assert body["meta"]["fallback_reason"]


def test_create_validation_error(build_client):
    tc, _ = build_client(llm=llm_valid())
    r = tc.post("/v1/pipelines", json={"goal": "", "channel": {"type": "nope"}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"


def test_get_and_list_pipeline(build_client):
    tc, _ = build_client(llm=llm_valid())
    pid = tc.post("/v1/pipelines", json=_create_body()).json()["pipeline_id"]
    got = tc.get(f"/v1/pipelines/{pid}")
    assert got.status_code == 200 and got.json()["pipeline_id"] == pid
    listed = tc.get("/v1/pipelines").json()
    assert listed["count"] == 1 and listed["items"][0]["pipeline_id"] == pid


def test_get_missing_pipeline_404(build_client):
    tc, _ = build_client()
    r = tc.get("/v1/pipelines/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_dry_run_applies_transforms(build_client):
    # Apify returns 3 items; the designed pipeline dedupes by id -> 2.
    def apify_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=APIFY_ITEMS)

    tc, _ = build_client(llm=llm_valid(), http_handler=apify_handler)
    pid = tc.post("/v1/pipelines", json=_create_body()).json()["pipeline_id"]

    r = tc.post(f"/v1/pipelines/{pid}/dry-run", json={"sample_size": 10, "apify_token": "runtime-tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["raw_count"] == 3
    assert body["transformed_count"] == 2  # dedupe by id applied
    assert body["channel_type"] == "apify-actor"
    assert "id" in body["schema_inferred"]


def test_dry_run_channel_error_maps_to_422(build_client):
    def apify_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tc, _ = build_client(llm=llm_valid(), http_handler=apify_handler)
    pid = tc.post("/v1/pipelines", json=_create_body()).json()["pipeline_id"]
    r = tc.post(f"/v1/pipelines/{pid}/dry-run", json={"sample_size": 5, "apify_token": "t"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unprocessable"


def test_dry_run_missing_pipeline_404(build_client):
    tc, _ = build_client()
    r = tc.post("/v1/pipelines/nope/dry-run", json={"sample_size": 5})
    assert r.status_code == 404


def test_dry_run_404_still_closes_connector_client(build_client, monkeypatch):
    # Regression: the yield-dependency must close the httpx client even when the
    # handler raises the 404 before reaching the fetch (no fd leak).
    closed = {"v": False}
    real_make = api_mod.make_http_client

    class Tracked:
        def __init__(self, c):
            self._c = c

        def __getattr__(self, name):
            return getattr(self._c, name)

        def close(self):
            closed["v"] = True
            self._c.close()

    monkeypatch.setattr(api_mod, "make_http_client", lambda **kw: Tracked(real_make()))
    tc, _ = build_client()  # real get_connector_http dependency (not overridden)
    r = tc.post("/v1/pipelines/missing/dry-run", json={"sample_size": 5})
    assert r.status_code == 404
    assert closed["v"] is True  # client was closed despite the early 404
