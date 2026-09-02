"""Insights agent: Python computes every number, the model only narrates them.

Reads core tables, writes only to insights.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import segmentation
from app.llm import client as llm
from app.llm import prompts
from app.models.agent import Insight
from app.models.base import utcnow
from app.models.core import DailySalesSummary, Product, ProductCategory, Transaction, TransactionItem
from app.services import stock_service
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

CACHE_HOURS = 24


def _money(value: Any) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def compute_metrics(db: Session, context: StoreContext) -> dict[str, Any]:
    """Every figure the narrator is allowed to use, computed in SQL/Python."""
    today = date.today()
    this_week_start = today - timedelta(days=7)
    last_week_start = today - timedelta(days=14)

    def window_totals(start: date, end: date) -> tuple[float, int, int]:
        row = db.execute(
            select(
                func.coalesce(func.sum(Transaction.total), 0),
                func.count(Transaction.id),
                func.count(func.distinct(Transaction.customer_id)),
            ).where(
                Transaction.store_id == context.store_id,
                Transaction.status == "completed",
                Transaction.created_at >= datetime.combine(start, time.min),
                Transaction.created_at < datetime.combine(end, time.min),
            )
        ).first()
        return _money(row[0]), int(row[1] or 0), int(row[2] or 0)

    this_sales, this_invoices, this_customers = window_totals(this_week_start, today)
    last_sales, last_invoices, _ = window_totals(last_week_start, this_week_start)

    change_pct = 0.0
    if last_sales > 0:
        change_pct = round((this_sales - last_sales) / last_sales * 100, 1)
    elif this_sales > 0:
        change_pct = 100.0

    segments = segmentation.distribution(db, context.store_id)

    low = stock_service.low_stock(db, context, limit=5)
    dead = stock_service.dead_stock(db, context, limit=5)

    top_rows = db.execute(
        select(
            ProductCategory.name,
            func.coalesce(func.sum(TransactionItem.line_total), 0).label("revenue"),
        )
        .join(Product, Product.category_id == ProductCategory.id)
        .join(TransactionItem, TransactionItem.product_id == Product.id)
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.created_at >= datetime.combine(today - timedelta(days=30), time.min),
        )
        .group_by(ProductCategory.name)
        .order_by(func.sum(TransactionItem.line_total).desc())
        .limit(3)
    ).all()

    trend = [
        {"date": str(row.date), "net": _money(row.net), "invoices": row.invoices}
        for row in db.scalars(
            select(DailySalesSummary)
            .where(
                DailySalesSummary.store_id == context.store_id,
                DailySalesSummary.date >= today - timedelta(days=30),
            )
            .order_by(DailySalesSummary.date)
        ).all()
    ]

    average_bill = round(this_sales / this_invoices, 2) if this_invoices else 0.0

    return {
        "store_name": context.store_name,
        "city": context.city,
        "week_sales": this_sales,
        "previous_week_sales": last_sales,
        "week_over_week_change_pct": change_pct,
        "week_invoices": this_invoices,
        "previous_week_invoices": last_invoices,
        "week_unique_customers": this_customers,
        "average_bill_value": average_bill,
        "segments": segments,
        "low_stock_count": len(low),
        "low_stock": [
            {
                "sku": row.sku,
                "name": row.name,
                "qty_on_hand": float(row.qty_on_hand),
                "reorder_point": float(row.reorder_point),
                "unit": row.unit_label,
            }
            for row in low
        ],
        "dead_stock_window_days": context.cfg_int("dead_stock_days", 90),
        "dead_stock_count": len(dead),
        "dead_stock": [
            {
                "sku": row.sku,
                "name": row.name,
                "qty_on_hand": float(row.qty_on_hand),
                "days_since_sold": row.days_since_sold,
                "value": _money(row.qty_on_hand * row.sell_price),
            }
            for row in dead
        ],
        "top_categories_30d": [
            {"category": name, "revenue": _money(revenue)} for name, revenue in top_rows
        ],
        "sales_trend_30d": trend,
        "inactive_days_threshold": context.cfg_int("inactive_days", 90),
    }


def template_suggestions(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """The non-LLM path. Same three slots, written by Python from the same figures."""
    change = metrics["week_over_week_change_pct"]
    direction = "up" if change >= 0 else "down"
    suggestions = [
        {
            "title": f"Weekly sales are {direction} {abs(change)}%",
            "detail": (
                f"This week's sales are INR {metrics['week_sales']:,.0f} against "
                f"INR {metrics['previous_week_sales']:,.0f} last week, across "
                f"{metrics['week_invoices']} bills. Check the days that dipped and plan "
                "staffing for the evening peak."
            ),
            "figure": f"INR {metrics['week_sales']:,.0f} this week",
            "action": "customers",
        }
    ]
    if metrics["low_stock"]:
        first = metrics["low_stock"][0]
        suggestions.append(
            {
                "title": f"{metrics['low_stock_count']} items are at or below reorder point",
                "detail": (
                    f"{first['name']} (SKU {first['sku']}) is down to "
                    f"{first['qty_on_hand']:g} {first['unit']} against a reorder point of "
                    f"{first['reorder_point']:g}. Raise a purchase order before the weekend."
                ),
                "figure": f"{first['qty_on_hand']:g} {first['unit']} of {first['sku']}",
                "action": "low_stock",
            }
        )
    if metrics["dead_stock"]:
        first = metrics["dead_stock"][0]
        suggestions.append(
            {
                "title": f"{metrics['dead_stock_count']} SKUs have not sold in "
                f"{metrics['dead_stock_window_days']} days",
                "detail": (
                    f"{first['name']} (SKU {first['sku']}) has INR {first['value']:,.0f} "
                    f"of stock sitting unsold for {first['days_since_sold']} days. "
                    "Put it in this week's campaign or move it to the front counter."
                ),
                "figure": f"INR {first['value']:,.0f} idle in {first['sku']}",
                "action": "dead_stock",
            }
        )
    inactive = metrics["segments"].get("Inactive", 0)
    if len(suggestions) < 3:
        suggestions.append(
            {
                "title": f"{inactive} customers have gone quiet",
                "detail": (
                    f"{inactive} customers have not bought in "
                    f"{metrics['inactive_days_threshold']} days. Run the reminder check and "
                    "send the win-back messages waiting in the outbox."
                ),
                "figure": f"{inactive} inactive customers",
                "action": "outbox",
            }
        )
    return suggestions[:3]


def _cached(db: Session, store_id: int) -> Insight | None:
    return db.scalar(
        select(Insight)
        .where(Insight.store_id == store_id)
        .order_by(Insight.generated_at.desc())
        .limit(1)
    )


def generate(
    db: Session, context: StoreContext, *, force: bool = False
) -> tuple[Insight, str]:
    """Return the store's insight row and where it came from: llm, template or cache."""
    cached = _cached(db, context.store_id)
    if cached is not None and not force:
        age = utcnow() - cached.generated_at
        if age < timedelta(hours=CACHE_HOURS):
            return cached, "cache"

    try:
        metrics = compute_metrics(db, context)
    except Exception:
        logger.exception("Metric computation failed for store %s", context.store_id)
        if cached is not None:
            return cached, "cache"
        raise

    source = "template"
    suggestions = template_suggestions(metrics)

    if llm.available():
        text = llm.call(prompts.insights_prompt(context, metrics), max_tokens=700, db=db)
        parsed = prompts.parse_json_block(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("suggestions"), list):
            cleaned = [
                {
                    "title": str(item.get("title", ""))[:120],
                    "detail": str(item.get("detail", ""))[:600],
                    "figure": str(item.get("figure", ""))[:120] or None,
                    "action": str(item.get("action", "")) or None,
                }
                for item in parsed["suggestions"]
                if isinstance(item, dict) and item.get("title") and item.get("detail")
            ][:3]
            if len(cleaned) == 3:
                suggestions = cleaned
                source = "llm"

    insight = Insight(
        store_id=context.store_id,
        period=f"week-ending-{date.today().isoformat()}",
        metrics_json=metrics,
        suggestions_json=suggestions,
        generated_at=utcnow(),
    )
    db.add(insight)
    db.flush()
    return insight, source
