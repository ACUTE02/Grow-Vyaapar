"""Rebuild daily_sales_summary for a date range, in SQL."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.core import DailySalesSummary, Transaction


def rebuild_daily_summary(
    db: Session, store_id: int, start: date, end: date
) -> list[DailySalesSummary]:
    """Delete and recompute the summary rows for [start, end] inclusive."""
    if start > end:
        start, end = end, start

    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end + timedelta(days=1), time.min)

    db.execute(
        delete(DailySalesSummary).where(
            DailySalesSummary.store_id == store_id,
            DailySalesSummary.date >= start,
            DailySalesSummary.date <= end,
        )
    )

    day = func.date(Transaction.created_at)
    rows = db.execute(
        select(
            day.label("day"),
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.subtotal), 0),
            func.coalesce(func.sum(Transaction.discount), 0),
            func.coalesce(func.sum(Transaction.total), 0),
            func.count(func.distinct(Transaction.customer_id)),
        )
        .where(
            Transaction.store_id == store_id,
            Transaction.status == "completed",
            Transaction.created_at >= window_start,
            Transaction.created_at < window_end,
        )
        .group_by(day)
        .order_by(day)
    ).all()

    # First-ever purchase date per customer, so "new" means new to this store.
    first_seen = dict(
        db.execute(
            select(Transaction.customer_id, func.date(func.min(Transaction.created_at)))
            .where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
                Transaction.customer_id.is_not(None),
            )
            .group_by(Transaction.customer_id)
        ).all()
    )
    new_per_day: dict[str, int] = {}
    for first_day in first_seen.values():
        key = str(first_day)
        new_per_day[key] = new_per_day.get(key, 0) + 1

    summaries: list[DailySalesSummary] = []
    for day_value, invoices, gross, discount, net, uniques in rows:
        day_key = str(day_value)
        summary = DailySalesSummary(
            store_id=store_id,
            date=date.fromisoformat(day_key),
            invoices=int(invoices or 0),
            gross=gross or 0,
            discount=discount or 0,
            net=net or 0,
            unique_customers=int(uniques or 0),
            new_customers=new_per_day.get(day_key, 0),
        )
        db.add(summary)
        summaries.append(summary)

    db.flush()
    return summaries


def rebuild_all(db: Session, store_id: int, days: int = 550) -> list[DailySalesSummary]:
    today = date.today()
    return rebuild_daily_summary(db, store_id, today - timedelta(days=days), today)
