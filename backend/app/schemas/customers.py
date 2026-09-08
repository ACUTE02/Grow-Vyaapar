"""Request/response bodies for customers and their append-only records."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PHONE_RE = re.compile(r"^[6-9]\d{9}$")


def normalise_mobile(value: str) -> str:
    """Ten digits, starting 6-9. Shared so an edit is validated exactly as an add."""
    digits = re.sub(r"\D", "", value)[-10:]
    if not PHONE_RE.match(digits):
        raise ValueError(
            f"'{value}' is not a 10-digit Indian mobile number starting with 6-9"
        )
    return digits


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    phone: str = Field(min_length=10, max_length=13)
    dob: date | None = None
    anniversary: date | None = None
    family_head_id: int | None = None
    notes: str | None = None
    marketing_opt_in: bool = True
    referral_code: str | None = None

    @field_validator("phone")
    @classmethod
    def _indian_mobile(cls, value: str) -> str:
        return normalise_mobile(value)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    # A mistyped phone number was previously uncorrectable: the field was absent
    # here, so pydantic dropped it and the PATCH reported 200 having changed
    # nothing. Same validation as CustomerIn, and the service checks the
    # store-unique constraint before writing.
    phone: str | None = Field(default=None, min_length=10, max_length=13)
    dob: date | None = None
    anniversary: date | None = None
    family_head_id: int | None = None
    notes: str | None = None
    marketing_opt_in: bool | None = None

    @field_validator("phone")
    @classmethod
    def _indian_mobile(cls, value: str | None) -> str | None:
        return normalise_mobile(value) if value is not None else None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    name: str
    phone: str
    dob: date | None = None
    anniversary: date | None = None
    family_head_id: int | None = None
    notes: str | None = None
    marketing_opt_in: bool = True
    created_at: datetime


class CustomerListItem(CustomerOut):
    """A customer plus whatever the agent has computed about them."""

    segment: str | None = None
    recency_days: int | None = None
    total_spend: float | None = None
    visits: int = 0


class CustomerRecordIn(BaseModel):
    record_type: str = Field(min_length=2, max_length=48)
    data: dict[str, Any] = Field(default_factory=dict)
    recorded_on: date | None = None


class CustomerRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    record_type: str
    data: dict[str, Any]
    recorded_on: date
