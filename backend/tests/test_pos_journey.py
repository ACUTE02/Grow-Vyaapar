"""The POS flow as a cashier actually walks it, end to end and across stores.

The individual pieces have tests next door - totals, oversell, refunds,
coupons, points. What this file asserts is that they still hold when strung
together in one sale, and that a sale in one shop leaves the other shop's
shelf, invoice sequence and customer history untouched.
"""
from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import select

from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from tests.test_segmentation import _store


def _key() -> dict[str, str]:
    """A fresh Idempotency-Key per checkout, which the endpoint requires. Tests
    that care about retries pass their own key instead of calling this."""
    return {"Idempotency-Key": uuid.uuid4().hex}


def _product(db, store, sku: str, *, qty: str = "100", price: str = "50.00") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("20.00"),
        sell_price=Decimal(price),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal(qty), reorder_point=Decimal("5"))
    )
    db.flush()
    return product


def _customer(db, store, name="Ronit Verma", phone="9800000001") -> Customer:
    customer = Customer(store_id=store.id, name=name, phone=phone, marketing_opt_in=True)
    db.add(customer)
    db.flush()
    return customer


def _stock(db, product_id: int) -> Decimal:
    db.expire_all()
    return db.scalar(select(StockLevel.qty_on_hand).where(StockLevel.product_id == product_id))


def test_a_whole_sale_from_search_to_invoice(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    rice = _product(db, store, "RICE-1", qty="40", price="60.00")
    dal = _product(db, store, "DAL-1", qty="25", price="120.00")
    customer = _customer(db, store)
    db.commit()
    params = {"store_id": store.id}

    # The cashier types into the product box, and the API answers from the
    # whole catalogue rather than a page already on screen.
    found = client.get("/products", params={**params, "q": "RICE"})
    assert found.status_code == 200
    assert [row["sku"] for row in found.json()] == ["RICE-1"]

    # And looks the customer up the same way.
    matches = client.get("/customers", params={**params, "q": "Ronit"})
    assert [row["id"] for row in matches.json()] == [customer.id]

    sale = client.post(
        "/billing/transactions",
        params=params,
        json={
            "customer_id": customer.id,
            "payment_mode": "upi",
            "lines": [
                {"product_id": rice.id, "qty": "3"},
                {"product_id": dal.id, "qty": "2"},
            ],
        },
        headers=_key(),
    )
    assert sale.status_code == 201, sale.text
    body = sale.json()

    assert body["customer_id"] == customer.id
    assert body["payment_mode"] == "upi"
    assert body["invoice_no"], "a completed sale needs an invoice number"
    assert body["status"] == "completed"
    assert len(body["lines"]) == 2
    # 3x60 + 2x120 = 420 before tax, and the total has to be more than that.
    assert Decimal(str(body["subtotal"])) == Decimal("420.00")
    assert Decimal(str(body["total"])) > Decimal(str(body["subtotal"]))

    assert _stock(db, rice.id) == Decimal("37")
    assert _stock(db, dal.id) == Decimal("23")

    # The bill is reachable again afterwards, and shows up in the customer's
    # own history rather than only in the store's.
    again = client.get(f"/billing/transactions/{body['id']}", params=params)
    assert again.status_code == 200
    assert again.json()["invoice_no"] == body["invoice_no"]

    history = client.get(
        "/billing/transactions", params={**params, "customer_id": customer.id}
    )
    assert [row["id"] for row in history.json()] == [body["id"]]


def test_a_walk_in_sale_needs_no_customer(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "WALK-1")
    db.commit()

    sale = client.post(
        "/billing/transactions",
        params={"store_id": store.id},
        json={"lines": [{"product_id": product.id, "qty": "1"}]},
        headers=_key(),
    )

    assert sale.status_code == 201, sale.text
    assert sale.json()["customer_id"] is None
    assert _stock(db, product.id) == Decimal("99")


def test_an_oversold_line_leaves_the_whole_bill_unwritten(client, db) -> None:
    """The second line is the one that fails, so this also asserts the first
    line's stock was not quietly spent on a bill that never existed."""
    store = _store(db, "grocery", "Sharma Kirana")
    plenty = _product(db, store, "PLENTY-1", qty="100")
    scarce = _product(db, store, "SCARCE-1", qty="2")
    db.commit()

    before = client.get("/billing/transactions", params={"store_id": store.id}).json()

    sale = client.post(
        "/billing/transactions",
        params={"store_id": store.id},
        json={
            "lines": [
                {"product_id": plenty.id, "qty": "1"},
                {"product_id": scarce.id, "qty": "50"},
            ]
        },
        headers=_key(),
    )

    assert sale.status_code == 409, sale.text
    assert _stock(db, plenty.id) == Decimal("100"), "a refused bill spent stock anyway"
    assert _stock(db, scarce.id) == Decimal("2")
    after = client.get("/billing/transactions", params={"store_id": store.id}).json()
    assert len(after) == len(before), "a refused bill was still recorded"


def test_a_sale_in_one_store_leaves_the_other_alone(client, db) -> None:
    """Same SKU, same customer name, two shops. Nothing may cross."""
    store_a = _store(db, "grocery", "Sharma Kirana")
    store_b = _store(db, "grocery", "Gupta Provisions")
    product_a = _product(db, store_a, "SHARED-SKU", qty="30")
    product_b = _product(db, store_b, "SHARED-SKU", qty="30")
    _customer(db, store_a, name="Ronit Verma", phone="9800000011")
    _customer(db, store_b, name="Ronit Verma", phone="9800000012")
    db.commit()

    sale = client.post(
        "/billing/transactions",
        params={"store_id": store_a.id},
        json={"lines": [{"product_id": product_a.id, "qty": "5"}]},
        headers=_key(),
    )
    assert sale.status_code == 201, sale.text

    assert _stock(db, product_a.id) == Decimal("25")
    assert _stock(db, product_b.id) == Decimal("30"), "the other shop's shelf moved"

    in_b = client.get("/billing/transactions", params={"store_id": store_b.id})
    assert in_b.json() == [], "a bill appeared in the wrong store"

    # Invoice sequences are per store, so store B's first bill is still its first.
    sale_b = client.post(
        "/billing/transactions",
        params={"store_id": store_b.id},
        json={"lines": [{"product_id": product_b.id, "qty": "1"}]},
        headers=_key(),
    )
    assert sale_b.status_code == 201
    assert sale_b.json()["invoice_no"] != sale.json()["invoice_no"]


def test_a_resubmitted_checkout_returns_the_first_bill(client, db) -> None:
    """The same cart, submitted twice with the same key, is one bill and one
    stock movement. This used to be the opposite: two bills, stock taken
    twice, and a disabled button as the only guard - which stops a second
    click and does nothing about a retried request."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "DOUBLE-1", qty="10")
    db.commit()

    body = {"lines": [{"product_id": product.id, "qty": "1"}]}
    headers = _key()
    first = client.post(
        "/billing/transactions", params={"store_id": store.id}, json=body, headers=headers
    )
    second = client.post(
        "/billing/transactions", params={"store_id": store.id}, json=body, headers=headers
    )

    assert first.status_code == 201
    assert second.status_code == 200, "a safe retry is not a creation"
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert second.json() == first.json(), "the retry returned a different bill"

    assert _stock(db, product.id) == Decimal("9"), "the shelf moved twice"
    bills = db.scalars(select(Transaction).where(Transaction.store_id == store.id)).all()
    assert len(bills) == 1
    items = db.scalars(
        select(TransactionItem).where(TransactionItem.transaction_id == bills[0].id)
    ).all()
    assert len(items) == 1, "the retry wrote a second set of line items"
