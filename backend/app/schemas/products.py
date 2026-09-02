"""Request/response bodies for the catalog."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

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
