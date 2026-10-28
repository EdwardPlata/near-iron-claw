"""Tests for the declarative transform executor."""

from __future__ import annotations

from near_iron_claw.pipeline.models import (
    AddField,
    Cast,
    Dedupe,
    DropFields,
    Filter,
    Flatten,
    Limit,
    Rename,
    SelectFields,
)
from near_iron_claw.pipeline.transforms import apply_ops, infer_schema

ROWS = [
    {"id": 1, "name": "A", "price": "10"},
    {"id": 2, "name": "B", "price": "20"},
    {"id": 2, "name": "B", "price": "20"},
]


def test_select_and_drop_fields():
    assert apply_ops(ROWS, [SelectFields(fields=["id"])]) == [{"id": 1}, {"id": 2}, {"id": 2}]
    dropped = apply_ops(ROWS, [DropFields(fields=["price", "name"])])
    assert dropped == [{"id": 1}, {"id": 2}, {"id": 2}]


def test_rename():
    out = apply_ops([{"old": 1}], [Rename(mapping={"old": "new"})])
    assert out == [{"new": 1}]


def test_filter_operators():
    assert apply_ops(ROWS, [Filter(field="id", operator="eq", value=2)]) == ROWS[1:]
    assert apply_ops(ROWS, [Filter(field="name", operator="contains", value="A")]) == [ROWS[0]]
    assert len(apply_ops(ROWS, [Filter(field="id", operator="gte", value=2)])) == 2
    # type-mismatched comparisons never crash
    assert apply_ops(ROWS, [Filter(field="name", operator="gt", value=5)]) == []


def test_limit_and_dedupe():
    assert apply_ops(ROWS, [Limit(count=2)]) == ROWS[:2]
    assert apply_ops(ROWS, [Dedupe(fields=["id"])]) == ROWS[:2]
    assert apply_ops(ROWS, [Dedupe(fields=[])]) == ROWS[:2]  # full-record dedupe


def test_flatten():
    rows = [{"g": "x", "items": [{"a": 1}, {"a": 2}]}]
    out = apply_ops(rows, [Flatten(field="items", prefix="i_")])
    assert out == [{"g": "x", "i_a": 1}, {"g": "x", "i_a": 2}]


def test_cast_and_add_field():
    out = apply_ops(ROWS, [Cast(field="price", to_type="float")])
    assert out[0]["price"] == 10.0
    # uncastable becomes None, never raises
    bad = apply_ops([{"price": "abc"}], [Cast(field="price", to_type="int")])
    assert bad == [{"price": None}]
    added = apply_ops([{"a": 1}], [AddField(field="source", value="apify")])
    assert added == [{"a": 1, "source": "apify"}]


def test_ops_are_non_destructive():
    original = [{"id": 1}]
    apply_ops(original, [AddField(field="x", value=1), Limit(count=1)])
    assert original == [{"id": 1}]  # input untouched (no "x" added)


def test_infer_schema():
    assert infer_schema(ROWS) == {"id": "int", "name": "str", "price": "str"}
