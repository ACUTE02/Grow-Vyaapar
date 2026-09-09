"""Guards against the two ways a list page gets slow: N+1 queries and no limit.

A timing assertion would be flaky on a laptop and meaningless in CI, so these
count queries instead. A page that issues one query per row will fail here long
before anybody notices it in a browser.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from tests.test_segmentation import _store

PHONES = iter(range(6_000_000, 7_000_000))


@contextmanager
def counted(engine):
    """Count the SQL statements issued inside the block."""
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _populate(db, store, customers: int = 40) -> None:
    product = Product(
        store_id=store.id,
        sku="PERF-1",
        name="Perf item",
        cost_price=Decimal("40.00"),
        sell_price=Decimal("100.00"),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal("999"), reorder_point=Decimal("5"))
    )

    for index in range(customers):
        customer = Customer(
            store_id=store.id, name=f"Customer {index:03d}", phone=f"9{next(PHONES):09d}"
        )
        db.add(customer)
        db.flush()
        for visit in range(3):
            transaction = Transaction(
                store_id=store.id,
                customer_id=customer.id,
                invoice_no=f"INV-{store.id:02d}-{customer.id:05d}-{visit}",
                subtotal=Decimal("100.00"),
                discount=Decimal("0.00"),
                gst_amount=Decimal("5.00"),
                total=Decimal("105.00"),
                payment_mode="cash",
                status="completed",
            )
            db.add(transaction)
            db.flush()
            db.add(
                TransactionItem(
                    transaction_id=transaction.id,
                    product_id=product.id,
                    qty=Decimal("1"),
                    unit_price=Decimal("100.00"),
                    line_discount=Decimal("0.00"),
                    line_total=Decimal("100.00"),
                )
            )
    db.commit()


# -- N+1 guards --------------------------------------------------------------
def test_the_customer_list_does_not_query_per_row(client, db, engine) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _populate(db, store, customers=40)

    with counted(engine) as statements:
        rows = client.get(f"/customers?store_id={store.id}&limit=40").json()

    assert len(rows) == 40
    selects = [item for item in statements if item.strip().upper().startswith("SELECT")]
    assert len(selects) < 10, (
        f"{len(selects)} SELECTs for 40 customers - something is querying per row:\n"
        + "\n".join(selects[:12])
    )


def test_the_outbox_does_not_query_per_row(client, rules, engine) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    _populate(db, store, customers=30)

    from app.agents import reminders as reminder_agent
    from app.agents import segmentation
    from app.verticals.context import resolve_store_context

    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    reminder_agent.run(db, context, llm_budget=0)
    db.commit()

    with counted(engine) as statements:
        rows = client.get(f"/marketing/reminders?store_id={store.id}&limit=50").json()

    assert rows, "the fixture should have queued something"
    selects = [item for item in statements if item.strip().upper().startswith("SELECT")]
    assert len(selects) < 10, f"{len(selects)} SELECTs for {len(rows)} reminders"


def test_the_transaction_list_does_not_query_per_row(client, db, engine) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _populate(db, store, customers=30)

    with counted(engine) as statements:
        rows = client.get(f"/billing/transactions?store_id={store.id}&limit=50").json()

    assert len(rows) == 50
    selects = [item for item in statements if item.strip().upper().startswith("SELECT")]
    assert len(selects) < 10, f"{len(selects)} SELECTs for 50 transactions"


# -- pagination --------------------------------------------------------------
def test_list_endpoints_report_pagination_metadata(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _populate(db, store, customers=25)

    response = client.get(f"/customers?store_id={store.id}&limit=10&offset=0")
    assert response.headers["X-Limit"] == "10"
    assert response.headers["X-Offset"] == "0"
    assert response.headers["X-Total-Count"] == "25"
    assert response.headers["X-Has-More"] == "true"
    assert len(response.json()) == 10

    last = client.get(f"/customers?store_id={store.id}&limit=10&offset=20")
    assert last.headers["X-Has-More"] == "false"
    assert len(last.json()) == 5


def test_offset_actually_moves_the_window(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _populate(db, store, customers=20)

    first = client.get(f"/customers?store_id={store.id}&limit=5&offset=0").json()
    second = client.get(f"/customers?store_id={store.id}&limit=5&offset=5").json()
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second})


def test_a_caller_cannot_ask_for_the_whole_table(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    assert client.get(f"/customers?store_id={store.id}&limit=100000").status_code == 422
    assert client.get(f"/products?store_id={store.id}&limit=99999").status_code == 422


# -- errors and tracing ------------------------------------------------------
def test_every_response_carries_a_request_id(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    response = client.get(f"/customers?store_id={store.id}")
    assert response.headers["X-Request-Id"]
    assert float(response.headers["X-Response-Time-Ms"]) >= 0


def test_a_supplied_request_id_is_echoed_back(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    response = client.get(
        f"/customers?store_id={store.id}", headers={"X-Request-Id": "trace-me-123"}
    )
    assert response.headers["X-Request-Id"] == "trace-me-123"


def test_an_unexpected_error_never_leaks_a_stack_trace(client, db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")

    def explode(*args, **kwargs):
        raise RuntimeError("a secret internal detail")

    monkeypatch.setattr("app.services.customer_service.search_customers", explode)

    # Let the app return its 500 instead of re-raising into the test, the way a
    # real client would see it.
    client._transport.raise_server_exceptions = False
    response = client.get(f"/customers?store_id={store.id}")
    assert response.status_code == 500
    body = response.json()
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    assert body["request_id"]
    assert "Nothing was changed" in body["detail"]


def test_the_suite_enforces_foreign_keys_like_production_does(db) -> None:
    """SQLite leaves referential integrity off unless asked, and the test engine
    is built in conftest rather than imported from app/db.py, so it did not
    inherit the pragma the application sets. The suite accepted a customer
    belonging to store 424242. A referential bug would have passed here and
    failed in production."""
    from sqlalchemy import text

    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1

    with pytest.raises(Exception):
        db.execute(
            text(
                "INSERT INTO customers (store_id, name, phone, marketing_opt_in, created_at) "
                "VALUES (424242, 'Orphan', '9000000000', 1, '2026-01-01')"
            )
        )
        db.flush()
