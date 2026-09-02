"""Agent-owned tables. Only app/agents/* writes to these."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    Index,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimeStamp, utcnow


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("store_id", "customer_id", name="uq_segment_store_customer"),
        Index("ix_segments_store_segment", "store_id", "segment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    recency_days: Mapped[int | None] = mapped_column(Integer)
    frequency_90d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_spend: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    computed_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)

    customer: Mapped["object"] = relationship("Customer")


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_rule", "rule_id"),
        Index("ix_reminders_store_status_kind", "store_id", "status", "kind"),
        Index("ix_reminders_store_sent", "store_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("reminder_rules.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="whatsapp")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(TimeStamp)
    sent_at: Mapped[datetime | None] = mapped_column(TimeStamp)
    # Whatever the provider said, success or failure, kept verbatim.
    provider_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)

    customer: Mapped["object"] = relationship("Customer")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    occasion: Mapped[str] = mapped_column(String(96), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    suggestions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class ChurnScore(Base):
    """One row per customer per scoring run of agents/churn.py."""

    __tablename__ = "churn_scores"
    __table_args__ = (Index("ix_churn_store_risk", "store_id", "risk_level"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    model_version: Mapped[str | None] = mapped_column(String(32))
    scored_at: Mapped[date | None] = mapped_column(Date)
