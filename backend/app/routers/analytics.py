"""Read-only analytics for the dashboard. Every number comes from SQL."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import insights as insight_agent
from app.db import get_db
from app.models.core import DailySalesSummary, Product, ProductCategory, Transaction, TransactionItem
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(
    days: int = Query(default=30, ge=1, le=550),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Headline figures plus the daily series the dashboard plots."""
    start = date.today() - timedelta(days=days)
    rows = db.scalars(
        select(DailySalesSummary)
        .where(
            DailySalesSummary.store_id == context.store_id,
            DailySalesSummary.date >= start,
        )
        .order_by(DailySalesSummary.date)
    ).all()

    series = [
        {
            "date": str(row.date),
            "net": float(row.net),
            "gross": float(row.gross),
            "invoices": row.invoices,
            "unique_customers": row.unique_customers,
            "new_customers": row.new_customers,
        }
        for row in rows
    ]
    net_total = sum(item["net"] for item in series)
    invoices = sum(item["invoices"] for item in series)

    return {
        "store_id": context.store_id,
        "store_name": context.store_name,
        "vertical_name": context.vertical_name,
        "unit_label": context.unit_label,
        "days": days,
        "net_total": round(net_total, 2),
        "invoices": invoices,
        "average_bill": round(net_total / invoices, 2) if invoices else 0.0,
        "series": series,
    }


@router.get("/top-products")
def top_products(
    days: int = Query(default=30, ge=1, le=550),
    limit: int = Query(default=10, ge=1, le=50),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    start = date.today() - timedelta(days=days)
    rows = db.execute(
        select(
            Product.sku,
            Product.name,
            ProductCategory.name,
            func.sum(TransactionItem.qty),
            func.sum(TransactionItem.line_total),
        )
        .join(TransactionItem, TransactionItem.product_id == Product.id)
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            func.date(Transaction.created_at) >= start,
        )
        .group_by(Product.id)
        .order_by(func.sum(TransactionItem.line_total).desc())
        .limit(limit)
    ).all()

    return [
        {
            "sku": sku,
            "name": name,
            "category": category,
            "qty": float(qty or 0),
            "revenue": float(revenue or 0),
            "unit_label": context.unit_label,
        }
        for sku, name, category, qty, revenue in rows
    ]


@router.get("/metrics")
def metrics(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """The exact figures handed to the model, with no model involved."""
    return insight_agent.compute_metrics(db, context)
