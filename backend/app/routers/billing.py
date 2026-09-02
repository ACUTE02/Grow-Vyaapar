"""POS endpoints: create a sale, read it back, print it, refund it, roll it up."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.observability import set_pagination
from app.models.core import Customer, Product, Transaction, TransactionItem
from app.schemas.billing import (
    RollupIn,
    RollupOut,
    SaleIn,
    TransactionListItem,
    TransactionOut,
)
from app.services import billing_service, finance_rollup, invoice_pdf
from app.services.errors import NotFoundError
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/billing", tags=["billing"])


def _serialise(db: Session, context: StoreContext, transaction: Transaction) -> dict:
    lines = []
    for item in transaction.items:
        product = db.get(Product, item.product_id)
        lines.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "sku": product.sku if product else None,
                "name": product.name if product else None,
                "qty": item.qty,
                "unit_price": item.unit_price,
                "line_discount": item.line_discount,
                "line_total": item.line_total,
            }
        )
    customer_name = None
    if transaction.customer_id:
        customer = db.get(Customer, transaction.customer_id)
        customer_name = customer.name if customer else None
    return {
        "id": transaction.id,
        "store_id": transaction.store_id,
        "customer_id": transaction.customer_id,
        "customer_name": customer_name,
        "invoice_no": transaction.invoice_no,
        "subtotal": transaction.subtotal,
        "discount": transaction.discount,
        "gst_amount": transaction.gst_amount,
        "total": transaction.total,
        "payment_mode": transaction.payment_mode,
        "status": transaction.status,
        "created_at": transaction.created_at,
        "unit_label": context.unit_label,
        "lines": lines,
    }


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: SaleIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """One DB transaction: items written and stock decremented, or nothing at all."""
    try:
        transaction = billing_service.create_sale(
            db,
            context,
            lines=[line.model_dump() for line in payload.lines],
            customer_id=payload.customer_id,
            discount=payload.discount,
            payment_mode=payload.payment_mode,
            coupon_code=payload.coupon_code,
            redeem_points=payload.redeem_points,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(transaction)
    from app.agents import reminders as reminder_agent  # noqa: PLC0415

    # The agent is not asked; a completed sale is a signal it listens for.
    reminder_agent.on_transaction_completed(db, context, transaction.id)
    return _serialise(db, context, transaction)


@router.get("/transactions", response_model=list[TransactionListItem])
def list_transactions(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    customer_id: int | None = None,
    response: Response = None,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    counts = (
        select(
            TransactionItem.transaction_id.label("tid"),
            func.count(TransactionItem.id).label("item_count"),
        )
        .group_by(TransactionItem.transaction_id)
        .subquery()
    )
    statement = (
        select(Transaction, Customer.name, counts.c.item_count)
        .outerjoin(Customer, Customer.id == Transaction.customer_id)
        .outerjoin(counts, counts.c.tid == Transaction.id)
        .where(Transaction.store_id == context.store_id)
    )
    if customer_id:
        statement = statement.where(Transaction.customer_id == customer_id)
    total = db.scalar(
        select(func.count(Transaction.id)).where(Transaction.store_id == context.store_id)
    )
    statement = statement.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)

    rows = [
        {
            "id": transaction.id,
            "invoice_no": transaction.invoice_no,
            "customer_name": customer_name,
            "total": transaction.total,
            "payment_mode": transaction.payment_mode,
            "status": transaction.status,
            "created_at": transaction.created_at,
            "item_count": int(item_count or 0),
        }
        for transaction, customer_name, item_count in db.execute(statement).all()
    ]
    set_pagination(response, total=total, limit=limit, offset=offset, returned=len(rows))
    return rows


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.store_id != context.store_id:
        raise NotFoundError(f"Invoice {transaction_id} does not belong to {context.store_name}")
    return _serialise(db, context, transaction)


@router.get("/transactions/{transaction_id}/invoice.pdf")
def invoice_as_pdf(
    transaction_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Response:
    """PDF when WeasyPrint is installed, otherwise the same invoice as HTML."""
    pdf = invoice_pdf.render_invoice_pdf(db, context, transaction_id)
    if pdf is not None:
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="invoice-{transaction_id}.pdf"'
            },
        )
    html = invoice_pdf.render_invoice_html(db, context, transaction_id)
    return Response(content=html, media_type="text/html", headers={"X-Pdf-Fallback": "html"})


@router.get("/transactions/{transaction_id}/invoice.html")
def invoice_as_html(
    transaction_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Response:
    return Response(
        content=invoice_pdf.render_invoice_html(db, context, transaction_id),
        media_type="text/html",
    )


@router.post("/transactions/{transaction_id}/refund", response_model=TransactionOut)
def refund(
    transaction_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    try:
        transaction = billing_service.refund_sale(db, context, transaction_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(transaction)
    return _serialise(db, context, transaction)


@router.post("/rollup", response_model=RollupOut)
def rollup(
    payload: RollupIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    end = payload.end or date.today()
    start = payload.start or (end - timedelta(days=550))
    rows = finance_rollup.rebuild_daily_summary(db, context.store_id, start, end)
    db.commit()
    return {"store_id": context.store_id, "days": len(rows), "start": start, "end": end}
