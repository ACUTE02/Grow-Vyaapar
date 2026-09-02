"""The single place configuration is read.

Services and agents receive a resolved StoreContext. They never query the
verticals or store_config tables themselves.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.config import Store, StoreConfig, Vertical


class StoreNotFound(Exception):
    def __init__(self, store_id: int) -> None:
        super().__init__(f"Store {store_id} does not exist")
        self.store_id = store_id


def _coerce(raw: str) -> Any:
    """store_config values are text; parse JSON scalars where possible."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


@dataclass(frozen=True)
class StoreContext:
    """Everything vertical-shaped, resolved once per request."""

    store_id: int
    store_name: str
    city: str
    language: str
    gstin: str | None
    google_review_url: str | None
    whatsapp_number: str | None

    vertical_id: int
    vertical_code: str
    vertical_name: str

    config: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    unit_labels: dict[str, Any] = field(default_factory=dict)
    product_schema: dict[str, Any] = field(default_factory=dict)
    prompt_profile: dict[str, Any] = field(default_factory=dict)

    # -- accessors -----------------------------------------------------------
    def cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def cfg_int(self, key: str, default: int = 0) -> int:
        value = self.config.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def cfg_float(self, key: str, default: float = 0.0) -> float:
        value = self.config.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def feature(self, name: str) -> bool:
        return bool(self.feature_flags.get(name, False))

    @property
    def unit_label(self) -> str:
        return str(self.unit_labels.get("default", "piece"))

    @property
    def unit_options(self) -> list[str]:
        options = self.unit_labels.get("options") or [self.unit_label]
        return [str(option) for option in options]

    def as_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "store_name": self.store_name,
            "city": self.city,
            "language": self.language,
            "gstin": self.gstin,
            "google_review_url": self.google_review_url,
            "whatsapp_number": self.whatsapp_number,
            "vertical_id": self.vertical_id,
            "vertical_code": self.vertical_code,
            "vertical_name": self.vertical_name,
            "config": self.config,
            "feature_flags": self.feature_flags,
            "unit_labels": self.unit_labels,
            "product_schema": self.product_schema,
            "prompt_profile": self.prompt_profile,
        }


def resolve_store_context(db: Session, store_id: int) -> StoreContext:
    """Merge vertical defaults with per-store overrides. Raises StoreNotFound."""
    row = db.execute(
        select(Store, Vertical).join(Vertical, Store.vertical_id == Vertical.id).where(
            Store.id == store_id
        )
    ).first()
    if row is None:
        raise StoreNotFound(store_id)
    store, vertical = row

    config: dict[str, Any] = dict(vertical.default_config or {})
    overrides = db.scalars(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    ).all()
    for override in overrides:
        config[override.key] = _coerce(override.value)

    return StoreContext(
        store_id=store.id,
        store_name=store.name,
        city=store.city,
        language=store.language,
        gstin=store.gstin,
        google_review_url=store.google_review_url,
        whatsapp_number=store.whatsapp_number,
        vertical_id=vertical.id,
        vertical_code=vertical.code,
        vertical_name=vertical.name,
        config=config,
        feature_flags=dict(vertical.feature_flags or {}),
        unit_labels=dict(vertical.unit_labels or {}),
        product_schema=dict(vertical.product_schema or {}),
        prompt_profile=dict(vertical.prompt_profile or {}),
    )


def get_store_context(
    store_id: int = Path(..., ge=1, description="Store the request acts on"),
    db: Session = Depends(get_db),
) -> StoreContext:
    """FastAPI dependency for routes with a {store_id} path parameter."""
    try:
        return resolve_store_context(db, store_id)
    except StoreNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def get_store_context_from_query(
    store_id: int,
    db: Session = Depends(get_db),
) -> StoreContext:
    """FastAPI dependency for routes that take store_id as a query parameter."""
    try:
        return resolve_store_context(db, store_id)
    except StoreNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
