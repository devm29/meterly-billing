from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from meterly.types import Slug


class UsageEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: Annotated[str, Field(min_length=1, max_length=128)]
    customer_id: Annotated[str, Field(min_length=1, max_length=128, description="External id")]
    code: Slug
    timestamp: AwareDatetime
    properties: dict[str, JsonValue] = {}


class EventBatchIn(BaseModel):
    """Items are validated one by one so a single bad event never sinks the batch."""

    events: Annotated[list[JsonValue], Field(min_length=1)]


class ItemStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class ItemError(BaseModel):
    code: str
    message: str


class EventResult(BaseModel):
    index: int
    transaction_id: str | None
    status: ItemStatus
    late: bool = False
    error: ItemError | None = None
    warnings: list[ItemError] = Field(
        default=[],
        description="Metrics that could not read this event; it still counts for the others",
    )


class EventBatchOut(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    results: list[EventResult]


class StoredEvent(BaseModel):
    id: str
    customer_id: str
    transaction_id: str
    code: str
    timestamp: datetime
    properties: dict[str, JsonValue]
    ingested_at: datetime


class EventPage(BaseModel):
    items: list[StoredEvent]
    next_cursor: str | None
