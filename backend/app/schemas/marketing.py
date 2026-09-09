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
    provider_response: str | None = None
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
    source: str = Field(description="llm | cache | template | template_failed")


class CampaignIn(BaseModel):
    occasion: str = Field(min_length=2, max_length=96)
    # Printed onto the poster itself, not just mentioned in the caption.
    offer_text: str | None = Field(default=None, max_length=140)


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    occasion: str
    offer_text: str | None = None
    prompt: str | None = None
    caption: str | None = None
    hashtags: list[str] = []
    image_url: str | None = None
    status: str
    created_at: datetime


class CampaignStatusIn(BaseModel):
    status: str = Field(pattern="^(draft|saved|published)$")


class SendBatchIn(BaseModel):
    reminder_ids: list[int] = Field(min_length=1, max_length=200)


class SendResult(BaseModel):
    reminder_id: int
    status: str
    detail: str | None = None


class SendBatchOut(BaseModel):
    store_id: int
    adapter: str
    sent: int
    failed: int
    skipped: int
    cap_remaining: int
    results: list[SendResult]


class DeliveryStatusOut(BaseModel):
    store_id: int
    adapter: str
    daily_cap: int
    sent_today: int
    cap_remaining: int
    rate_limit_per_minute: int
