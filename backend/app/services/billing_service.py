"""Billing: totals arithmetic and the transactional sale/refund flow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from app.services import batch_service
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext

TWOPLACES = Decimal("0.01")
QTYPLACES = Decimal("0.001")


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def qty(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(QTYPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineInput:
    product_id: int
    qty: Decimal
    unit_price: Decimal
    line_discount: Decimal = Decimal("0.00")
    gst_rate: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class ComputedLine:
    product_id: int
    qty: Decimal
    unit_price: Decimal
    line_discount: Decimal
    line_total: Decimal
    gst_amount: Decimal


@dataclass(frozen=True)
class ComputedTotals:
    lines: list[ComputedLine]
    subtotal: Decimal
    discount: Decimal
    gst_amount: Decimal
    total: Decimal


def compute_totals(lines: list[LineInput], order_discount: Decimal) -> ComputedTotals:
    """Pure arithmetic, shared by the API and the seed script.

    Prices are GST-exclusive. The order-level discount is allocated across lines
    pro rata, then GST is charged on the discounted line value.
    """
    if not lines:
        raise ValidationError("A transaction needs at least one line item")

    computed_raw: list[tuple[LineInput, Decimal]] = []
    for line in lines:
        if line.qty <= 0:
            raise ValidationError(f"Quantity for product {line.product_id} must be greater than 0")
        if line.unit_price < 0:
            raise ValidationError(f"Unit price for product {line.product_id} cannot be negative")
        gross = money(qty(line.qty) * money(line.unit_price))
        line_total = money(gross - money(line.line_discount))
        if line_total < 0:
            raise ValidationError(
                f"Line discount for product {line.product_id} exceeds the line value "
                f"({money(line.line_discount)} on {gross})"
            )
        computed_raw.append((line, line_total))

    subtotal = money(sum((total for _, total in computed_raw), Decimal("0.00")))
    discount = money(order_discount or 0)
    if discount < 0:
        raise ValidationError("Discount cannot be negative")
    if discount > subtotal:
        raise ValidationError(
            f"Discount {discount} is larger than the bill subtotal {subtotal}"
        )

    computed: list[ComputedLine] = []
    allocated = Decimal("0.00")
    gst_total = Decimal("0.00")
    for index, (line, line_total) in enumerate(computed_raw):
        if subtotal > 0 and discount > 0:
            if index == len(computed_raw) - 1:
                share = money(discount - allocated)      # last line absorbs rounding
            else:
                share = money(discount * line_total / subtotal)
                allocated += share
        else:
            share = Decimal("0.00")
        taxable = money(line_total - share)
        line_gst = money(taxable * money(line.gst_rate) / Decimal("100"))
        gst_total += line_gst
        computed.append(
            ComputedLine(
                product_id=line.product_id,
                qty=qty(line.qty),
                unit_price=money(line.unit_price),
                line_discount=money(line.line_discount),
                line_total=line_total,
                gst_amount=line_gst,
            )
        )

    gst_total = money(gst_total)
    total = money(subtotal - discount + gst_total)
    return ComputedTotals(
        lines=computed,
        subtotal=subtotal,
        discount=discount,
        gst_amount=gst_total,
        total=total,
    )


def next_invoice_no(db: Session, store_id: int) -> str:
    """Sequential per store: INV-<store>-00001."""
    count = db.scalar(
        select(func.count(Transaction.id)).where(Transaction.store_id == store_id)
    ) or 0
    return f"INV-{store_id:02d}-{count + 1:05d}"


def create_sale(
    db: Session,
    context: StoreContext,
    *,
    lines: list[dict],
    customer_id: int | None = None,
    discount: Decimal = Decimal("0.00"),
    payment_mode: str = "cash",
    created_at: datetime | None = None,
    status: str = "completed",
) -> Transaction:
    """Validate stock, write the transaction and decrement stock in one DB transaction.

    Raises ConflictError on an oversell, NotFoundError for unknown ids. The caller
    commits; any exception leaves the session rolled back by the router.
    """
    if customer_id is not None:
        customer = db.get(Customer, customer_id)
        if customer is None or customer.store_id != context.store_id:
            raise NotFoundError(
                f"Customer {customer_id} is not a customer of {context.store_name}"
            )

    prepared: list[LineInput] = []
    products: dict[int, Product] = {}
    wanted: dict[int, Decimal] = {}

    for raw in lines:
        product = db.get(Product, int(raw["product_id"]))
        if product is None or product.store_id != context.store_id:
            raise NotFoundError(
                f"Product {raw['product_id']} is not in the catalog of {context.store_name}"
            )
        products[product.id] = product
        line_qty = qty(raw["qty"])
        wanted[product.id] = wanted.get(product.id, Decimal("0")) + line_qty
        prepared.append(
            LineInput(
                product_id=product.id,
                qty=line_qty,
                unit_price=money(raw.get("unit_price") or product.sell_price),
                line_discount=money(raw.get("line_discount") or 0),
                gst_rate=Decimal(str(product.gst_rate or 0)),
            )
        )

    unit = context.unit_label
    for product_id, needed in wanted.items():
        stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product_id))
        on_hand = qty(stock.qty_on_hand) if stock else Decimal("0")
        if on_hand < needed:
            product = products[product_id]
            raise ConflictError(
                f"SKU {product.sku} has {on_hand.normalize()} {unit} in stock, "
                f"{needed.normalize()} requested"
            )

    totals = compute_totals(prepared, discount)
    stamp = created_at or utcnow()

    transaction = Transaction(
        store_id=context.store_id,
        customer_id=customer_id,
        invoice_no=next_invoice_no(db, context.store_id),
        subtotal=totals.subtotal,
        discount=totals.discount,
        gst_amount=totals.gst_amount,
        total=totals.total,
        payment_mode=payment_mode,
        status=status,
        created_at=stamp,
    )
    db.add(transaction)
    db.flush()

    tracks_expiry = context.feature("expiry")
    for line in totals.lines:
        allocation = None
        if tracks_expiry and status == "completed":
            allocation = batch_service.allocate_fefo(db, line.product_id, line.qty)
        db.add(
            TransactionItem(
                transaction_id=transaction.id,
                product_id=line.product_id,
                qty=line.qty,
                unit_price=line.unit_price,
                line_discount=line.line_discount,
                line_total=line.line_total,
                batch_allocation=allocation,
            )
        )

    if status == "completed":
        _move_stock(db, wanted, stamp, direction=-1)

    db.flush()
    return transaction


def refund_sale(db: Session, context: StoreContext, transaction_id: int) -> Transaction:
    """Flip a completed sale to refunded and return the stock."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.store_id != context.store_id:
        raise NotFoundError(f"Invoice {transaction_id} does not belong to {context.store_name}")
    if transaction.status == "refunded":
        raise ConflictError(f"Invoice {transaction.invoice_no} is already refunded")
    if transaction.status != "completed":
        raise ConflictError(
            f"Invoice {transaction.invoice_no} is {transaction.status}; only a completed "
            "sale can be refunded"
        )

    quantities: dict[int, Decimal] = {}
    for item in transaction.items:
        quantities[item.product_id] = quantities.get(item.product_id, Decimal("0")) + qty(item.qty)
        if item.batch_allocation:
            batch_service.restore(db, item.batch_allocation)
    _move_stock(db, quantities, utcnow(), direction=+1)

    transaction.status = "refunded"
    db.flush()
    return transaction


def _move_stock(
    db: Session, quantities: dict[int, Decimal], stamp: datetime, *, direction: int
) -> None:
    for product_id, amount in quantities.items():
        stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product_id))
        if stock is None:
            stock = StockLevel(product_id=product_id, qty_on_hand=Decimal("0"))
            db.add(stock)
            db.flush()
        stock.qty_on_hand = qty(Decimal(str(stock.qty_on_hand)) + (amount * direction))
        if direction < 0:
            stock.last_sold_at = stamp
        else:
            stock.last_received_at = stamp
