"""Catalog behaviour differs by vertical without any branch on a vertical name."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.base import utcnow
from app.models.config import Store, Vertical
from app.models.core import Product, StockLevel


def _store_for(db, code: str, name: str) -> Store:
    vertical = db.scalar(select(Vertical).where(Vertical.code == code))
    store = Store(vertical_id=vertical.id, name=name, city="Pune", language="en")
    db.add(store)
    db.commit()
    return store


PHARMACY_PRODUCT = {
    "sku": "ANL-1001",
    "name": "Paracetamol 500",
    "sell_price": "24.50",
    "cost_price": "18.00",
    "gst_rate": "12",
    "qty_on_hand": 40,
    "reorder_point": 10,
}


def test_pharmacy_product_without_batch_no_is_422(client, db) -> None:
    store = _store_for(db, "pharmacy", "Jeevan Medical")
    payload = PHARMACY_PRODUCT | {
        "attributes": {"composition": "Paracetamol IP 500mg", "expiry_date": "2027-01-31"}
    }
    response = client.post(f"/products?store_id={store.id}", json=payload)
    assert response.status_code == 422
    assert "batch_no" in response.text


def test_the_same_shape_under_apparel_is_also_422(client, db) -> None:
    store = _store_for(db, "apparel", "Rangoli Fashion")
    payload = PHARMACY_PRODUCT | {
        "attributes": {
            "composition": "Paracetamol IP 500mg",
            "batch_no": "B12345",
            "expiry_date": "2027-01-31",
        }
    }
    response = client.post(f"/products?store_id={store.id}", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert "unknown attribute" in body["detail"]
    assert any("size" in error for error in body["errors"]), body["errors"]


def test_valid_attributes_create_the_product(client, db) -> None:
    store = _store_for(db, "pharmacy", "Jeevan Medical")
    payload = PHARMACY_PRODUCT | {
        "attributes": {
            "composition": "Paracetamol IP 500mg",
            "batch_no": "B12345",
            "expiry_date": "2027-01-31",
            "schedule_h": False,
        }
    }
    response = client.post(f"/products?store_id={store.id}", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sku"] == "ANL-1001"
    assert body["unit_label"] == "strip"
    assert Decimal(body["qty_on_hand"]) == 40


def test_duplicate_sku_is_409(client, db) -> None:
    store = _store_for(db, "apparel", "Rangoli Fashion")
    payload = {
        "sku": "KRT-1001",
        "name": "Cotton Kurta Set",
        "sell_price": "1299.00",
        "attributes": {"size": "M", "colour": "Indigo"},
    }
    assert client.post(f"/products?store_id={store.id}", json=payload).status_code == 201
    duplicate = client.post(f"/products?store_id={store.id}", json=payload)
    assert duplicate.status_code == 409
    assert "KRT-1001" in duplicate.json()["detail"]


def _stale_product(db, store: Store, sku: str, days_since_sold: int) -> None:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Stale {sku}",
        cost_price=Decimal("10.00"),
        sell_price=Decimal("20.00"),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(
            product_id=product.id,
            qty_on_hand=Decimal("25"),
            reorder_point=Decimal("5"),
            last_sold_at=utcnow() - timedelta(days=days_since_sold),
        )
    )
    db.commit()


def test_dead_stock_uses_each_stores_own_window(client, db) -> None:
    """Same query code, different answers: 100 days is dead for one, fine for the other."""
    slow = _store_for(db, "pharmacy", "Jeevan Medical")     # dead_stock_days = 120
    fast = _store_for(db, "apparel", "Rangoli Fashion")     # dead_stock_days = 90

    _stale_product(db, slow, "SLOW-1", 100)
    _stale_product(db, fast, "FAST-1", 100)

    slow_rows = client.get(f"/products/dead-stock?store_id={slow.id}").json()
    fast_rows = client.get(f"/products/dead-stock?store_id={fast.id}").json()

    assert slow_rows == [], "100 days is inside the 120-day window, nothing is dead yet"
    assert [row["sku"] for row in fast_rows] == ["FAST-1"]


def test_low_stock_lists_items_at_or_below_reorder_point(client, db) -> None:
    store = _store_for(db, "apparel", "Rangoli Fashion")
    created = client.post(
        f"/products?store_id={store.id}",
        json={
            "sku": "SHT-2001",
            "name": "Formal Shirt",
            "sell_price": "899.00",
            "attributes": {"size": "L", "colour": "Ivory"},
            "qty_on_hand": 2,
            "reorder_point": 6,
        },
    )
    assert created.status_code == 201
    rows = client.get(f"/products/low-stock?store_id={store.id}").json()
    assert [row["sku"] for row in rows] == ["SHT-2001"]
    assert rows[0]["unit_label"] == "piece"
