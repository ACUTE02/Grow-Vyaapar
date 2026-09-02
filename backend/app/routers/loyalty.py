"""Coupons, loyalty and referrals - the things that make a campaign measurable."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import coupon_service, loyalty_service
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/loyalty", tags=["loyalty"])


# -- schemas -----------------------------------------------------------------
class CouponIn(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    campaign_id: int | None = None
    discount_type: str = "percent"
    discount_value: Decimal
    valid_from: date | None = None
    valid_to: date | None = None
    max_redemptions: int = Field(default=100, ge=1, le=100000)


class CouponOut(BaseModel):
    id: int
    code: str
    campaign_id: int | None = None
    discount_type: str
    discount_value: Decimal
    valid_from: date | None = None
    valid_to: date | None = None
    max_redemptions: int
    times_redeemed: int
    is_active: bool


class CouponQuoteOut(BaseModel):
    code: str
    discount_type: str
    discount_value: Decimal
    amount_off: Decimal
    times_redeemed: int
    max_redemptions: int


class LedgerEntryOut(BaseModel):
    id: int
    points_delta: int
    reason: str
    transaction_id: int | None = None
    created_at: Any


class LoyaltyOut(BaseModel):
    customer_id: int
    points_balance: int
    lifetime_points: int
    point_value: float
    rupees_per_point: int
    ledger: list[LedgerEntryOut]


class ReferralOut(BaseModel):
    id: int
    code: str
    referrer_customer_id: int
    referrer_name: str | None = None
    referred_customer_id: int | None = None
    status: str
    rewarded_at: Any | None = None
    created_at: Any


# -- coupons -----------------------------------------------------------------
@router.post("/coupons", response_model=CouponOut, status_code=http_status.HTTP_201_CREATED)
def create_coupon(
    payload: CouponIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Any:
    coupon = coupon_service.create_coupon(db, context, payload.model_dump())
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/coupons", response_model=list[CouponOut])
def list_coupons(
    limit: int = Query(default=50, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Any:
    return coupon_service.list_coupons(db, context, limit=limit)


@router.get("/coupons/{code}/quote", response_model=CouponQuoteOut)
def quote_coupon(
    code: str,
    subtotal: Decimal = Query(..., gt=0, description="bill value before this coupon"),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """What this code would take off, without redeeming it."""
    coupon, amount = coupon_service.validate(db, context, code, subtotal)
    return {
        "code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "amount_off": amount,
        "times_redeemed": coupon.times_redeemed,
        "max_redemptions": coupon.max_redemptions,
    }


# -- loyalty -----------------------------------------------------------------
@router.get("/customers/{customer_id}", response_model=LoyaltyOut)
def loyalty_for_customer(
    customer_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    return loyalty_service.history(db, context, customer_id)


# -- referrals ---------------------------------------------------------------
@router.post("/referrals/{customer_id}", response_model=ReferralOut)
def issue_referral_code(
    customer_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    referral = loyalty_service.referral_code_for(db, context, customer_id)
    db.commit()
    db.refresh(referral)
    return {
        "id": referral.id,
        "code": referral.code,
        "referrer_customer_id": referral.referrer_customer_id,
        "referrer_name": None,
        "referred_customer_id": referral.referred_customer_id,
        "status": referral.status,
        "rewarded_at": referral.rewarded_at,
        "created_at": referral.created_at,
    }


@router.get("/referrals", response_model=list[ReferralOut])
def list_referrals(
    limit: int = Query(default=50, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return loyalty_service.list_referrals(db, context, limit=limit)
