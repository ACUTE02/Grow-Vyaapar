"""Request/response bodies for the agent-owned surfaces."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    phone: str | None = None
    segment: str
    recency_days: int | None = None
    frequency_90d: int
    total_spend: Decimal
    computed_at: datetime


class SegmentRebuildOut(BaseModel):
    store_id: int
    distribution: dict[str, int]


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    phone: str | None = None
    kind: str
    channel: str
    message: str
    status: str
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime


class ReminderRunOut(BaseModel):
    store_id: int
    created: dict[str, int]
    total: int
    used_llm: bool


class SuggestionOut(BaseModel):
    title: str
    detail: str
    figure: str | None = None
    action: str | None = None


class InsightOut(BaseModel):
    store_id: int
    period: str
    generated_at: datetime
    metrics: dict[str, Any]
    suggestions: list[SuggestionOut]
    source: str = Field(description="llm | cache | template")


class CampaignIn(BaseModel):
    occasion: str = Field(min_length=2, max_length=96)


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    occasion: str
    prompt: str | None = None
    caption: str | None = None
    hashtags: list[str] = []
    image_url: str | None = None
    status: str
    created_at: datetime


class CampaignStatusIn(BaseModel):
    status: str = Field(pattern="^(draft|saved|published)$")
