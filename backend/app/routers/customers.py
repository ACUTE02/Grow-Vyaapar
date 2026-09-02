"""Customer endpoints. No business logic here - services do the work."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import Customer, CustomerRecord
from app.schemas.customers import (
    CustomerIn,
    CustomerListItem,
    CustomerOut,
    CustomerRecordIn,
    CustomerRecordOut,
    CustomerUpdate,
)
from app.services import customer_service
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerListItem])
def list_customers(
    q: str | None = Query(default=None, description="name or phone fragment"),
    segment: str | None = Query(default=None, description="New | Regular | VIP | Inactive"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return customer_service.search_customers(
        db, context, query=q, segment=segment, limit=limit, offset=offset
    )


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Customer:
    customer = customer_service.create_customer(db, context, payload.model_dump())
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Customer:
    return customer_service.get_customer(db, context, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Customer:
    customer = customer_service.update_customer(
        db, context, customer_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}/records", response_model=list[CustomerRecordOut])
def list_records(
    customer_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[CustomerRecord]:
    return customer_service.list_records(db, context, customer_id)


@router.post(
    "/{customer_id}/records",
    response_model=CustomerRecordOut,
    status_code=status.HTTP_201_CREATED,
)
def add_record(
    customer_id: int,
    payload: CustomerRecordIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> CustomerRecord:
    record = customer_service.add_record(db, context, customer_id, payload.model_dump())
    db.commit()
    db.refresh(record)
    return record
