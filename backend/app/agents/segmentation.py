"""Segmentation agent: one SQL pass, thresholds from the StoreContext.

Reads core tables, writes only to segments.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Segment
from app.models.base import utcnow
from app.models.core import Customer, Transaction

SEGMENTS = ("New", "Regular", "VIP", "Inactive")


def classify(
    *,
    recency_days: int | None,
    visits: int,
    total_spend: Decimal,
    average_spend: Decimal,
    inactive_days: int,
    vip_multiplier: float,
    new_customer_max_visits: int,
) -> str:
    """The whole rule set, in one place, driven entirely by numbers."""
    if recency_days is None or recency_days > inactive_days:
        return "Inactive"
    if average_spend > 0 and total_spend > average_spend * Decimal(str(vip_multiplier)):
        return "VIP"
    if visits <= new_customer_max_visits:
        return "New"
    return "Regular"


def rebuild(db: Session, context) -> dict[str, int]:
    """Recompute every customer's segment for this store. Returns the distribution."""
    now = utcnow()
    window_start = now - timedelta(days=90)

    recent = (
        select(
            Transaction.customer_id.label("cid"),
            func.count(Transaction.id).label("recent_visits"),
        )
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.created_at >= window_start,
        )
        .group_by(Transaction.customer_id)
        .subquery()
    )

    lifetime = (
        select(
            Transaction.customer_id.label("cid"),
            func.count(Transaction.id).label("visits"),
            func.max(Transaction.created_at).label("last_at"),
            func.coalesce(func.sum(Transaction.total), 0).label("spend"),
        )
        .where(Transaction.store_id == context.store_id, Transaction.status == "completed")
        .group_by(Transaction.customer_id)
        .subquery()
    )

    rows = db.execute(
        select(
            Customer.id,
            Customer.created_at,
            func.coalesce(lifetime.c.visits, 0),
            lifetime.c.last_at,
            func.coalesce(lifetime.c.spend, 0),
            func.coalesce(recent.c.recent_visits, 0),
        )
        .outerjoin(lifetime, lifetime.c.cid == Customer.id)
        .outerjoin(recent, recent.c.cid == Customer.id)
        .where(Customer.store_id == context.store_id)
    ).all()

    spends = [Decimal(str(row[4])) for row in rows if Decimal(str(row[4])) > 0]
    average_spend = (
        (sum(spends, Decimal("0")) / Decimal(len(spends))) if spends else Decimal("0")
    )

    inactive_days = context.cfg_int("inactive_days", 90)
    vip_multiplier = context.cfg_float("vip_spend_multiplier", 2.0)
    new_max_visits = context.cfg_int("new_customer_max_visits", 1)

    existing = {
        segment.customer_id: segment
        for segment in db.scalars(
            select(Segment).where(Segment.store_id == context.store_id)
        ).all()
    }

    distribution = dict.fromkeys(SEGMENTS, 0)
    for customer_id, created_at, visits, last_at, spend, recent_visits in rows:
        recency_days = _days_since(now, last_at, created_at)
        label = classify(
            recency_days=recency_days,
            visits=int(visits or 0),
            total_spend=Decimal(str(spend or 0)),
            average_spend=average_spend,
            inactive_days=inactive_days,
            vip_multiplier=vip_multiplier,
            new_customer_max_visits=new_max_visits,
        )
        distribution[label] += 1

        segment = existing.get(customer_id)
        if segment is None:
            segment = Segment(store_id=context.store_id, customer_id=customer_id)
            db.add(segment)
        segment.segment = label
        segment.recency_days = recency_days
        segment.frequency_90d = int(recent_visits or 0)
        segment.total_spend = Decimal(str(spend or 0))
        segment.computed_at = now

    db.flush()
    return distribution


def _days_since(now: datetime, last_at: datetime | None, created_at: datetime) -> int | None:
    if last_at is None:
        # Never bought. Age them from the day they were added, so a customer
        # registered yesterday is not filed as lapsed.
        return (now - created_at).days if created_at else None
    if isinstance(last_at, str):
        last_at = datetime.fromisoformat(last_at)
    return (now - last_at).days


def distribution(db: Session, store_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Segment.segment, func.count(Segment.id))
        .where(Segment.store_id == store_id)
        .group_by(Segment.segment)
    ).all()
    counts = dict.fromkeys(SEGMENTS, 0)
    for label, count in rows:
        counts[label] = int(count)
    return counts
