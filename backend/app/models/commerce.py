"""Coupons, loyalty, referrals and campaign attribution."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimeStamp, utcnow


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("store_id", "code", name="uq_coupon_store_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    discount_type: Mapped[str] = mapped_column(String(16), nullable=False, default="percent")
    discount_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    max_redemptions: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    times_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), nullable=False, index=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), nullable=False, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    redeemed_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class CampaignStat(Base):
    """Last-touch attribution over a fixed window. Not causal proof, and labelled so."""

    __tablename__ = "campaign_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), nullable=False, index=True
    )
    messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customers_reached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visits_attributed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue_attributed: Mapped[Decimal] = mapped_column(
        Money, nullable=False, default=Decimal("0.00")
    )
    coupons_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class LoyaltyAccount(Base):
    """The balance is derived from the ledger and never edited directly."""

    __tablename__ = "loyalty_accounts"
    __table_args__ = (
        UniqueConstraint("store_id", "customer_id", name="uq_loyalty_store_customer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class LoyaltyLedger(Base):
    __tablename__ = "loyalty_ledger"
    __table_args__ = (Index("ix_loyalty_ledger_account", "loyalty_account_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loyalty_account_id: Mapped[int] = mapped_column(
        ForeignKey("loyalty_accounts.id"), nullable=False
    )
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_referral_store_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    referrer_customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    referred_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="issued")
    notes: Mapped[str | None] = mapped_column(Text)
    rewarded_at: Mapped[datetime | None] = mapped_column(TimeStamp)
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)
