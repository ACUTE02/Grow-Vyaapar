"""Billing: stock moves exactly, oversells change nothing, GST adds up."""
from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import select

from app.models.config import Store, Vertical
from app.models.core import Product, StockLevel, Transaction
from app.services.billing_service import LineInput, compute_totals


def _idempotency_key() -> dict[str, str]:
    """A fresh Idempotency-Key per checkout, which the sale endpoint requires."""
    return {"Idempotency-Key": uuid.uuid4().hex}



def _store_for(db, code: str, name: str) -> Store:
    vertical = db.scalar(select(Vertical).where(Vertical.code == code))
    store = Store(
        vertical_id=vertical.id,
        name=name,
        city="Indore",
        gstin="23ABCDE1234F1Z5",
        language="en",
    )
    db.add(store)
    db.commit()
    return store


def _product(db, store: Store, sku: str, price: str, gst: str, qty: str) -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("10.00"),
        sell_price=Decimal(price),
        gst_rate=Decimal(gst),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal(qty), reorder_point=Decimal("2"))
    )
    db.commit()
    return product


# -- pure arithmetic ---------------------------------------------------------
def test_totals_are_exact_with_gst_and_discount() -> None:
    totals = compute_totals(
        [
            LineInput(1, Decimal("2"), Decimal("100.00"), Decimal("0.00"), Decimal("5")),
            LineInput(2, Decimal("1"), Decimal("200.00"), Decimal("20.00"), Decimal("12")),
        ],
        Decimal("30.00"),
    )
    # lines: 200.00 and 180.00 -> subtotal 380.00
    assert totals.subtotal == Decimal("380.00")
    assert totals.discount == Decimal("30.00")
    # discount allocated pro rata: 15.79 and 14.21; gst 5% and 12% on the remainder
    assert totals.gst_amount == Decimal("29.10")
    assert totals.total == Decimal("379.10")
    assert sum(line.line_total for line in totals.lines) == totals.subtotal


def test_discount_larger_than_the_bill_is_rejected() -> None:
    try:
        compute_totals(
            [LineInput(1, Decimal("1"), Decimal("50.00"), Decimal("0.00"), Decimal("5"))],
            Decimal("80.00"),
        )
    except Exception as exc:
        assert "larger than the bill subtotal" in str(exc)
    else:
        raise AssertionError("an over-sized discount must be rejected")


# -- the endpoint ------------------------------------------------------------
def test_sale_decrements_stock_by_exactly_the_sold_quantity(client, db) -> None:
    store = _store_for(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "STP-1001", "50.00", "5", "10")

    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 3}], "payment_mode": "upi"},
        headers=_idempotency_key(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invoice_no"] == f"INV-{store.id:02d}-00001"
    assert Decimal(body["subtotal"]) == Decimal("150.00")
    assert Decimal(body["gst_amount"]) == Decimal("7.50")
    assert Decimal(body["total"]) == Decimal("157.50")
    assert body["unit_label"] == "kg"

    db.expire_all()
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert Decimal(str(stock.qty_on_hand)) == Decimal("7.000")
    assert stock.last_sold_at is not None


def test_oversell_returns_409_and_changes_nothing(client, db) -> None:
    store = _store_for(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "STP-1042", "50.00", "5", "3")

    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 5}]},
        headers=_idempotency_key(),
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "STP-1042" in detail and "3" in detail and "5 requested" in detail

    db.expire_all()
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert Decimal(str(stock.qty_on_hand)) == Decimal("3.000")
    assert db.scalars(select(Transaction)).all() == []


def test_invoice_numbers_are_sequential_per_store(client, db) -> None:
    first = _store_for(db, "grocery", "Store One")
    second = _store_for(db, "pharmacy", "Store Two")
    product_a = _product(db, first, "A-1", "10.00", "5", "50")
    product_b = _product(db, second, "B-1", "10.00", "5", "50")

    numbers = []
    for _ in range(2):
        numbers.append(
            client.post(
                f"/billing/transactions?store_id={first.id}",
                json={"lines": [{"product_id": product_a.id, "qty": 1}]},
                headers=_idempotency_key(),
            ).json()["invoice_no"]
        )
    other = client.post(
        f"/billing/transactions?store_id={second.id}",
        json={"lines": [{"product_id": product_b.id, "qty": 1}]},
        headers=_idempotency_key(),
    ).json()["invoice_no"]

    assert numbers == [f"INV-{first.id:02d}-00001", f"INV-{first.id:02d}-00002"]
    assert other == f"INV-{second.id:02d}-00001"


def test_refund_returns_the_stock(client, db) -> None:
    store = _store_for(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "STP-1001", "50.00", "5", "10")
    sale = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 4}]},
        headers=_idempotency_key(),
    ).json()

    refunded = client.post(
        f"/billing/transactions/{sale['id']}/refund?store_id={store.id}"
    )
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"

    db.expire_all()
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert Decimal(str(stock.qty_on_hand)) == Decimal("10.000")

    again = client.post(f"/billing/transactions/{sale['id']}/refund?store_id={store.id}")
    assert again.status_code == 409


def test_invoice_renders_with_the_right_unit_label_per_store(client, db) -> None:
    grocery = _store_for(db, "grocery", "Sharma Kirana")
    pharmacy = _store_for(db, "pharmacy", "Jeevan Medical")
    grocery_product = _product(db, grocery, "STP-1", "50.00", "5", "10")
    pharmacy_product = _product(db, pharmacy, "ANL-1", "24.00", "12", "10")

    grocery_sale = client.post(
        f"/billing/transactions?store_id={grocery.id}",
        json={"lines": [{"product_id": grocery_product.id, "qty": 2}]},
        headers=_idempotency_key(),
    ).json()
    pharmacy_sale = client.post(
        f"/billing/transactions?store_id={pharmacy.id}",
        json={"lines": [{"product_id": pharmacy_product.id, "qty": 2}]},
        headers=_idempotency_key(),
    ).json()

    grocery_html = client.get(
        f"/billing/transactions/{grocery_sale['id']}/invoice.html?store_id={grocery.id}"
    ).text
    pharmacy_html = client.get(
        f"/billing/transactions/{pharmacy_sale['id']}/invoice.html?store_id={pharmacy.id}"
    ).text

    assert "Qty (kg)" in grocery_html
    assert "Qty (strip)" in pharmacy_html
    assert "23ABCDE1234F1Z5" in grocery_html
    assert "INR 105.00" in grocery_html          # 100.00 + 5% GST
    assert "INR 53.76" in pharmacy_html          # 48.00 + 12% GST


def test_invoice_pdf_endpoint_answers(client, db) -> None:
    """WeasyPrint needs native libraries; the route must still answer either way."""
    store = _store_for(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "STP-1", "50.00", "5", "10")
    sale = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 1}]},
        headers=_idempotency_key(),
    ).json()

    response = client.get(
        f"/billing/transactions/{sale['id']}/invoice.pdf?store_id={store.id}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(("application/pdf", "text/html"))


def test_selling_another_stores_product_is_404(client, db) -> None:
    mine = _store_for(db, "grocery", "Mine")
    theirs = _store_for(db, "pharmacy", "Theirs")
    their_product = _product(db, theirs, "X-1", "10.00", "5", "50")

    response = client.post(
        f"/billing/transactions?store_id={mine.id}",
        json={"lines": [{"product_id": their_product.id, "qty": 1}]},
        headers=_idempotency_key(),
    )
    assert response.status_code == 404
