"""Shared pytest fixtures: a mock-transport client factory."""

from __future__ import annotations

import os
from typing import Callable

import httpx
import pytest

from near_iron_claw import NearAIClient, Settings

Handler = Callable[[httpx.Request], httpx.Response]


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked 'live' against the real gateway",
    )


def pytest_collection_modifyitems(config, items):
    """Deselect 'live' tests unless --run-live (or RUN_LIVE=1) is given."""
    if config.getoption("--run-live") or os.environ.get("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test; pass --run-live or set RUN_LIVE=1 to enable")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        base_url="https://cloud-api.near.ai/v1",
        api_key="sk-agent-testkey0000000000000000000000",
        model="anthropic/claude-sonnet-4-6",
        timeout=5.0,
        max_retries=1,
    )


@pytest.fixture
def make_client(settings: Settings) -> Callable[[Handler], NearAIClient]:
    def _factory(handler: Handler, *, s: Settings = settings) -> NearAIClient:
        return NearAIClient(s, transport=httpx.MockTransport(handler))

    return _factory
