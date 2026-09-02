"""Suppliers, purchase orders and receiving. Manager and above."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.services import supplier_service
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/purchasing", tags=["purchasing"])


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    rating: Decimal | None = None
    notes: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    rating: Decimal | None = None
    notes: str | None = None


class SupplierOut(BaseModel):
    id: int
    name: str
    phone: str | None = None
    gstin: str | None = None
    address: str | None = None
    rating: float | None = None
    notes: str | None = None
    orders: int = 0
    total_ordered: float = 0.0


class PurchaseLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_cost: Decimal | None = None
    batch_no: str | None = None
    expiry_date: date | None = None


class PurchaseOrderIn(BaseModel):
    supplier_id: int
    items: list[PurchaseLineIn] = Field(min_length=1)


class PurchaseOrderOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str | None = None
    status: str
    ordered_at: datetime | None = None
    received_at: datetime | None = None
    total: float
    is_paid: bool = False
    lines: int = 0


class ReceiveOut(BaseModel):
    purchase_order_id: int
    lines_received: int
    batches_created: int
    received_at: datetime


# -- suppliers ---------------------------------------------------------------
@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return supplier_service.list_suppliers(db, context)


@router.post("/suppliers", response_model=SupplierOut, status_code=http_status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    supplier = supplier_service.create_supplier(db, context, payload.model_dump())
    db.commit()
    return next(
        row for row in supplier_service.list_suppliers(db, context) if row["id"] == supplier.id
    )


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    supplier_service.update_supplier(
        db, context, supplier_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    return next(
        row for row in supplier_service.list_suppliers(db, context) if row["id"] == supplier_id
    )


# -- purchase orders ---------------------------------------------------------
@router.get("/orders", response_model=list[PurchaseOrderOut])
def list_orders(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return supplier_service.list_orders(db, context, status=status, limit=limit)


@router.post("/orders", response_model=PurchaseOrderOut, status_code=http_status.HTTP_201_CREATED)
def create_order(
    payload: PurchaseOrderIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    order = supplier_service.create_order(
        db,
        context,
        {
            "supplier_id": payload.supplier_id,
            "items": [line.model_dump() for line in payload.items],
        },
    )
    db.commit()
    return next(row for row in supplier_service.list_orders(db, context) if row["id"] == order.id)


@router.post("/orders/{order_id}/receive", response_model=ReceiveOut)
def receive_order(
    order_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Stock goes up and, where the vertical tracks expiry, batches are created."""
    result = supplier_service.receive_order(db, context, order_id)
    db.commit()
    return result


@router.post("/orders/{order_id}/pay", response_model=PurchaseOrderOut)
def mark_paid(
    order_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    supplier_service.mark_paid(db, context, order_id)
    db.commit()
    return next(row for row in supplier_service.list_orders(db, context) if row["id"] == order_id)


@router.get("/pending-payments")
def pending_payments(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    return supplier_service.pending_payments(db, context)


# -- the trail ---------------------------------------------------------------
@router.get("/audit")
def audit_trail(
    limit: int = Query(default=100, ge=1, le=500),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "action": row.action,
            "entity": row.entity,
            "entity_id": row.entity_id,
            "user_id": row.user_id,
            "before": row.before,
            "after": row.after,
            "created_at": row.created_at,
        }
        for row in audit.for_store(db, context.store_id, limit=limit)
    ]
