"""Pipeline Creator API — design LLM-powered data pipelines from Apify + custom channels.

See FEATURE.md and SPEC.md (§Feature). Public entry point:

    from near_iron_claw.pipeline.api import app   # FastAPI ASGI app
"""

from __future__ import annotations

from .designer import DesignResult, design_pipeline
from .models import (
    Channel,
    CreatePipelineRequest,
    DryRunRequest,
    Pipeline,
    PipelineSpec,
)
from .store import InMemoryPipelineStore, PipelineStore

__all__ = [
    "design_pipeline",
    "DesignResult",
    "PipelineSpec",
    "Pipeline",
    "CreatePipelineRequest",
    "DryRunRequest",
    "Channel",
    "PipelineStore",
    "InMemoryPipelineStore",
]
