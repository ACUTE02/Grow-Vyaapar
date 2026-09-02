"""Batch handling for verticals whose expiry flag is on.

FEFO - first expired, first out. A chemist and a baker both want the oldest
stock off the shelf first, and neither wants to think about it at the counter,
so allocation happens inside the sale.

Batches are advisory here: stock_levels remains the authority on whether a sale
is possible. If the batch rows do not cover the quantity (older stock received
before batches were tracked), the remainder is recorded as unbatched rather than
blocking the sale.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Batch, Product
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)


def _sorted_batches(db: Session, product_id: int) -> list[Batch]:
    """Earliest expiry first; undated batches last, they are the fallback."""
    batches = db.scalars(
        select(Batch).where(Batch.product_id == product_id, Batch.qty > 0)
    ).all()
    return sorted(
        batches,
        key=(lambda batch: (batch.expiry_date is None, batch.expiry_date or date.max, batch.id)),
    )


def allocate_fefo(db: Session, product_id: int, quantity: Decimal) -> list[dict[str, Any]]:
    """Consume `quantity` from the earliest-expiring batches. Returns what was taken."""
    remaining = Decimal(str(quantity))
    allocation: list[dict[str, Any]] = []

    for batch in _sorted_batches(db, product_id):
        if remaining <= 0:
            break
        available = Decimal(str(batch.qty))
        taken = available if available <= remaining else remaining
        batch.qty = available - taken
        remaining -= taken
        allocation.append(
            {
                "batch_id": batch.id,
                "batch_no": batch.batch_no,
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "qty": float(taken),
            }
        )

    if remaining > 0:
        allocation.append(
            {"batch_id": None, "batch_no": None, "expiry_date": None, "qty": float(remaining)}
        )
        logger.info(
            "Product %s: %s units sold with no batch on record", product_id, remaining
        )

    db.flush()
    return allocation


def restore(db: Session, allocation: list[dict[str, Any]] | None) -> None:
    """Put a refunded quantity back into the batches it came out of."""
    for line in allocation or []:
        batch_id = line.get("batch_id")
        if not batch_id:
            continue
        batch = db.get(Batch, batch_id)
        if batch is not None:
            batch.qty = Decimal(str(batch.qty)) + Decimal(str(line.get("qty", 0)))
    db.flush()


def near_expiry(
    db: Session, context: StoreContext, *, within_days: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Batches expiring inside this vertical's alert window."""
    if not context.feature("expiry"):
        return []

    window = within_days if within_days is not None else context.cfg("near_expiry_days")
    today = date.today()
    statement = (
        select(Batch, Product)
        .join(Product, Product.id == Batch.product_id)
        .where(
            Product.store_id == context.store_id,
            Batch.qty > 0,
            Batch.expiry_date.is_not(None),
        )
        .order_by(Batch.expiry_date.asc())
        .limit(limit)
    )
    if window is not None:
        statement = statement.where(Batch.expiry_date <= today + timedelta(days=int(window)))

    return [
        {
            "batch_id": batch.id,
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "batch_no": batch.batch_no,
            "expiry_date": batch.expiry_date,
            "days_left": (batch.expiry_date - today).days,
            "qty": float(batch.qty),
            "unit_label": context.unit_label,
            "value": float(Decimal(str(batch.qty)) * Decimal(str(product.sell_price))),
            "is_expired": batch.expiry_date < today,
        }
        for batch, product in db.execute(statement).all()
    ]


def alert_count(db: Session, context: StoreContext) -> int:
    """How many batches are inside the alert window, or zero if there is none."""
    if not context.feature("expiry") or context.cfg("near_expiry_days") is None:
        return 0
    return len(near_expiry(db, context))
