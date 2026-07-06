"""Pydantic v2 models for the Pipeline Creator API.

Three families of models:
  * **Channels** — polymorphic ingestion sources (discriminated on ``type``).
  * **Transforms** — a *whitelist* of declarative ops (discriminated on ``op``);
    unknown ops cannot deserialize, so there is no arbitrary-code surface.
  * **Pipelines** — the designed spec plus request/response envelopes.

Secret fields (``apify_token``, custom ``headers``) are accepted on input but are
**scrubbed** before a channel is stored or returned — see ``*.public()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Ingestion channels (discriminated union on `type`)
# --------------------------------------------------------------------------- #


class _ApifyChannel(BaseModel):
    """Shared base for Apify channels — carries the (secret) token field.
    Does NOT declare ``type`` so each leaf keeps its own discriminator literal."""

    apify_token: Optional[str] = Field(default=None, description="Secret — not stored/echoed")


class ApifyActorChannel(_ApifyChannel):
    type: Literal["apify-actor"] = "apify-actor"
    actor_id: str = Field(..., description="Apify actor slug, e.g. 'apify/web-scraper'")
    run_input: dict[str, Any] = Field(default_factory=dict, description="Actor input JSON")

    def public(self) -> dict[str, Any]:
        return {"type": self.type, "actor_id": self.actor_id, "run_input": self.run_input}


class ApifyDatasetChannel(_ApifyChannel):
    type: Literal["apify-dataset"] = "apify-dataset"
    dataset_id: str = Field(..., description="Apify dataset id")

    def public(self) -> dict[str, Any]:
        return {"type": self.type, "dataset_id": self.dataset_id}


class CustomHttpChannel(BaseModel):
    type: Literal["custom-http"] = "custom-http"
    url: str = Field(..., description="HTTP(S) endpoint you control")
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict, description="Secret — not stored/echoed")
    body: Optional[dict[str, Any]] = Field(default=None, description="JSON body for POST")
    records_path: str = Field(
        default="",
        description="Dot-path to the list of records in the response (empty = the top-level list)",
    )

    def public(self) -> dict[str, Any]:
        # `body` is not secret and is needed to reconstruct the channel for a dry-run;
        # `headers` ARE secret and are deliberately excluded.
        return {
            "type": self.type,
            "url": self.url,
            "method": self.method,
            "body": self.body,
            "records_path": self.records_path,
        }


Channel = Annotated[
    Union[ApifyActorChannel, ApifyDatasetChannel, CustomHttpChannel],
    Field(discriminator="type"),
]


def channel_public(channel: Channel) -> dict[str, Any]:
    """Return the non-secret view of any channel (used for storage + responses)."""
    return channel.public()  # type: ignore[union-attr]


def channel_secrets(channel: Channel) -> dict[str, Any]:
    """Extract the transient secrets a connector needs (never stored)."""
    if isinstance(channel, _ApifyChannel):
        return {"apify_token": channel.apify_token}
    if isinstance(channel, CustomHttpChannel):
        return {"headers": channel.headers}
    return {}


# --------------------------------------------------------------------------- #
# Transform ops (discriminated union on `op` — the safe whitelist)
# --------------------------------------------------------------------------- #

FilterOperator = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "is_null", "is_not_null"
]


class SelectFields(BaseModel):
    op: Literal["select_fields"] = "select_fields"
    fields: list[str]


class DropFields(BaseModel):
    op: Literal["drop_fields"] = "drop_fields"
    fields: list[str]


class Rename(BaseModel):
    op: Literal["rename"] = "rename"
    mapping: dict[str, str]


class Filter(BaseModel):
    op: Literal["filter"] = "filter"
    field: str
    operator: FilterOperator
    value: Optional[Union[str, int, float, bool]] = None


class Limit(BaseModel):
    op: Literal["limit"] = "limit"
    count: int = Field(gt=0, le=1_000_000)


class Dedupe(BaseModel):
    op: Literal["dedupe"] = "dedupe"
    fields: list[str] = Field(default_factory=list)  # empty = full-record dedupe


class Flatten(BaseModel):
    op: Literal["flatten"] = "flatten"
    field: str
    prefix: str = ""


class Cast(BaseModel):
    op: Literal["cast"] = "cast"
    field: str
    to_type: Literal["str", "int", "float", "bool"]


class AddField(BaseModel):
    op: Literal["add_field"] = "add_field"
    field: str
    value: Optional[Union[str, int, float, bool]] = None


Transform = Annotated[
    Union[SelectFields, DropFields, Rename, Filter, Limit, Dedupe, Flatten, Cast, AddField],
    Field(discriminator="op"),
]

ALLOWED_OPS = [
    "select_fields", "drop_fields", "rename", "filter",
    "limit", "dedupe", "flatten", "cast", "add_field",
]


# --------------------------------------------------------------------------- #
# Pipeline spec + steps
# --------------------------------------------------------------------------- #


class PipelineStep(BaseModel):
    step_id: str = Field(default_factory=lambda: "s_" + uuid.uuid4().hex[:8])
    phase: Literal["extract", "transform", "load"]
    order: int = Field(ge=1)
    name: str
    description: str = ""
    ops: list[Transform] = Field(default_factory=list)  # populated for transform steps


class LoadTarget(BaseModel):
    destination: Literal["return", "jsonl"] = "return"
    format: Literal["json", "jsonl"] = "json"


class PipelineSpec(BaseModel):
    """The designed pipeline. ``source`` is the scrubbed (non-secret) channel view."""

    spec_version: Literal["1.0"] = "1.0"
    name: str
    description: str = ""
    goal: str
    source: dict[str, Any]
    steps: list[PipelineStep]
    load: LoadTarget = Field(default_factory=LoadTarget)
    tags: list[str] = Field(default_factory=list)

    def transform_ops(self) -> list[Transform]:
        """The ordered transform ops across all transform steps (execution order)."""
        ops: list[Transform] = []
        for step in sorted(self.steps, key=lambda s: s.order):
            ops.extend(step.ops)
        return ops


# --------------------------------------------------------------------------- #
# Request / response envelopes
# --------------------------------------------------------------------------- #


class CreateOptions(BaseModel):
    max_steps: int = Field(default=10, ge=1, le=50)
    output_format: Literal["json", "jsonl"] = "json"
    model: Optional[str] = None


class CreatePipelineRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000)
    channel: Channel
    options: CreateOptions = Field(default_factory=CreateOptions)


class PipelineMeta(BaseModel):
    llm_used: bool
    llm_model: Optional[str] = None
    fallback_reason: Optional[str] = None
    step_count: int
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Pipeline(BaseModel):
    """Stored + returned resource. Never contains secrets."""

    pipeline_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: Literal["ready", "error"] = "ready"
    goal: str
    channel: dict[str, Any]  # scrubbed
    spec: PipelineSpec
    meta: PipelineMeta


class PipelineListItem(BaseModel):
    pipeline_id: str
    status: str
    goal: str
    channel: dict[str, Any]
    meta: PipelineMeta


class PipelineList(BaseModel):
    items: list[PipelineListItem]
    count: int


class DryRunRequest(BaseModel):
    sample_size: int = Field(default=10, ge=1, le=100)
    # Transient secrets for this run only — never stored.
    apify_token: Optional[str] = None
    headers: Optional[dict[str, str]] = None


class DryRunResponse(BaseModel):
    pipeline_id: str
    channel_type: str
    sample_size: int
    raw_count: int
    transformed_count: int
    records: list[dict[str, Any]]
    truncated: bool
    schema_inferred: dict[str, str]
    duration_ms: int
    warnings: list[str] = Field(default_factory=list)


class ChannelInfo(BaseModel):
    type: str
    display_name: str
    description: str
    required_fields: list[str]
    optional_fields: list[str]


class ChannelsResponse(BaseModel):
    channels: list[ChannelInfo]


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody
