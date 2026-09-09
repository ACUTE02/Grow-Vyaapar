"""Request/response bodies for the catalog."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=96)
    parent_id: int | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    name: str
    parent_id: int | None = None


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=2, max_length=160)
    category_id: int | None = None
    hsn_code: str | None = None
    cost_price: Decimal = Decimal("0.00")
    sell_price: Decimal = Decimal("0.00")
    gst_rate: Decimal = Decimal("0.00")
    attributes: dict[str, Any] = Field(default_factory=dict)
    image_url: str | None = None
    is_active: bool = True
    qty_on_hand: Decimal = Decimal("0")
    reorder_point: Decimal = Decimal("0")


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    category_id: int | None = None
    hsn_code: str | None = None
    cost_price: Decimal | None = None
    sell_price: Decimal | None = None
    gst_rate: Decimal | None = None
    attributes: dict[str, Any] | None = None
    image_url: str | None = None
    is_active: bool | None = None
    qty_on_hand: Decimal | None = None
    reorder_point: Decimal | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    sku: str
    name: str
    category_id: int | None = None
    category_name: str | None = None
    hsn_code: str | None = None
    cost_price: Decimal
    sell_price: Decimal
    gst_rate: Decimal
    attributes: dict[str, Any]
    image_url: str | None = None
    is_active: bool
    qty_on_hand: Decimal = Decimal("0")
    reorder_point: Decimal = Decimal("0")
    unit_label: str = "piece"


class StockRowOut(BaseModel):
    product_id: int
    sku: str
    name: str
    qty_on_hand: Decimal
    reorder_point: Decimal
    unit_label: str
    days_since_sold: int | None = None
    sell_price: Decimal


# Why a count changed. A controlled list rather than free text, because "why"
# is the whole point of the record: a shelf that lost six units to breakage and
# one that lost six to a miscount are different problems, and a typed box
# collects neither. Validated by the API, never taken on the UI's word.
ADJUSTMENT_REASONS = (
    "damaged",
    "lost",
    "found",
    "expired",
    "stock_count",
    "manual_correction",
    "other",
)
AdjustmentReason = Literal[
    "damaged", "lost", "found", "expired", "stock_count", "manual_correction", "other"
]


class StockAdjustmentIn(BaseModel):
    """A deliberate correction to a count.

    The product comes from the path and the store from the authorised context,
    so neither is in this body. Unknown fields are refused rather than ignored:
    nothing here should be able to reach a column that is not an adjustment.
    """

    model_config = ConfigDict(extra="forbid")

    # Signed: positive found it, negative lost it. Zero is refused, because an
    # adjustment that adjusts nothing is a mistake worth telling someone about
    # rather than an audit row saying nothing happened.
    quantity_delta: Decimal = Field(
        description="Signed change. Positive adds stock, negative removes it. Never zero."
    )
    reason: AdjustmentReason
    note: str | None = Field(default=None, max_length=280)


class StockAdjustmentOut(BaseModel):
    product_id: int
    sku: str
    name: str
    unit_label: str
    qty_before: Decimal
    quantity_delta: Decimal
    qty_after: Decimal
    reason: str
    note: str | None = None
    adjusted_at: datetime
    adjusted_by: int | None = None
