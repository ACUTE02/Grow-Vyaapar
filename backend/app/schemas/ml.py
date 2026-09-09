"""Request/response bodies for the model layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class ChurnScoreOut(BaseModel):
    customer_id: int
    name: str
    phone: str | None = None
    probability: float
    risk_level: str
    segment: str | None = None
    recency_days: int | None = None
    total_spend: float | None = None
    model_version: str | None = None
    scored_at: date | None = None


class ChurnTrainOut(BaseModel):
    store_id: int
    model_name: str
    model_version: str
    metrics: dict[str, Any]
    scored: int
    bands: dict[str, int] = {}


class ModelRunOut(BaseModel):
    id: int
    model_name: str
    model_version: str
    trained_at: datetime
    rows_trained: int
    metrics: dict[str, Any]
    params: dict[str, Any]


class QueueWinbackOut(BaseModel):
    store_id: int
    queued: int


class StockForecastOut(BaseModel):
    product_id: int
    sku: str
    name: str
    qty_on_hand: float
    unit_label: str
    predicted_daily_velocity: float
    days_to_stockout: float | None = None
    suggested_reorder_qty: float
    is_dead_stock_risk: bool
    reason: str
    source: str = "estimate"          # "model" | "estimate" - which one produced this row
    computed_at: datetime | None = None


class ForecastRunOut(BaseModel):
    store_id: int
    products: int
    window_days: int
    reorder_soon: int
    dead_stock_risk: int
    computed_at: datetime


class StockForecastStatusOut(BaseModel):
    """Is a trained regressor behind the reorder numbers, and if not, why not."""

    trained: bool
    in_use: bool
    explanation: str
    model_name: str | None = None
    model_version: str | None = None
    trained_at: datetime | None = None
    rows_trained: int | None = None
    mae: float | None = None
    baseline_mae: float | None = None
    r2: float | None = None


class StockForecastTrainOut(BaseModel):
    store_id: int
    model_name: str
    model_version: str
    metrics: dict[str, Any]
