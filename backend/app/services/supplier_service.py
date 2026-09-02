"""Suppliers, purchase orders, and receiving stock into the shelf.

Receiving is the only place stock goes up outside a refund, and it is where
batches come from for verticals that track expiry.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models.admin import PurchaseItem, PurchaseOrder, Supplier
from app.models.base import utcnow
from app.models.core import Batch, Product, StockLevel
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

STATUSES = ("draft", "ordered", "received", "cancelled")


# --------------------------------------------------------------------------- #
# suppliers
# --------------------------------------------------------------------------- #
def list_suppliers(db: Session, context: StoreContext) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            Supplier,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.total), 0),
        )
        .outerjoin(PurchaseOrder, PurchaseOrder.supplier_id == Supplier.id)
        .where(Supplier.store_id == context.store_id)
        .group_by(Supplier.id)
        .order_by(Supplier.name)
    ).all()
    return [
        {
            "id": supplier.id,
            "name": supplier.name,
            "phone": supplier.phone,
            "gstin": supplier.gstin,
            "address": supplier.address,
            "rating": float(supplier.rating) if supplier.rating is not None else None,
            "notes": supplier.notes,
            "orders": int(orders or 0),
            "total_ordered": float(total or 0),
        }
        for supplier, orders, total in rows
    ]


def create_supplier(db: Session, context: StoreContext, payload: dict[str, Any]) -> Supplier:
    rating = payload.get("rating")
    if rating is not None and not (0 <= float(rating) <= 5):
        raise ValidationError("A supplier rating runs from 0 to 5")

    supplier = Supplier(store_id=context.store_id, **payload)
    db.add(supplier)
    db.flush()
    audit.record(
        db,
        action="supplier.create",
        entity="supplier",
        entity_id=supplier.id,
        store_id=context.store_id,
        after={"name": supplier.name, "phone": supplier.phone},
    )
    return supplier


def update_supplier(
    db: Session, context: StoreContext, supplier_id: int, payload: dict[str, Any]
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.store_id != context.store_id:
        raise NotFoundError(f"Supplier {supplier_id} does not belong to {context.store_name}")

    before = {
        "name": supplier.name,
        "phone": supplier.phone,
        "rating": float(supplier.rating) if supplier.rating is not None else None,
    }
    for key, value in payload.items():
        setattr(supplier, key, value)
    db.flush()
    after = {
        "name": supplier.name,
        "phone": supplier.phone,
        "rating": float(supplier.rating) if supplier.rating is not None else None,
    }
    changed_before, changed_after = audit.diff(before, after)
    if changed_after:
        audit.record(
            db,
            action="supplier.update",
            entity="supplier",
            entity_id=supplier.id,
            store_id=context.store_id,
            before=changed_before,
            after=changed_after,
        )
    return supplier


# --------------------------------------------------------------------------- #
# purchase orders
# --------------------------------------------------------------------------- #
def create_order(db: Session, context: StoreContext, payload: dict[str, Any]) -> PurchaseOrder:
    supplier = db.get(Supplier, int(payload["supplier_id"]))
    if supplier is None or supplier.store_id != context.store_id:
        raise NotFoundError(
            f"Supplier {payload['supplier_id']} does not belong to {context.store_name}"
        )

    lines = payload.get("items") or []
    if not lines:
        raise ValidationError("A purchase order needs at least one line")

    order = PurchaseOrder(
        store_id=context.store_id,
        supplier_id=supplier.id,
        status="ordered",
        ordered_at=utcnow(),
        total=Decimal("0.00"),
    )
    db.add(order)
    db.flush()

    total = Decimal("0.00")
    for line in lines:
        product = db.get(Product, int(line["product_id"]))
        if product is None or product.store_id != context.store_id:
            raise NotFoundError(
                f"Product {line['product_id']} is not in the catalog of {context.store_name}"
            )
        quantity = Decimal(str(line["qty"]))
        cost = Decimal(str(line.get("unit_cost") or product.cost_price))
        if quantity <= 0:
            raise ValidationError(f"Quantity for {product.sku} must be more than zero")
        total += quantity * cost
        db.add(
            PurchaseItem(
                purchase_order_id=order.id,
                product_id=product.id,
                qty=quantity,
                unit_cost=cost,
                batch_no=line.get("batch_no"),
                expiry_date=line.get("expiry_date"),
            )
        )

    order.total = total.quantize(Decimal("0.01"))
    db.flush()
    audit.record(
        db,
        action="purchase_order.create",
        entity="purchase_order",
        entity_id=order.id,
        store_id=context.store_id,
        after={"supplier_id": supplier.id, "lines": len(lines), "total": float(order.total)},
    )
    return order


def receive_order(db: Session, context: StoreContext, order_id: int) -> dict[str, Any]:
    """Stock goes up, and batches appear where the vertical tracks expiry."""
    order = db.get(PurchaseOrder, order_id)
    if order is None or order.store_id != context.store_id:
        raise NotFoundError(f"Purchase order {order_id} does not belong to {context.store_name}")
    if order.status == "received":
        raise ConflictError(f"Purchase order {order_id} was already received")
    if order.status == "cancelled":
        raise ConflictError(f"Purchase order {order_id} was cancelled and cannot be received")

    items = db.scalars(
        select(PurchaseItem).where(PurchaseItem.purchase_order_id == order.id)
    ).all()
    tracks_expiry = context.feature("expiry")
    stamp = utcnow()
    batches_created = 0

    for item in items:
        stock = db.scalar(select(StockLevel).where(StockLevel.product_id == item.product_id))
        if stock is None:
            stock = StockLevel(product_id=item.product_id, qty_on_hand=Decimal("0"))
            db.add(stock)
            db.flush()
        stock.qty_on_hand = Decimal(str(stock.qty_on_hand)) + Decimal(str(item.qty))
        stock.last_received_at = stamp

        if tracks_expiry and (item.batch_no or item.expiry_date):
            db.add(
                Batch(
                    product_id=item.product_id,
                    batch_no=item.batch_no or f"PO{order.id}-{item.id}",
                    expiry_date=item.expiry_date,
                    qty=Decimal(str(item.qty)),
                )
            )
            batches_created += 1

    order.status = "received"
    order.received_at = stamp
    db.flush()
    audit.record(
        db,
        action="purchase_order.receive",
        entity="purchase_order",
        entity_id=order.id,
        store_id=context.store_id,
        before={"status": "ordered"},
        after={"status": "received", "lines": len(items), "batches_created": batches_created},
    )
    return {
        "purchase_order_id": order.id,
        "lines_received": len(items),
        "batches_created": batches_created,
        "received_at": stamp,
    }


def list_orders(
    db: Session, context: StoreContext, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    statement = (
        select(PurchaseOrder, Supplier)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(PurchaseOrder.store_id == context.store_id)
    )
    if status:
        statement = statement.where(PurchaseOrder.status == status)
    statement = statement.order_by(PurchaseOrder.id.desc()).limit(limit)

    rows = []
    for order, supplier in db.execute(statement).all():
        lines = db.scalar(
            select(func.count(PurchaseItem.id)).where(
                PurchaseItem.purchase_order_id == order.id
            )
        )
        rows.append(
            {
                "id": order.id,
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "status": order.status,
                "ordered_at": order.ordered_at,
                "received_at": order.received_at,
                "total": float(order.total),
                "is_paid": order.is_paid,
                "lines": int(lines or 0),
            }
        )
    return rows


def mark_paid(db: Session, context: StoreContext, order_id: int) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None or order.store_id != context.store_id:
        raise NotFoundError(f"Purchase order {order_id} does not belong to {context.store_name}")
    if order.is_paid:
        raise ConflictError(f"Purchase order {order_id} is already marked paid")
    order.is_paid = True
    db.flush()
    audit.record(
        db,
        action="purchase_order.pay",
        entity="purchase_order",
        entity_id=order.id,
        store_id=context.store_id,
        before={"is_paid": False},
        after={"is_paid": True, "total": float(order.total)},
    )
    return order


def pending_payments(db: Session, context: StoreContext) -> dict[str, Any]:
    rows = db.execute(
        select(func.count(PurchaseOrder.id), func.coalesce(func.sum(PurchaseOrder.total), 0))
        .where(
            PurchaseOrder.store_id == context.store_id,
            PurchaseOrder.is_paid.is_(False),
            PurchaseOrder.status.in_(("ordered", "received")),
        )
    ).first()
    return {"orders": int(rows[0] or 0), "amount": float(rows[1] or 0)}
