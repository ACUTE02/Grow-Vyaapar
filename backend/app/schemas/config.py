"""Request/response bodies for the configuration router."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VerticalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    unit_labels: dict[str, Any]
    default_config: dict[str, Any]
    feature_flags: dict[str, bool]
    product_schema: dict[str, Any]
    prompt_profile: dict[str, Any]


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str
    vertical_id: int
    gstin: str | None = None
    google_review_url: str | None = None
    whatsapp_number: str | None = None
    language: str


class StoreSummary(BaseModel):
    """What the store selector needs, without a second round trip."""

    id: int
    name: str
    city: str
    vertical_code: str
    vertical_name: str


class StoreContextOut(BaseModel):
    store_id: int
    store_name: str
    city: str
    address: str | None = None
    language: str
    gstin: str | None = None
    google_review_url: str | None = None
    whatsapp_number: str | None = None
    vertical_id: int
    vertical_code: str
    vertical_name: str
    config: dict[str, Any]
    feature_flags: dict[str, bool]
    unit_labels: dict[str, Any]
    product_schema: dict[str, Any]
    prompt_profile: dict[str, Any]


class StoreConfigIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: Any


class StoreDetailsIn(BaseModel):
    """Store identity, as opposed to the vertical configuration next door.

    An address is not a threshold the agent reads, so it belongs on the store
    row rather than in store_config - and it needs its own way in.
    """

    address: str | None = Field(default=None, max_length=256)
    whatsapp_number: str | None = Field(default=None, max_length=20)
    google_review_url: str | None = Field(default=None, max_length=512)


class ReminderRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vertical_id: int
    kind: str
    signal: str
    offset_days: int
    template_key: str
    channel: str
    enabled: bool


class MessageTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_key: str
    language: str
    body: str
    llm_instruction: str | None = None
