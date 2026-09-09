"""Configuration tables. Vertical behaviour lives here as data, never as code."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimeStamp, utcnow


class Vertical(Base):
    __tablename__ = "verticals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_labels: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    feature_flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    product_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prompt_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    stores: Mapped[list["Store"]] = relationship(back_populates="vertical")
    reminder_rules: Mapped[list["ReminderRule"]] = relationship(back_populates="vertical")


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vertical_id: Mapped[int] = mapped_column(ForeignKey("verticals.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    # Street address, for the bottom of a printed poster. Optional: a store
    # that has not filled it in simply gets one fewer line.
    address: Mapped[str | None] = mapped_column(String(256))
    gstin: Mapped[str | None] = mapped_column(String(20))
    google_review_url: Mapped[str | None] = mapped_column(String(512))
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)

    vertical: Mapped[Vertical] = relationship(back_populates="stores")
    config_rows: Mapped[list["StoreConfig"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )


class StoreConfig(Base):
    """Per-store overrides merged over the vertical's default_config."""

    __tablename__ = "store_config"
    __table_args__ = (UniqueConstraint("store_id", "key", name="uq_store_config_store_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    store: Mapped[Store] = relationship(back_populates="config_rows")


class ReminderRule(Base):
    __tablename__ = "reminder_rules"
    __table_args__ = (
        UniqueConstraint("vertical_id", "kind", name="uq_reminder_rule_vertical_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vertical_id: Mapped[int] = mapped_column(ForeignKey("verticals.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    signal: Mapped[str] = mapped_column(String(48), nullable=False)
    offset_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="whatsapp")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    vertical: Mapped[Vertical] = relationship(back_populates="reminder_rules")


class MessageTemplate(Base):
    """Non-LLM fallback copy. Every template_key used by a rule has a row here."""

    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "language", name="uq_template_key_language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    llm_instruction: Mapped[str | None] = mapped_column(Text)
