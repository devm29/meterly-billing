from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GroupUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimensions: dict[str, str | None]
    quantity: Decimal


class MetricUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: Decimal
    groups: list[GroupUsage] = []
