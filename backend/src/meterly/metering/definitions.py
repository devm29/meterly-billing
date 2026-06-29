from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from meterly.types import Slug

PropertyPath = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$",
        description="Dot-separated path into the event properties, e.g. usage.input_tokens",
    ),
]


class Aggregation(StrEnum):
    COUNT = "count"
    SUM = "sum"
    MAX = "max"
    UNIQUE_COUNT = "unique_count"
    LATEST = "latest"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Slug
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=500)] | None = None
    event_code: Slug
    aggregation: Aggregation
    field: PropertyPath | None = None
    group_by: Annotated[list[PropertyPath], Field(max_length=3)] = []
    unit: Annotated[str, Field(min_length=1, max_length=32)] = "units"

    @model_validator(mode="after")
    def _field_matches_aggregation(self) -> MetricDefinition:
        if self.aggregation is Aggregation.COUNT and self.field is not None:
            raise ValueError("count metrics do not read a property")
        if self.aggregation is not Aggregation.COUNT and self.field is None:
            raise ValueError(f"{self.aggregation} metrics need a field")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by dimensions must be unique")
        return self


class Metric(MetricDefinition):
    id: UUID

    @property
    def path(self) -> list[str]:
        return self.field.split(".") if self.field else []


class Reading(BaseModel):
    """What one event contributes to one metric."""

    model_config = ConfigDict(frozen=True)

    metric_id: UUID
    group_key: str
    numeric: Decimal | None = None
    distinct: str | None = None


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MissingPropertyError(ExtractionError):
    """The event simply doesn't carry what this metric reads; other metrics may still use it."""

    def __init__(self, metric: Metric) -> None:
        super().__init__(
            "missing_property", f"metric {metric.code!r} needs property {metric.field!r}"
        )


_MISSING = object()


def lookup(properties: Mapping[str, object], path: Sequence[str]) -> object:
    node: object = properties
    for part in path:
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def group_key(dimensions: Mapping[str, str | None]) -> str:
    return json.dumps(dimensions, sort_keys=True, separators=(",", ":"))


def parse_group_key(key: str) -> dict[str, str | None]:
    parsed: dict[str, str | None] = json.loads(key)
    return parsed


def read(metric: Metric, properties: Mapping[str, object]) -> Reading:
    dimensions: dict[str, str | None] = {}
    for dim in metric.group_by:
        raw = lookup(properties, dim.split("."))
        dimensions[dim] = None if raw is _MISSING or raw is None else _scalar_text(raw, dim)

    key = group_key(dimensions)
    if metric.aggregation is Aggregation.COUNT:
        return Reading(metric_id=metric.id, group_key=key)

    raw = lookup(properties, metric.path)
    if raw is _MISSING or raw is None:
        raise MissingPropertyError(metric)
    if metric.aggregation is Aggregation.UNIQUE_COUNT:
        return Reading(
            metric_id=metric.id, group_key=key, distinct=_scalar_text(raw, metric.field or "")
        )
    return Reading(metric_id=metric.id, group_key=key, numeric=_number(raw, metric))


def _scalar_text(raw: object, path: str) -> str:
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, str | int | float | Decimal):
        return str(raw)
    raise ExtractionError("invalid_property", f"property {path!r} must be a scalar value")


def _number(raw: object, metric: Metric) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, str | int | float | Decimal):
        raise ExtractionError("invalid_property", f"property {metric.field!r} must be numeric")
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ExtractionError(
            "invalid_property", f"property {metric.field!r} must be numeric"
        ) from exc
    if not value.is_finite():
        raise ExtractionError("invalid_property", f"property {metric.field!r} must be finite")
    return value
