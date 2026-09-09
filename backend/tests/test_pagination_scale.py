"""Pagination and search at the sizes a real store reaches.

The brief asks for 0, 1, 300, 1,000 and 10,000 customers explicitly, because
every one of them breaks a different assumption: zero breaks the "showing 1-N"
arithmetic, one breaks the plural, and ten thousand breaks anything that loads
the list into memory before filtering it.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.core import Customer
from tests.test_segmentation import _store


def _fill(db, store, count: int, *, prefix: str = "Customer") -> None:
    """Bulk insert - 10,000 ORM objects would dominate the test's runtime."""
    if count == 0:
        return
    db.execute(
        Customer.__table__.insert(),
        [
            {
                "store_id": store.id,
                "name": f"{prefix} {index:05d}",
                "phone": f"9{index:09d}",
                "marketing_opt_in": True,
            }
            for index in range(count)
        ],
    )
    db.commit()


@pytest.mark.parametrize("size", [0, 1, 300, 1000])
def test_the_total_is_the_store_not_the_page(db, role_client, size: int) -> None:
    store = _store(db, "grocery", "Scale Store")
    _fill(db, store, size)

    client = role_client("manager", store_id=store.id)
    response = client.get("/customers", params={"store_id": store.id, "limit": 50, "offset": 0})

    assert response.status_code == 200
    assert int(response.headers["X-Total-Count"]) == size
    assert len(response.json()) == min(size, 50)
    assert response.headers["X-Has-More"] == ("true" if size > 50 else "false")


def test_the_last_page_of_a_thousand_is_reachable_and_correct(db, role_client) -> None:
    store = _store(db, "grocery", "Scale Store")
    _fill(db, store, 1000)

    client = role_client("manager", store_id=store.id)
    # 1,000 customers at 50 a page is 20 pages; page 20 starts at offset 950.
    last = client.get("/customers", params={"store_id": store.id, "limit": 50, "offset": 950})

    assert last.status_code == 200
    rows = last.json()
    assert len(rows) == 50
    assert rows[-1]["name"] == "Customer 00999"
    assert last.headers["X-Has-More"] == "false"

    # And one past the end is an empty page, not an error.
    beyond = client.get("/customers", params={"store_id": store.id, "limit": 50, "offset": 1000})
    assert beyond.status_code == 200
    assert beyond.json() == []


def test_search_finds_the_last_customer_of_ten_thousand(db, role_client) -> None:
    """The bug this exists for: a search that only looks at the page already
    loaded. Ronit is inserted last, sorts last by name, and sits roughly 200
    pages past the first one."""
    store = _store(db, "grocery", "Big Store")
    _fill(db, store, 10_000, prefix="Aarav")
    db.add(Customer(store_id=store.id, name="Ronit Verma", phone="9999999999"))
    db.commit()

    assert db.scalar(select(func.count(Customer.id)).where(Customer.store_id == store.id)) == 10_001

    client = role_client("manager", store_id=store.id)
    found = client.get("/customers", params={"store_id": store.id, "q": "Ronit", "limit": 50})

    assert found.status_code == 200
    assert [row["name"] for row in found.json()] == ["Ronit Verma"]
    assert found.headers["X-Total-Count"] == "1"

    # A phone fragment reaches just as far.
    by_phone = client.get(
        "/customers", params={"store_id": store.id, "q": "9999999999", "limit": 50}
    )
    assert [row["name"] for row in by_phone.json()] == ["Ronit Verma"]

    # Browsing still pages: 10,001 rows, never all in one response.
    page = client.get("/customers", params={"store_id": store.id, "limit": 50, "offset": 0})
    assert len(page.json()) == 50
    assert page.headers["X-Total-Count"] == "10001"


def test_the_ceiling_stops_a_client_asking_for_everything(db, role_client) -> None:
    """No caller gets to turn a list endpoint into a full table scan."""
    store = _store(db, "grocery", "Big Store")
    _fill(db, store, 600)

    client = role_client("manager", store_id=store.id)
    assert client.get("/customers", params={"store_id": store.id, "limit": 5000}).status_code == 422
    assert client.get("/customers", params={"store_id": store.id, "limit": 500}).status_code == 200


def test_products_page_and_count_at_scale(db, role_client) -> None:
    from decimal import Decimal
    from app.models.core import Product

    store = _store(db, "grocery", "Big Store")
    db.execute(
        Product.__table__.insert(),
        [
            {
                "store_id": store.id,
                "sku": f"SKU-{index:05d}",
                "name": f"Item {index:05d}",
                "cost_price": Decimal("10.00"),
                "sell_price": Decimal("20.00"),
                "gst_rate": Decimal("5"),
                "attributes": {},
                "is_active": True,
            }
            for index in range(2000)
        ],
    )
    db.commit()

    client = role_client("manager", store_id=store.id)
    response = client.get("/products", params={"store_id": store.id, "limit": 50, "offset": 0})

    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "2000"
    assert len(response.json()) == 50

    found = client.get("/products", params={"store_id": store.id, "q": "Item 01999", "limit": 50})
    assert [row["sku"] for row in found.json()] == ["SKU-01999"]
