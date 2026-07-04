"""LLM-backed pipeline designer.

Turns ``{goal, channel}`` into a validated :class:`PipelineSpec` by prompting the
model on NEAR AI Cloud (via :class:`near_iron_claw.client.NearAIClient`). Robust by
construction:

  * output is parsed as JSON (markdown fences stripped) and validated with Pydantic,
  * one **repair** round-trip is attempted on invalid output,
  * any failure (no key, auth error, timeout, unparseable output) **degrades** to a
    deterministic rule-based spec and records why (``llm_used=False`` + reason).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..client import NearAIClient
from ..errors import NearAIError
from .models import (
    ALLOWED_OPS,
    Channel,
    CreatePipelineRequest,
    LoadTarget,
    PipelineSpec,
    PipelineStep,
    channel_public,
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass
class DesignResult:
    spec: PipelineSpec
    llm_used: bool
    model: Optional[str]
    fallback_reason: Optional[str]


def _system_prompt(model: str, max_steps: int) -> str:
    return (
        "You are a data-pipeline designer. Given a goal and a data source, output ONE JSON "
        "object that is a valid PipelineSpec. Output ONLY the JSON — no prose, no markdown.\n\n"
        "PipelineSpec = {\n"
        '  "spec_version": "1.0",\n'
        '  "name": string, "description": string, "goal": string,\n'
        '  "source": <the source object provided to you, unchanged>,\n'
        '  "steps": PipelineStep[],  // ordered; first phase "extract", last "load"\n'
        '  "load": {"destination": "return"|"jsonl", "format": "json"|"jsonl"},\n'
        '  "tags": string[]\n}\n'
        'PipelineStep = {"phase": "extract"|"transform"|"load", "order": int>=1, '
        '"name": string, "description": string, "ops": Transform[]}\n'
        "Only 'transform' steps have ops. Allowed transform ops (use the exact 'op' value):\n"
        '  {"op":"select_fields","fields":[...]}  {"op":"drop_fields","fields":[...]}\n'
        '  {"op":"rename","mapping":{"old":"new"}}  {"op":"limit","count":int}\n'
        '  {"op":"filter","field":str,"operator":'
        '"eq|neq|gt|gte|lt|lte|contains|not_contains|is_null|is_not_null","value":any}\n'
        '  {"op":"dedupe","fields":[...]}  {"op":"flatten","field":str,"prefix":str}\n'
        '  {"op":"cast","field":str,"to_type":"str|int|float|bool"}  '
        '{"op":"add_field","field":str,"value":any}\n'
        f"Use at most {max_steps} steps. Do not invent op names outside: {', '.join(ALLOWED_OPS)}.\n"
        f"You are running as model '{model}'."
    )


def _user_prompt(goal: str, source: dict[str, Any], output_format: str) -> str:
    return (
        f"goal: {goal}\n"
        f"source (use verbatim as PipelineSpec.source): {json.dumps(source)}\n"
        f"preferred load format: {output_format}\n"
        "Design the pipeline now. Output only the JSON object."
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text)
    return text.strip()


def _parse(text: str) -> PipelineSpec:
    data = json.loads(_strip_fences(text))
    return PipelineSpec.model_validate(data)


def design_pipeline(client: NearAIClient, req: CreatePipelineRequest) -> DesignResult:
    """Design a pipeline for ``req``; degrade to a rule-based spec on any failure."""
    source = channel_public(req.channel)
    model = req.options.model or client.settings.model
    messages = [
        {"role": "system", "content": _system_prompt(model, req.options.max_steps)},
        {"role": "user", "content": _user_prompt(req.goal, source, req.options.output_format)},
    ]

    try:
        raw = client.chat(messages, model=req.options.model, max_tokens=1500, temperature=0)
    except NearAIError as exc:
        return _degrade(req, source, model, f"LLM unavailable: {exc}")

    try:
        spec = _parse(raw)
        return DesignResult(_finalize(spec, req, source), True, model, None)
    except (ValueError, json.JSONDecodeError) as first_err:
        # One repair round-trip.
        repair = messages + [
            {"role": "assistant", "content": raw[:4000]},
            {
                "role": "user",
                "content": f"That was not a valid PipelineSpec ({first_err}). "
                "Output only the corrected JSON object.",
            },
        ]
        try:
            raw2 = client.chat(repair, model=req.options.model, max_tokens=1500, temperature=0)
            spec = _parse(raw2)
            return DesignResult(_finalize(spec, req, source), True, model, None)
        except NearAIError as exc:
            return _degrade(req, source, model, f"LLM unavailable during repair: {exc}")
        except (ValueError, json.JSONDecodeError):
            return _degrade(req, source, model, "LLM response could not be parsed as a PipelineSpec")


def _finalize(spec: PipelineSpec, req: CreatePipelineRequest, source: dict[str, Any]) -> PipelineSpec:
    """Force server-owned fields to trusted values (source/goal are never LLM-authoritative)."""
    spec.source = source
    spec.goal = req.goal
    if not spec.name:
        spec.name = _name_from_goal(req.goal)
    return spec


def _degrade(
    req: CreatePipelineRequest, source: dict[str, Any], model: str, reason: str
) -> DesignResult:
    """A deterministic, always-valid pipeline: extract → passthrough → load."""
    ch_type = source.get("type", "source")
    spec = PipelineSpec(
        name=_name_from_goal(req.goal),
        description=f"Auto-generated (degraded) pipeline for a {ch_type} source.",
        goal=req.goal,
        source=source,
        steps=[
            PipelineStep(phase="extract", order=1, name=f"extract:{ch_type}",
                         description=f"Fetch records from the {ch_type} channel."),
            PipelineStep(phase="transform", order=2, name="passthrough",
                         description="No transforms (rule-based fallback).", ops=[]),
            PipelineStep(phase="load", order=3, name="load",
                         description=f"Emit records as {req.options.output_format}."),
        ],
        load=LoadTarget(destination="return", format=req.options.output_format),
        tags=["degraded"],
    )
    return DesignResult(spec, False, model, reason)


def _name_from_goal(goal: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", goal.lower())[:6]
    return ("-".join(words) or "pipeline")[:60]


def channel_display_type(channel: Channel) -> str:
    return channel_public(channel).get("type", "unknown")
