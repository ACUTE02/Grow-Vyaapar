"""Stock queries. Thresholds come from the resolved StoreContext, never from a name."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.core import Product, StockLevel
from app.verticals.context import StoreContext


@dataclass(frozen=True)
class StockRow:
    product_id: int
    sku: str
    name: str
    qty_on_hand: Decimal
    reorder_point: Decimal
    unit_label: str
    days_since_sold: int | None
    sell_price: Decimal


def _row(product: Product, stock: StockLevel, context: StoreContext) -> StockRow:
    days: int | None = None
    if stock.last_sold_at is not None:
        days = (utcnow() - stock.last_sold_at).days
    return StockRow(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        qty_on_hand=Decimal(str(stock.qty_on_hand)),
        reorder_point=Decimal(str(stock.reorder_point)),
        unit_label=context.unit_label,
        days_since_sold=days,
        sell_price=Decimal(str(product.sell_price)),
    )


def low_stock(db: Session, context: StoreContext, limit: int = 50) -> list[StockRow]:
    rows = db.execute(
        select(Product, StockLevel)
        .join(StockLevel, StockLevel.product_id == Product.id)
        .where(
            Product.store_id == context.store_id,
            Product.is_active.is_(True),
            StockLevel.qty_on_hand <= StockLevel.reorder_point,
        )
        .order_by(StockLevel.qty_on_hand.asc())
        .limit(limit)
    ).all()
    return [_row(product, stock, context) for product, stock in rows]


def dead_stock(db: Session, context: StoreContext, limit: int = 50) -> list[StockRow]:
    """Not sold within this store's dead_stock_days window."""
    cutoff = utcnow() - timedelta(days=context.cfg_int("dead_stock_days", 90))
    rows = db.execute(
        select(Product, StockLevel)
        .join(StockLevel, StockLevel.product_id == Product.id)
        .where(
            Product.store_id == context.store_id,
            Product.is_active.is_(True),
            StockLevel.qty_on_hand > 0,
            or_(StockLevel.last_sold_at.is_(None), StockLevel.last_sold_at < cutoff),
        )
        .order_by(StockLevel.last_sold_at.asc().nulls_first())
        .limit(limit)
    ).all()
    return [_row(product, stock, context) for product, stock in rows]


def overstocked(db: Session, context: StoreContext, limit: int = 3) -> list[StockRow]:
    """The SKUs a campaign should push: sitting longest with the most stock on hand."""
    candidates = dead_stock(db, context, limit=limit * 10)
    candidates.sort(key=lambda row: (row.qty_on_hand * row.sell_price), reverse=True)
    return candidates[:limit]
