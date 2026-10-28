"""FastAPI app for the Pipeline Creator.

Run locally:  ``uvicorn near_iron_claw.pipeline.api:app --reload``  → http://127.0.0.1:8000/docs

Dependencies (`get_nearai_client`, `get_connector_http`, `get_store`) are provided via
FastAPI's DI so tests can override them with mock transports and a fresh store.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..client import NearAIClient
from ..config import Settings
from .connectors import (
    CHANNEL_CATALOG,
    ConnectorError,
    fetch_sample,
    make_http_client,
)
from .designer import design_pipeline
from .models import (
    ApifyActorChannel,
    ApifyDatasetChannel,
    Channel,
    ChannelInfo,
    ChannelsResponse,
    CreatePipelineRequest,
    CustomHttpChannel,
    DryRunRequest,
    DryRunResponse,
    Pipeline,
    PipelineList,
    PipelineListItem,
    PipelineMeta,
    channel_secrets,
)
from .store import InMemoryPipelineStore, PipelineStore
from .transforms import execute_steps, infer_schema

app = FastAPI(
    title="near-iron-claw · Pipeline Creator",
    version=__version__,
    description="Design LLM-powered data pipelines from Apify + custom ingestion channels.",
)

_STORE = InMemoryPipelineStore()

_CODE_STATUS = {
    "validation_error": 400,
    "not_found": 404,
    "unprocessable": 422,
    "llm_upstream_error": 502,
}


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)
# --------------------------------------------------------------------------- #


def get_nearai_client() -> Iterator[NearAIClient]:
    # `yield` dependency: FastAPI closes the client on EVERY exit path (return,
    # raise, or request-validation failure), so it can't leak on non-happy paths.
    client = NearAIClient(Settings.load())
    try:
        yield client
    finally:
        client.close()


def get_connector_http() -> Iterator[httpx.Client]:
    http = make_http_client()
    try:
        yield http
    finally:
        http.close()


def get_store() -> PipelineStore:
    return _STORE


# --------------------------------------------------------------------------- #
# Error envelope handlers
# --------------------------------------------------------------------------- #


def _err(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(ConnectorError)
async def _connector_error(_req: Request, exc: ConnectorError) -> JSONResponse:
    return _err(_CODE_STATUS.get(exc.code, 422), exc.code, str(exc))


@app.exception_handler(RequestValidationError)
async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
    return _err(400, "validation_error", "request body failed validation", detail=exc.errors())


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed", 415: "unsupported_media_type"}.get(
        exc.status_code, "error"
    )
    return _err(exc.status_code, code, str(exc.detail))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict[str, Any]:
    settings = Settings.load()
    return {
        "status": "ok",
        "service": "near-iron-claw-pipeline",
        "version": __version__,
        "llm": {
            "base_url": settings.base_url,
            "model": settings.model,
            "has_key": settings.has_key,
        },
    }


@app.get("/v1/channels", response_model=ChannelsResponse)
def list_channels() -> ChannelsResponse:
    return ChannelsResponse(channels=[ChannelInfo(**c) for c in CHANNEL_CATALOG])


@app.post("/v1/pipelines", response_model=Pipeline, status_code=201)
def create_pipeline(
    req: CreatePipelineRequest,
    client: NearAIClient = Depends(get_nearai_client),
    store: PipelineStore = Depends(get_store),
) -> Pipeline:
    result = design_pipeline(client, req)  # client closed by the get_nearai_client dependency

    pipeline = Pipeline(
        status="ready",
        goal=req.goal,
        channel=result.spec.source,  # already scrubbed (channel.public())
        spec=result.spec,
        meta=PipelineMeta(
            llm_used=result.llm_used,
            llm_model=result.model,
            fallback_reason=result.fallback_reason,
            step_count=len(result.spec.steps),
        ),
    )
    return store.create(pipeline)


@app.get("/v1/pipelines", response_model=PipelineList)
def list_pipelines(store: PipelineStore = Depends(get_store)) -> PipelineList:
    items = [
        PipelineListItem(
            pipeline_id=p.pipeline_id, status=p.status, goal=p.goal, channel=p.channel, meta=p.meta
        )
        for p in store.list()
    ]
    return PipelineList(items=items, count=len(items))


def _require_pipeline(store: PipelineStore, pipeline_id: str) -> Pipeline:
    """Fetch a pipeline or raise a 404 (shared by the get + dry-run routes)."""
    pipeline = store.get(pipeline_id)
    if pipeline is None:
        raise StarletteHTTPException(status_code=404, detail=f"pipeline {pipeline_id} not found")
    return pipeline


@app.get("/v1/pipelines/{pipeline_id}", response_model=Pipeline)
def get_pipeline(pipeline_id: str, store: PipelineStore = Depends(get_store)) -> Pipeline:
    return _require_pipeline(store, pipeline_id)


@app.post("/v1/pipelines/{pipeline_id}/dry-run", response_model=DryRunResponse)
def dry_run(
    pipeline_id: str,
    body: DryRunRequest,
    store: PipelineStore = Depends(get_store),
    http: httpx.Client = Depends(get_connector_http),
) -> DryRunResponse:
    pipeline = _require_pipeline(store, pipeline_id)

    channel = _rebuild_channel(pipeline.channel, body)
    secrets = channel_secrets(channel)
    warnings: list[str] = []

    started = time.monotonic()
    raw = fetch_sample(channel, secrets, sample_size=body.sample_size, http=http)
    duration_ms = int((time.monotonic() - started) * 1000)

    transformed = execute_steps(raw, pipeline.spec.steps)
    if pipeline.meta.fallback_reason:
        warnings.append(f"pipeline was designed in degraded mode: {pipeline.meta.fallback_reason}")

    return DryRunResponse(
        pipeline_id=pipeline_id,
        channel_type=channel.type,
        sample_size=body.sample_size,
        raw_count=len(raw),
        transformed_count=len(transformed),
        records=transformed,
        truncated=len(raw) >= body.sample_size,
        schema_inferred=infer_schema(transformed),
        duration_ms=duration_ms,
        warnings=warnings,
    )


def _rebuild_channel(public: dict[str, Any], body: DryRunRequest) -> Channel:
    """Reconstruct a channel from its stored (scrubbed) form + transient run secrets."""
    ctype = public.get("type")
    if ctype == "apify-actor":
        return ApifyActorChannel(
            actor_id=public["actor_id"],
            run_input=public.get("run_input", {}),
            apify_token=body.apify_token,
        )
    if ctype == "apify-dataset":
        return ApifyDatasetChannel(dataset_id=public["dataset_id"], apify_token=body.apify_token)
    if ctype == "custom-http":
        return CustomHttpChannel(
            url=public["url"],
            method=public.get("method", "GET"),
            body=public.get("body"),
            records_path=public.get("records_path", ""),
            headers=body.headers or {},
        )
    raise StarletteHTTPException(status_code=422, detail=f"unknown stored channel type: {ctype}")
