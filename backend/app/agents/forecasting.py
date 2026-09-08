"""Forecasting agent: how fast each SKU moves, and what that implies.

Reads core tables, writes only to stock_forecasts.

The method is a day-of-week weighted moving average, and it is worth being
straight about that: it is not ARIMA, not Prophet, not a neural anything. Over a
few hundred SKUs of counter trade it is the honest choice - it needs no tuning,
it degrades gracefully on sparse data, and every number it produces can be
explained to a shopkeeper in one sentence.

What makes it useful is not the maths but the framing: the phase-1 dead-stock
list reports what already died. This predicts what is about to.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.ml import stock_forecast_model
from app.models.base import utcnow
from app.models.core import Product, StockLevel, Transaction, TransactionItem
from app.models.ml import StockForecast
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MIN_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 180
SAFETY_FACTOR = 1.2
FADING_RATIO = 0.35        # recent velocity below this share of earlier velocity
APPROACHING_SHARE = 0.6    # ... and already this far into the dead-stock window


@dataclass
class Forecast:
    product_id: int
    sku: str
    name: str
    qty_on_hand: float
    unit_label: str
    predicted_daily_velocity: float
    days_to_stockout: float | None
    suggested_reorder_qty: float
    is_dead_stock_risk: bool
    reason: str
    source: str = "estimate"          # "model" (trained regressor) | "estimate" (moving average)


def window_days(context: StoreContext) -> int:
    """Look back over roughly two reorder cycles, clamped to something sane."""
    cycle = context.cfg_int("reorder_cycle_days", 30)
    return max(MIN_WINDOW_DAYS, min(cycle * 2, MAX_WINDOW_DAYS))


def _sales_by_day(db: Session, context: StoreContext, days: int) -> dict[int, dict[date, float]]:
    start = datetime.combine(date.today() - timedelta(days=days), time.min)
    statement: Select = (
        select(
            TransactionItem.product_id,
            func.date(Transaction.created_at),
            func.sum(TransactionItem.qty),
        )
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.created_at >= start,
        )
        .group_by(TransactionItem.product_id, func.date(Transaction.created_at))
    )
    sales: dict[int, dict[date, float]] = {}
    for product_id, day, quantity in db.execute(statement).all():
        day_value = day if isinstance(day, date) else date.fromisoformat(str(day))
        sales.setdefault(product_id, {})[day_value] = float(quantity or 0)
    return sales


def weekday_factors(sales: dict[int, dict[date, float]], days: int) -> dict[int, float]:
    """How much busier a Saturday is than a Tuesday, for this store as a whole.

    Per-SKU weekday factors would be noise on this much data, so the shape is
    taken from the whole shop and applied to each product's own average.
    """
    totals: dict[int, float] = {index: 0.0 for index in range(7)}
    counts: dict[int, int] = {index: 0 for index in range(7)}
    today = date.today()
    for offset in range(days):
        day = today - timedelta(days=offset + 1)
        counts[day.weekday()] += 1
    for per_day in sales.values():
        for day, quantity in per_day.items():
            totals[day.weekday()] += quantity

    daily_means = {
        weekday: (totals[weekday] / counts[weekday] if counts[weekday] else 0.0)
        for weekday in range(7)
    }
    overall = sum(daily_means.values()) / 7 or 0.0
    if overall <= 0:
        return {weekday: 1.0 for weekday in range(7)}
    return {weekday: (value / overall) or 1.0 for weekday, value in daily_means.items()}


def days_until_empty(
    qty_on_hand: float, daily_velocity: float, factors: dict[int, float], horizon: int = 400
) -> float | None:
    """Walk forward day by day, spending the weekday-weighted velocity."""
    if daily_velocity <= 0:
        return None
    remaining = qty_on_hand
    day = date.today()
    for step in range(1, horizon + 1):
        day = day + timedelta(days=1)
        remaining -= daily_velocity * factors.get(day.weekday(), 1.0)
        if remaining <= 0:
            return float(step)
    # Past the simulated horizon the weekday shape averages out, so a plain
    # division is accurate enough - and far more useful than saying "unknown"
    # about a shelf that simply holds three years of cover.
    return round(qty_on_hand / daily_velocity, 2)


def _pack_round(quantity: float, attributes: dict[str, Any]) -> float:
    """Round up to something a supplier will actually deliver."""
    if quantity <= 0:
        return 0.0
    pack = 0.0
    for key in ("pack_size", "case_size", "box_size"):
        raw = (attributes or {}).get(key)
        if raw is None:
            continue
        digits = "".join(
            character for character in str(raw) if character.isdigit() or character == "."
        )
        try:
            pack = float(digits)
        except ValueError:
            pack = 0.0
        if pack > 0:
            break
    if pack <= 0:
        pack = 1.0 if quantity < 20 else 5.0
    return float(int((quantity + pack - 0.001) // pack) * pack)


def compute(db: Session, context: StoreContext) -> list[Forecast]:
    """Forecast every active product. Pure computation, no writes."""
    days = window_days(context)
    half = max(days // 2, 7)
    sales = _sales_by_day(db, context, days)
    factors = weekday_factors(sales, days)

    dead_stock_days = context.cfg_int("dead_stock_days", 90)
    reorder_cycle = context.cfg_int("reorder_cycle_days", 30)
    today = date.today()
    now = utcnow()
    split = today - timedelta(days=half)

    # A trained model's own prediction, for the products it has enough history
    # to be trusted on; everyone else keeps the moving average. Never lets a
    # scoring problem break the forecast - the moving average is always safe.
    try:
        model_predictions = stock_forecast_model.predict_weekly_units(db, context)
    except Exception:
        logger.exception(
            "Stock forecast model scoring failed for store %s, using the moving average",
            context.store_id,
        )
        model_predictions = {}

    rows = db.execute(
        select(Product, StockLevel)
        .outerjoin(StockLevel, StockLevel.product_id == Product.id)
        .where(Product.store_id == context.store_id, Product.is_active.is_(True))
    ).all()

    forecasts: list[Forecast] = []
    for product, stock in rows:
        per_day = sales.get(product.id, {})
        sold_total = sum(per_day.values())
        historical_velocity = sold_total / days if days else 0.0

        recent = sum(quantity for day, quantity in per_day.items() if day >= split)
        earlier = sum(quantity for day, quantity in per_day.items() if day < split)
        recent_velocity = recent / half if half else 0.0
        earlier_velocity = earlier / max(days - half, 1)

        qty_on_hand = float(stock.qty_on_hand) if stock else 0.0
        last_sold = stock.last_sold_at if stock else None
        idle_days = (now - last_sold).days if last_sold else None

        predicted_weekly = model_predictions.get(product.id)
        if predicted_weekly is not None:
            velocity, source = predicted_weekly / 7.0, "model"
        else:
            velocity, source = historical_velocity, "estimate"

        stockout = days_until_empty(qty_on_hand, velocity, factors)

        fading = (
            earlier_velocity > 0
            and recent_velocity <= earlier_velocity * FADING_RATIO
        )
        approaching = (
            idle_days is not None
            and idle_days >= dead_stock_days * APPROACHING_SHARE
            and idle_days < dead_stock_days
        )
        # Whether this SKU has genuinely never sold is a fact about its actual
        # sales history, not about what a model predicts next week - always
        # judged from the real velocity, regardless of which one drives the
        # reorder math below.
        never_moved = historical_velocity <= 0 and qty_on_hand > 0
        # Already past the window is not a prediction, it is the phase-1 report.
        already_dead = idle_days is not None and idle_days >= dead_stock_days

        dead_risk = bool(
            qty_on_hand > 0
            and not already_dead
            and (never_moved or fading or approaching)
        )

        if never_moved:
            reason = f"no sales in the last {days} days"
        elif approaching and fading:
            reason = (
                f"sales fading and last sold {idle_days} days ago, "
                f"against a {dead_stock_days}-day window"
            )
        elif approaching:
            reason = f"last sold {idle_days} days ago, {dead_stock_days}-day window"
        elif fading:
            reason = (
                f"velocity fell from {earlier_velocity:.2f} to {recent_velocity:.2f} "
                f"per day over the last {half} days"
            )
        elif stockout is not None and stockout <= reorder_cycle:
            reason = f"runs out in {stockout:.0f} days, inside the {reorder_cycle}-day cycle"
        else:
            reason = "healthy"

        suggested = 0.0
        if velocity > 0 and stockout is not None and stockout <= reorder_cycle:
            suggested = _pack_round(
                velocity * reorder_cycle * SAFETY_FACTOR - qty_on_hand, product.attributes
            )

        forecasts.append(
            Forecast(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                qty_on_hand=qty_on_hand,
                unit_label=context.unit_label,
                predicted_daily_velocity=round(velocity, 4),
                days_to_stockout=round(stockout, 2) if stockout is not None else None,
                suggested_reorder_qty=suggested,
                is_dead_stock_risk=dead_risk,
                reason=reason,
                source=source,
            )
        )

    forecasts.sort(
        key=lambda item: (
            item.days_to_stockout if item.days_to_stockout is not None else 10_000
        )
    )
    return forecasts


def run(db: Session, context: StoreContext) -> dict[str, Any]:
    """Compute and persist. Replaces this store's previous forecast rows."""
    forecasts = compute(db, context)
    db.execute(delete(StockForecast).where(StockForecast.store_id == context.store_id))
    stamp = utcnow()
    for forecast in forecasts:
        db.add(
            StockForecast(
                store_id=context.store_id,
                product_id=forecast.product_id,
                days_to_stockout=(
                    Decimal(str(forecast.days_to_stockout))
                    if forecast.days_to_stockout is not None
                    else None
                ),
                predicted_daily_velocity=Decimal(str(forecast.predicted_daily_velocity)),
                suggested_reorder_qty=Decimal(str(forecast.suggested_reorder_qty)),
                is_dead_stock_risk=forecast.is_dead_stock_risk,
                computed_at=stamp,
            )
        )
    db.flush()

    reorder_cycle = context.cfg_int("reorder_cycle_days", 30)
    urgent = [
        item
        for item in forecasts
        if item.days_to_stockout is not None and item.days_to_stockout <= reorder_cycle
    ]
    return {
        "store_id": context.store_id,
        "products": len(forecasts),
        "window_days": window_days(context),
        "reorder_soon": len(urgent),
        "dead_stock_risk": sum(1 for item in forecasts if item.is_dead_stock_risk),
        "computed_at": stamp,
    }


def reorder_list(db: Session, context: StoreContext, limit: int = 50) -> list[Forecast]:
    reorder_cycle = context.cfg_int("reorder_cycle_days", 30)
    return [
        item
        for item in compute(db, context)
        if item.days_to_stockout is not None and item.days_to_stockout <= reorder_cycle
    ][:limit]


def dead_stock_risk(db: Session, context: StoreContext, limit: int = 50) -> list[Forecast]:
    """Predicted to die, not yet dead: the list phase 1 could not produce."""
    at_risk = [item for item in compute(db, context) if item.is_dead_stock_risk]
    at_risk.sort(key=lambda item: item.qty_on_hand, reverse=True)
    return at_risk[:limit]
