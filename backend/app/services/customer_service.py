"""Customer search, creation and the append-only record log."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.agent import Segment
from app.models.core import Customer, CustomerRecord, Transaction
from app.services.errors import ConflictError, NotFoundError
from app.verticals.context import StoreContext


def search_customers(
    db: Session,
    context: StoreContext,
    *,
    query: str | None = None,
    segment: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search by name or phone, optionally filtered by the agent's segment."""
    spend = (
        select(
            Transaction.customer_id.label("cid"),
            func.count(Transaction.id).label("visits"),
            func.coalesce(func.sum(Transaction.total), 0).label("spend"),
        )
        .where(Transaction.store_id == context.store_id, Transaction.status == "completed")
        .group_by(Transaction.customer_id)
        .subquery()
    )

    statement = (
        select(Customer, Segment, spend.c.visits, spend.c.spend)
        .outerjoin(Segment, Segment.customer_id == Customer.id)
        .outerjoin(spend, spend.c.cid == Customer.id)
        .where(Customer.store_id == context.store_id)
    )
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(Customer.name.ilike(pattern), Customer.phone.ilike(pattern))
        )
    if segment:
        statement = statement.where(Segment.segment == segment)

    statement = statement.order_by(Customer.name).limit(limit).offset(offset)

    rows: list[dict[str, Any]] = []
    for customer, segment_row, visits, total in db.execute(statement).all():
        rows.append(
            {
                "id": customer.id,
                "store_id": customer.store_id,
                "name": customer.name,
                "phone": customer.phone,
                "dob": customer.dob,
                "anniversary": customer.anniversary,
                "family_head_id": customer.family_head_id,
                "notes": customer.notes,
                "marketing_opt_in": customer.marketing_opt_in,
                "created_at": customer.created_at,
                "segment": segment_row.segment if segment_row else None,
                "recency_days": segment_row.recency_days if segment_row else None,
                "total_spend": float(total or 0),
                "visits": int(visits or 0),
            }
        )
    return rows


def get_customer(db: Session, context: StoreContext, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.store_id != context.store_id:
        raise NotFoundError(f"Customer {customer_id} is not registered at {context.store_name}")
    return customer


def create_customer(db: Session, context: StoreContext, payload: dict[str, Any]) -> Customer:
    existing = db.scalar(
        select(Customer).where(
            Customer.store_id == context.store_id, Customer.phone == payload["phone"]
        )
    )
    if existing is not None:
        raise ConflictError(
            f"Phone {payload['phone']} already belongs to {existing.name} "
            f"(customer {existing.id}) at this store"
        )
    if payload.get("family_head_id"):
        get_customer(db, context, int(payload["family_head_id"]))

    customer = Customer(store_id=context.store_id, **payload)
    db.add(customer)
    db.flush()
    return customer


def update_customer(
    db: Session, context: StoreContext, customer_id: int, payload: dict[str, Any]
) -> Customer:
    customer = get_customer(db, context, customer_id)
    if payload.get("family_head_id"):
        if int(payload["family_head_id"]) == customer_id:
            raise ConflictError("A customer cannot be their own family head")
        get_customer(db, context, int(payload["family_head_id"]))
    for key, value in payload.items():
        setattr(customer, key, value)
    db.flush()
    return customer


def list_records(db: Session, context: StoreContext, customer_id: int) -> list[CustomerRecord]:
    get_customer(db, context, customer_id)
    return list(
        db.scalars(
            select(CustomerRecord)
            .where(CustomerRecord.customer_id == customer_id)
            .order_by(CustomerRecord.recorded_on.desc(), CustomerRecord.id.desc())
        ).all()
    )


def add_record(
    db: Session, context: StoreContext, customer_id: int, payload: dict[str, Any]
) -> CustomerRecord:
    """Records are append-only: a correction is a new row, never an UPDATE."""
    get_customer(db, context, customer_id)
    record = CustomerRecord(
        customer_id=customer_id,
        record_type=payload["record_type"],
        data=payload.get("data") or {},
        recorded_on=payload.get("recorded_on") or date.today(),
    )
    db.add(record)
    db.flush()
    return record
