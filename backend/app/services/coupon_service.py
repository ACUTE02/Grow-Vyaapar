"""Coupons: generate a code for a campaign, validate it, redeem it once."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Campaign
from app.models.commerce import Coupon, CouponRedemption
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext

MAX_PERCENT = Decimal("90")


def suggest_code(occasion: str, discount_value: Decimal, discount_type: str) -> str:
    """DIWALI20 from "Diwali" and 20 percent. Readable beats random on a poster."""
    word = re.sub(r"[^A-Za-z0-9]", "", occasion).upper()[:10] or "OFFER"
    number = int(Decimal(str(discount_value)))
    suffix = f"{number}" if discount_type == "percent" else f"F{number}"
    return f"{word}{suffix}"


def create_coupon(db: Session, context: StoreContext, payload: dict[str, Any]) -> Coupon:
    discount_type = payload.get("discount_type", "percent")
    if discount_type not in ("percent", "flat"):
        raise ValidationError("A coupon is either 'percent' or 'flat'")

    value = Decimal(str(payload["discount_value"]))
    if value <= 0:
        raise ValidationError("A coupon has to take something off the bill")
    if discount_type == "percent" and value > MAX_PERCENT:
        raise ValidationError(
            f"A {value}% coupon would give the shop away. The cap is {MAX_PERCENT}%."
        )

    campaign_id = payload.get("campaign_id")
    campaign = None
    if campaign_id:
        campaign = db.get(Campaign, int(campaign_id))
        if campaign is None or campaign.store_id != context.store_id:
            raise NotFoundError(
                f"Campaign {campaign_id} does not belong to {context.store_name}"
            )

    code = (payload.get("code") or "").strip().upper()
    if not code:
        code = suggest_code(
            campaign.occasion if campaign else "OFFER", value, discount_type
        )

    existing = db.scalar(
        select(Coupon).where(Coupon.store_id == context.store_id, Coupon.code == code)
    )
    if existing is not None:
        raise ConflictError(f"Coupon code {code} already exists at {context.store_name}")

    coupon = Coupon(
        store_id=context.store_id,
        code=code,
        campaign_id=campaign.id if campaign else None,
        discount_type=discount_type,
        discount_value=value,
        valid_from=payload.get("valid_from") or date.today(),
        valid_to=payload.get("valid_to"),
        max_redemptions=int(payload.get("max_redemptions") or 100),
        is_active=True,
    )
    db.add(coupon)
    db.flush()
    return coupon


def validate(db: Session, context: StoreContext, code: str, subtotal: Decimal) -> tuple[Coupon, Decimal]:
    """Return the coupon and what it takes off this bill. Raises if it cannot be used."""
    cleaned = (code or "").strip().upper()
    coupon = db.scalar(
        select(Coupon).where(Coupon.store_id == context.store_id, Coupon.code == cleaned)
    )
    if coupon is None:
        raise NotFoundError(f"No coupon '{cleaned}' at {context.store_name}")
    if not coupon.is_active:
        raise ConflictError(f"Coupon {coupon.code} has been switched off")

    today = date.today()
    if coupon.valid_from and today < coupon.valid_from:
        raise ConflictError(f"Coupon {coupon.code} is not valid until {coupon.valid_from}")
    if coupon.valid_to and today > coupon.valid_to:
        raise ConflictError(f"Coupon {coupon.code} expired on {coupon.valid_to}")
    if coupon.times_redeemed >= coupon.max_redemptions:
        raise ConflictError(
            f"Coupon {coupon.code} has been used {coupon.times_redeemed} times, "
            f"which is its limit of {coupon.max_redemptions}"
        )

    subtotal = Decimal(str(subtotal))
    if coupon.discount_type == "percent":
        amount = (subtotal * Decimal(str(coupon.discount_value)) / Decimal("100")).quantize(
            Decimal("0.01")
        )
    else:
        amount = Decimal(str(coupon.discount_value))
    amount = min(amount, subtotal)
    return coupon, amount


def redeem(
    db: Session,
    coupon: Coupon,
    *,
    transaction_id: int,
    customer_id: int | None,
) -> CouponRedemption:
    coupon.times_redeemed += 1
    redemption = CouponRedemption(
        coupon_id=coupon.id, transaction_id=transaction_id, customer_id=customer_id
    )
    db.add(redemption)
    db.flush()
    return redemption


def release(db: Session, transaction_id: int) -> None:
    """A refund gives the coupon use back."""
    redemptions = db.scalars(
        select(CouponRedemption).where(CouponRedemption.transaction_id == transaction_id)
    ).all()
    for redemption in redemptions:
        coupon = db.get(Coupon, redemption.coupon_id)
        if coupon is not None and coupon.times_redeemed > 0:
            coupon.times_redeemed -= 1
        db.delete(redemption)
    db.flush()


def list_coupons(db: Session, context: StoreContext, limit: int = 50) -> list[Coupon]:
    return list(
        db.scalars(
            select(Coupon)
            .where(Coupon.store_id == context.store_id)
            .order_by(Coupon.id.desc())
            .limit(limit)
        ).all()
    )
