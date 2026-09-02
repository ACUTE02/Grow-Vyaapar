"""Campaign attribution.

Reads core tables, writes only campaign_stats.

This is last-touch attribution over a fixed window, and the UI says so in those
words. If a customer received a message from the shop after a campaign was
drafted and then bought something within the window, the visit is counted
against that campaign. That is a correlation with a plausible mechanism, not
proof the campaign caused the visit - there is no control group here and there
cannot be one in a single shop.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.agent import Campaign, Reminder
from app.models.base import utcnow
from app.models.commerce import CampaignStat, Coupon, CouponRedemption
from app.models.core import Transaction
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW_DAYS = 14
METHOD = (
    f"last-touch, {ATTRIBUTION_WINDOW_DAYS}-day window from the campaign date; "
    "correlation, not causation"
)


def compute_for_campaign(
    db: Session, context: StoreContext, campaign: Campaign
) -> dict[str, Any]:
    window_end = campaign.created_at + timedelta(days=ATTRIBUTION_WINDOW_DAYS)

    reached_rows = db.execute(
        select(Reminder.customer_id, func.count(Reminder.id))
        .where(
            Reminder.store_id == context.store_id,
            Reminder.status == "sent",
            Reminder.sent_at.is_not(None),
            Reminder.sent_at >= campaign.created_at,
            Reminder.sent_at < window_end,
        )
        .group_by(Reminder.customer_id)
    ).all()
    reached = {customer_id for customer_id, _ in reached_rows}
    messages_sent = sum(count for _, count in reached_rows)

    visits = 0
    revenue = Decimal("0.00")
    if reached:
        row = db.execute(
            select(
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.total), 0),
            ).where(
                Transaction.store_id == context.store_id,
                Transaction.status == "completed",
                Transaction.customer_id.in_(reached),
                Transaction.created_at >= campaign.created_at,
                Transaction.created_at < window_end,
            )
        ).first()
        visits = int(row[0] or 0)
        revenue = Decimal(str(row[1] or 0))

    coupons_redeemed = int(
        db.scalar(
            select(func.count(CouponRedemption.id))
            .join(Coupon, Coupon.id == CouponRedemption.coupon_id)
            .where(Coupon.campaign_id == campaign.id)
        )
        or 0
    )

    return {
        "campaign_id": campaign.id,
        "occasion": campaign.occasion,
        "created_at": campaign.created_at,
        "messages_sent": messages_sent,
        "customers_reached": len(reached),
        "visits_attributed": visits,
        "revenue_attributed": revenue,
        "coupons_redeemed": coupons_redeemed,
        "conversion_rate": round(visits / len(reached), 3) if reached else 0.0,
        "method": METHOD,
    }


def run(db: Session, context: StoreContext) -> dict[str, Any]:
    """Recompute stats for every campaign this store has drafted."""
    campaigns = db.scalars(
        select(Campaign).where(Campaign.store_id == context.store_id)
    ).all()

    stamp = utcnow()
    computed = 0
    for campaign in campaigns:
        stats = compute_for_campaign(db, context, campaign)
        db.execute(delete(CampaignStat).where(CampaignStat.campaign_id == campaign.id))
        db.add(
            CampaignStat(
                campaign_id=campaign.id,
                messages_sent=stats["messages_sent"],
                customers_reached=stats["customers_reached"],
                visits_attributed=stats["visits_attributed"],
                revenue_attributed=stats["revenue_attributed"],
                coupons_redeemed=stats["coupons_redeemed"],
                computed_at=stamp,
            )
        )
        computed += 1

    db.flush()
    return {"store_id": context.store_id, "campaigns": computed, "computed_at": stamp}


def performance(db: Session, context: StoreContext, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Campaign, CampaignStat)
        .outerjoin(CampaignStat, CampaignStat.campaign_id == Campaign.id)
        .where(Campaign.store_id == context.store_id)
        .order_by(Campaign.created_at.desc())
        .limit(limit)
    ).all()

    results = []
    for campaign, stat in rows:
        reached = stat.customers_reached if stat else 0
        visits = stat.visits_attributed if stat else 0
        results.append(
            {
                "campaign_id": campaign.id,
                "occasion": campaign.occasion,
                "status": campaign.status,
                "created_at": campaign.created_at,
                "messages_sent": stat.messages_sent if stat else 0,
                "customers_reached": reached,
                "visits_attributed": visits,
                "revenue_attributed": float(stat.revenue_attributed) if stat else 0.0,
                "coupons_redeemed": stat.coupons_redeemed if stat else 0,
                "conversion_rate": round(visits / reached, 3) if reached else 0.0,
                "computed_at": stat.computed_at if stat else None,
                "method": METHOD,
            }
        )
    return results
