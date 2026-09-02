"""Catalog endpoints, including the two stock lists the dashboard links to."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.observability import MAX_LIMIT, set_pagination
from sqlalchemy import select

from app.models.core import Batch, Product, ProductCategory
from app.schemas.products import (
    CategoryIn,
    CategoryOut,
    ProductIn,
    ProductOut,
    ProductUpdate,
    StockRowOut,
)
from app.services import batch_service, product_service, stock_service
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/products", tags=["products"])


# -- categories (declared before /{product_id} so the paths do not collide) ---
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[ProductCategory]:
    return product_service.list_categories(db, context)


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> ProductCategory:
    category = product_service.create_category(db, context, payload.model_dump())
    db.commit()
    db.refresh(category)
    return category


# -- stock lists -------------------------------------------------------------
@router.get("/low-stock", response_model=list[StockRowOut])
def low_stock(
    limit: int = Query(default=50, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [asdict(row) for row in stock_service.low_stock(db, context, limit=limit)]


@router.get("/dead-stock", response_model=list[StockRowOut])
def dead_stock(
    limit: int = Query(default=50, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Not sold within this store's own dead_stock_days window."""
    return [asdict(row) for row in stock_service.dead_stock(db, context, limit=limit)]


@router.get("/expiring")
def expiring(
    within_days: int | None = Query(
        default=None, ge=1, le=720,
        description="defaults to this vertical's near_expiry_days; omit for every dated batch",
    ),
    limit: int = Query(default=200, ge=1, le=500),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Batches ordered by expiry, with this vertical's own alert window applied."""
    window = within_days if within_days is not None else context.cfg("near_expiry_days")
    rows = batch_service.near_expiry(db, context, within_days=window, limit=limit)
    return {
        "store_id": context.store_id,
        "tracks_expiry": context.feature("expiry"),
        "near_expiry_days": context.cfg("near_expiry_days"),
        "window_days": window,
        "alert_count": sum(1 for row in rows if row["days_left"] <= (window or 0)),
        "expired_count": sum(1 for row in rows if row["is_expired"]),
        "batches": rows,
    }


# -- products ----------------------------------------------------------------
@router.get("", response_model=list[ProductOut])
def list_products(
    q: str | None = Query(default=None, description="name or SKU fragment"),
    category_id: int | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    response: Response = None,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = product_service.search_products(
        db,
        context,
        query=q,
        category_id=category_id,
        active_only=not include_inactive,
        limit=limit,
        offset=offset,
    )
    set_pagination(response, total=None, limit=limit, offset=offset, returned=len(rows))
    return rows


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    product = product_service.create_product(db, context, payload.model_dump())
    db.commit()
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    return product_service.get_product_out(db, context, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    product = product_service.update_product(
        db, context, product_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    return product
