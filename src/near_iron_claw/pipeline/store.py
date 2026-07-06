"""Pipeline persistence.

A tiny protocol + a thread-safe in-memory implementation for the MVP. Swapping in
a durable store (e.g. Supabase) later means implementing the same three methods —
see [ROADMAP.md] Phase 3.
"""

from __future__ import annotations

import threading
from typing import Optional, Protocol

from .models import Pipeline


class PipelineStore(Protocol):
    def create(self, pipeline: Pipeline) -> Pipeline: ...
    def get(self, pipeline_id: str) -> Optional[Pipeline]: ...
    def list(self) -> list[Pipeline]: ...


class InMemoryPipelineStore:
    """Insertion-ordered, thread-safe in-memory store."""

    def __init__(self) -> None:
        self._items: dict[str, Pipeline] = {}
        self._lock = threading.Lock()

    def create(self, pipeline: Pipeline) -> Pipeline:
        with self._lock:
            self._items[pipeline.pipeline_id] = pipeline
        return pipeline

    def get(self, pipeline_id: str) -> Optional[Pipeline]:
        with self._lock:
            return self._items.get(pipeline_id)

    def list(self) -> list[Pipeline]:
        with self._lock:
            return list(self._items.values())
