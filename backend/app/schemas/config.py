"""Request/response bodies for the configuration router."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# Languages a reminder can actually be written in. The message templates are
# keyed by language and fall back to any template for the same key, so an
# unlisted value would not break a send - it would silently deliver English
# while the settings page claimed otherwise. Controlled here instead.
SUPPORTED_LANGUAGES = ("en", "hi", "hi-en")

# 2-digit state code, 10-character PAN, entity number, a literal Z, checksum.
GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"

# E.164 with the + optional, which is how an Indian shopkeeper writes it.
PHONE_PATTERN = r"^\+?[0-9]{10,15}$"


class StoreDetailsIn(BaseModel):
    """Store identity, as opposed to the vertical configuration next door.

    These are columns on the store row, not thresholds the agent reads, so they
    have their own endpoint rather than being folded into the config one. Only
    the fields actually sent are written, so a form that shows one field cannot
    blank the rest.

    Two fields are non-nullable in the database and stay that way here: a store
    always has a name and a city. The rest can be cleared by sending null or an
    empty string. Unknown fields are rejected outright - store_id and
    vertical_id are not settings, and a payload that tries to move a store
    between tenants should fail loudly rather than be quietly ignored.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=128)
    city: str | None = Field(default=None, min_length=2, max_length=64)
    language: str | None = Field(default=None)
    address: str | None = Field(default=None, max_length=256)
    gstin: str | None = Field(default=None, max_length=20)
    whatsapp_number: str | None = Field(default=None, max_length=20)
    google_review_url: str | None = Field(default=None, max_length=512)

    @field_validator("name", "city")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned

    @field_validator("language")
    @classmethod
    def _known_language(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            raise ValueError(
                f"language must be one of: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        cleaned = value.strip().lower()
        if cleaned not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"'{value}' is not a language this app writes messages in. "
                f"Choose one of: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        return cleaned

    @field_validator("gstin")
    @classmethod
    def _gstin_shape(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip().upper()
        if not cleaned:
            return None
        if not re.match(GSTIN_PATTERN, cleaned):
            raise ValueError(
                "A GSTIN is 15 characters: two state digits, a ten-character PAN, "
                "an entity number, the letter Z, and a check character "
                "(for example 27AAPFU0939F1ZV)."
            )
        return cleaned

    @field_validator("whatsapp_number")
    @classmethod
    def _phone_shape(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip().replace(" ", "").replace("-", "")
        if not cleaned:
            return None
        if not re.match(PHONE_PATTERN, cleaned):
            raise ValueError(
                "A WhatsApp number is 10 to 15 digits, optionally starting with + "
                "(for example +919812345678)."
            )
        return cleaned

    @field_validator("google_review_url")
    @classmethod
    def _url_shape(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("A review link must start with http:// or https://")
        return cleaned

    @field_validator("address")
    @classmethod
    def _blank_address_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


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
