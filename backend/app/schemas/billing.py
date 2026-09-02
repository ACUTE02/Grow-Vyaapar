"""Request/response bodies for billing."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SaleLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_price: Decimal | None = None
    line_discount: Decimal = Decimal("0.00")


class SaleIn(BaseModel):
    customer_id: int | None = None
    lines: list[SaleLineIn] = Field(min_length=1)
    discount: Decimal = Decimal("0.00")
    payment_mode: str = "cash"
    coupon_code: str | None = None
    redeem_points: int = Field(default=0, ge=0)


class SaleLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    sku: str | None = None
    name: str | None = None
    qty: Decimal
    unit_price: Decimal
    line_discount: Decimal
    line_total: Decimal


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    customer_id: int | None = None
    customer_name: str | None = None
    invoice_no: str
    subtotal: Decimal
    discount: Decimal
    gst_amount: Decimal
    total: Decimal
    payment_mode: str
    status: str
    created_at: datetime
    unit_label: str = "piece"
    lines: list[SaleLineOut] = []


class TransactionListItem(BaseModel):
    id: int
    invoice_no: str
    customer_name: str | None = None
    total: Decimal
    payment_mode: str
    status: str
    created_at: datetime
    item_count: int


class RollupIn(BaseModel):
    start: date | None = None
    end: date | None = None


class RollupOut(BaseModel):
    store_id: int
    days: int
    start: date
    end: date
