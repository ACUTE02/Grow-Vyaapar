"""Catalog endpoints, including the two stock lists the dashboard links to."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import ProductCategory
from app.schemas.products import (
    CategoryIn,
    CategoryOut,
    ProductIn,
    ProductOut,
    ProductUpdate,
    StockRowOut,
)
from app.services import product_service, stock_service
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


# -- products ----------------------------------------------------------------
@router.get("", response_model=list[ProductOut])
def list_products(
    q: str | None = Query(default=None, description="name or SKU fragment"),
    category_id: int | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return product_service.search_products(
        db,
        context,
        query=q,
        category_id=category_id,
        active_only=not include_inactive,
        limit=limit,
        offset=offset,
    )


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
