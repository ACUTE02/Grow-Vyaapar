"""Tables that support the model layer: prompt cache, training runs, forecasts."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimeStamp, utcnow


class LlmCache(Base):
    """Identical prompt, identical answer, for a configurable window.

    The free tiers we target are rate limited in requests per minute and per day,
    so not asking twice is the cheapest optimisation available.
    """

    __tablename__ = "llm_cache"
    __table_args__ = (Index("ix_llm_cache_hash_created", "prompt_hash", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)


class ModelRun(Base):
    """One training run. Rule 9: every artefact is versioned and reproducible."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(48), nullable=False)
    model_version: Mapped[str] = mapped_column(String(48), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(TimeStamp, nullable=False, default=utcnow)
    rows_trained: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
