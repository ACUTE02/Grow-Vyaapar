"""Configuration endpoints: verticals, stores and the resolved store context."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.config import (
    MessageTemplate,
    ReminderRule,
    Store,
    StoreConfig,
    Vertical,
)
from app.schemas.config import (
    MessageTemplateOut,
    ReminderRuleOut,
    StoreConfigIn,
    StoreContextOut,
    StoreSummary,
    VerticalOut,
)
from app.verticals.context import StoreContext, get_store_context

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/verticals", response_model=list[VerticalOut])
def list_verticals(db: Session = Depends(get_db)) -> list[Vertical]:
    return list(db.scalars(select(Vertical).order_by(Vertical.code)).all())


@router.get("/stores", response_model=list[StoreSummary])
def list_stores(db: Session = Depends(get_db)) -> list[StoreSummary]:
    rows = db.execute(
        select(Store, Vertical).join(Vertical, Store.vertical_id == Vertical.id).order_by(Store.id)
    ).all()
    return [
        StoreSummary(
            id=store.id,
            name=store.name,
            city=store.city,
            vertical_code=vertical.code,
            vertical_name=vertical.name,
        )
        for store, vertical in rows
    ]


@router.get("/stores/{store_id}/context", response_model=StoreContextOut)
def get_context(context: StoreContext = Depends(get_store_context)) -> StoreContextOut:
    return StoreContextOut(**context.as_dict())


@router.put("/stores/{store_id}/config", response_model=StoreContextOut)
def upsert_store_config(
    payload: StoreConfigIn,
    context: StoreContext = Depends(get_store_context),
    db: Session = Depends(get_db),
) -> StoreContextOut:
    """Override one config key for this store. Overrides win over vertical defaults."""
    row = db.scalar(
        select(StoreConfig).where(
            StoreConfig.store_id == context.store_id, StoreConfig.key == payload.key
        )
    )
    encoded = json.dumps(payload.value)
    if row is None:
        db.add(StoreConfig(store_id=context.store_id, key=payload.key, value=encoded))
    else:
        row.value = encoded
    db.commit()

    from app.verticals.context import resolve_store_context

    return StoreContextOut(**resolve_store_context(db, context.store_id).as_dict())


@router.get("/stores/{store_id}/reminder-rules", response_model=list[ReminderRuleOut])
def list_reminder_rules(
    context: StoreContext = Depends(get_store_context),
    db: Session = Depends(get_db),
) -> list[ReminderRule]:
    return list(
        db.scalars(
            select(ReminderRule)
            .where(ReminderRule.vertical_id == context.vertical_id)
            .order_by(ReminderRule.kind)
        ).all()
    )


@router.get("/templates", response_model=list[MessageTemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[MessageTemplate]:
    return list(
        db.scalars(select(MessageTemplate).order_by(MessageTemplate.template_key)).all()
    )


@router.get("/verticals/{code}", response_model=VerticalOut)
def get_vertical(code: str, db: Session = Depends(get_db)) -> Vertical:
    vertical = db.scalar(select(Vertical).where(Vertical.code == code))
    if vertical is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No vertical with code '{code}'. Seed the verticals table first.",
        )
    return vertical
