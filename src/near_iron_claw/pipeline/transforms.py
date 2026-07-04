"""Safe, declarative transform executor.

Each op is a pure ``list[dict] -> list[dict]`` function selected from a fixed
dispatch table. There is **no ``eval``/``exec``/reflection** — the only ops that
can run are the ones whitelisted in :mod:`.models`. Input is deep-copied per step
so transforms are non-destructive and replayable.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from .models import (
    AddField,
    Cast,
    Dedupe,
    DropFields,
    Filter,
    Flatten,
    Limit,
    PipelineStep,
    Rename,
    SelectFields,
)

Record = dict[str, Any]


def _select(records: list[Record], op: SelectFields) -> list[Record]:
    return [{k: r.get(k) for k in op.fields} for r in records]


def _drop(records: list[Record], op: DropFields) -> list[Record]:
    drop = set(op.fields)
    return [{k: v for k, v in r.items() if k not in drop} for r in records]


def _rename(records: list[Record], op: Rename) -> list[Record]:
    return [{op.mapping.get(k, k): v for k, v in r.items()} for r in records]


_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and a > b,
    "gte": lambda a, b: a is not None and b is not None and a >= b,
    "lt": lambda a, b: a is not None and b is not None and a < b,
    "lte": lambda a, b: a is not None and b is not None and a <= b,
    "contains": lambda a, b: b is not None and a is not None and str(b) in str(a),
    "not_contains": lambda a, b: a is None or b is None or str(b) not in str(a),
    "is_null": lambda a, _b: a is None,
    "is_not_null": lambda a, _b: a is not None,
}


def _filter(records: list[Record], op: Filter) -> list[Record]:
    cmp = _COMPARATORS[op.operator]
    out = []
    for r in records:
        try:
            keep = cmp(r.get(op.field), op.value)
        except TypeError:
            keep = False  # mismatched types never match, never crash
        if keep:
            out.append(r)
    return out


def _limit(records: list[Record], op: Limit) -> list[Record]:
    return records[: op.count]


def _dedupe(records: list[Record], op: Dedupe) -> list[Record]:
    seen: set = set()
    out: list[Record] = []
    for r in records:
        if op.fields:
            key = tuple(_hashable(r.get(f)) for f in op.fields)
        else:
            key = tuple(sorted((k, _hashable(v)) for k, v in r.items()))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _flatten(records: list[Record], op: Flatten) -> list[Record]:
    out: list[Record] = []
    for r in records:
        nested = r.get(op.field)
        if isinstance(nested, list):
            base = {k: v for k, v in r.items() if k != op.field}
            for item in nested:
                new = dict(base)
                if isinstance(item, dict):
                    new.update({f"{op.prefix}{k}": v for k, v in item.items()})
                else:
                    new[f"{op.prefix}value"] = item
                out.append(new)
        else:
            out.append(r)
    return out


_CASTERS: dict[str, Callable[[Any], Any]] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def _cast(records: list[Record], op: Cast) -> list[Record]:
    fn = _CASTERS[op.to_type]
    out = []
    for r in records:
        new = dict(r)
        if op.field in new and new[op.field] is not None:
            try:
                new[op.field] = fn(new[op.field])
            except (ValueError, TypeError):
                new[op.field] = None
        out.append(new)
    return out


def _add_field(records: list[Record], op: AddField) -> list[Record]:
    return [{**r, op.field: op.value} for r in records]


_DISPATCH: dict[str, Callable[[list[Record], Any], list[Record]]] = {
    "select_fields": _select,
    "drop_fields": _drop,
    "rename": _rename,
    "filter": _filter,
    "limit": _limit,
    "dedupe": _dedupe,
    "flatten": _flatten,
    "cast": _cast,
    "add_field": _add_field,
}


def _hashable(value: Any) -> Any:
    """Make a value usable as a dedupe key (lists/dicts -> stable string)."""
    if isinstance(value, (list, dict)):
        import json

        return json.dumps(value, sort_keys=True, default=str)
    return value


def apply_ops(records: list[Record], ops: list[Any]) -> list[Record]:
    """Apply an ordered list of validated transform ops to a copy of ``records``."""
    current = copy.deepcopy(records)
    for op in ops:
        handler = _DISPATCH[op.op]  # op.op is validated by Pydantic; KeyError impossible
        current = handler(current, op)
    return current


def execute_steps(records: list[Record], steps: list[PipelineStep]) -> list[Record]:
    """Run every transform step's ops in ``order``."""
    ordered = sorted(steps, key=lambda s: s.order)
    all_ops = [op for step in ordered for op in step.ops]
    return apply_ops(records, all_ops)


def infer_schema(records: list[Record]) -> dict[str, str]:
    """Best-effort field -> python-type-name map from a sample (first 50 records)."""
    schema: dict[str, str] = {}
    for r in records[:50]:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if k not in schema and v is not None:
                schema[k] = type(v).__name__
    return schema
