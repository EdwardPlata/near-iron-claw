"""Tests for the LLM pipeline designer: happy path, repair, and degradation."""

from __future__ import annotations

import json

from helpers import VALID_SPEC, llm_returning, llm_status, llm_valid

from near_iron_claw.pipeline.designer import design_pipeline
from near_iron_claw.pipeline.models import ApifyActorChannel, CreatePipelineRequest


def _req(**opts):
    return CreatePipelineRequest(
        goal="scrape products and dedupe by sku",
        channel=ApifyActorChannel(actor_id="apify/web-scraper", apify_token="secret-token"),
        **opts,
    )


def test_happy_path_uses_llm_and_overwrites_source():
    res = design_pipeline(llm_valid(), _req())
    assert res.llm_used is True
    assert res.fallback_reason is None
    # Server forces source + goal to trusted values (LLM's are ignored).
    assert res.spec.source == {"type": "apify-actor", "actor_id": "apify/web-scraper", "run_input": {}}
    assert res.spec.goal == "scrape products and dedupe by sku"
    assert [s.phase for s in res.spec.steps] == ["extract", "transform", "load"]


def test_secret_never_in_designed_spec():
    res = design_pipeline(llm_valid(), _req())
    assert "secret-token" not in json.dumps(res.spec.model_dump())


def test_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(VALID_SPEC) + "\n```"
    res = design_pipeline(llm_returning(fenced), _req())
    assert res.llm_used is True


def test_degrades_on_auth_error():
    res = design_pipeline(llm_status(401), _req())
    assert res.llm_used is False
    assert "LLM unavailable" in res.fallback_reason
    assert "degraded" in res.spec.tags
    # The fallback pipeline is still valid and executable.
    assert [s.phase for s in res.spec.steps] == ["extract", "transform", "load"]


def test_degrades_on_unparseable_output():
    # Both the first response and the repair are junk -> degrade.
    res = design_pipeline(llm_returning("not json at all"), _req())
    assert res.llm_used is False
    assert "could not be parsed" in res.fallback_reason


def test_repair_round_trip_recovers(monkeypatch):
    # First call returns junk, second (repair) returns valid JSON.
    import near_iron_claw.client as client_mod

    calls = {"n": 0}
    valid = json.dumps(VALID_SPEC)

    def fake_chat(self, messages, **kwargs):
        calls["n"] += 1
        return "junk" if calls["n"] == 1 else valid

    monkeypatch.setattr(client_mod.NearAIClient, "chat", fake_chat)
    res = design_pipeline(llm_valid(), _req())
    assert calls["n"] == 2
    assert res.llm_used is True
    assert res.fallback_reason is None
