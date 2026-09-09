"""Tenant isolation, asserted against hand-crafted requests.

The query-string half of this was already enforced. The path half was not: the
/config/stores/{store_id}/... routes take the store from the path, and the
authorisation middleware only ever looked at request.query_params, so a manager
of one store could read - and PUT - another store's configuration. Every test
below fails against that version of the middleware.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.config import StoreConfig
from app.models.core import Customer
from tests.test_segmentation import _store


def _two_stores(db):
    return _store(db, "grocery", "Store A"), _store(db, "pharmacy", "Store B")


# -- reads through the query string ------------------------------------------
def test_a_scoped_user_cannot_read_another_stores_customers(db, role_client) -> None:
    store_a, store_b = _two_stores(db)
    db.add(Customer(store_id=store_a.id, name="Ronit Sharma", phone="9800000001"))
    db.commit()

    client = role_client("manager", store_id=store_b.id)
    response = client.get("/customers", params={"store_id": store_a.id})

    assert response.status_code == 403
    assert f"not store {store_a.id}" in response.json()["detail"]


# -- reads through the path --------------------------------------------------
def test_a_scoped_user_cannot_read_another_stores_context(db, role_client) -> None:
    store_a, store_b = _two_stores(db)
    client = role_client("manager", store_id=store_b.id)

    response = client.get(f"/config/stores/{store_a.id}/context")

    assert response.status_code == 403, response.text


def test_a_cashier_cannot_read_another_stores_reminder_rules(db, role_client) -> None:
    store_a, store_b = _two_stores(db)
    client = role_client("cashier", store_id=store_b.id)

    response = client.get(f"/config/stores/{store_a.id}/reminder-rules")

    assert response.status_code == 403, response.text


# -- writes through the path -------------------------------------------------
def test_a_scoped_manager_cannot_write_another_stores_config(db, role_client) -> None:
    store_a, store_b = _two_stores(db)
    client = role_client("manager", store_id=store_b.id)

    response = client.put(
        f"/config/stores/{store_a.id}/config",
        json={"key": "reorder_cycle_days", "value": "1"},
    )

    assert response.status_code == 403, response.text
    landed = db.scalars(select(StoreConfig).where(StoreConfig.store_id == store_a.id)).all()
    assert landed == [], "the refused write must not have reached the database"


# -- the store the user does own is still reachable ---------------------------
def test_a_scoped_user_still_reaches_their_own_store(db, role_client) -> None:
    _store_a, store_b = _two_stores(db)
    client = role_client("manager", store_id=store_b.id)

    assert client.get(f"/config/stores/{store_b.id}/context").status_code == 200
    assert client.get("/customers", params={"store_id": store_b.id}).status_code == 200
    assert (
        client.put(
            f"/config/stores/{store_b.id}/config",
            json={"key": "reorder_cycle_days", "value": "9"},
        ).status_code
        == 200
    )


def test_an_unscoped_owner_reaches_every_store(db, role_client) -> None:
    store_a, store_b = _two_stores(db)
    client = role_client("owner", store_id=None)

    assert client.get(f"/config/stores/{store_a.id}/context").status_code == 200
    assert client.get(f"/config/stores/{store_b.id}/context").status_code == 200


# -- and none of it is reachable without signing in --------------------------
def test_none_of_it_is_reachable_without_a_token(db, anon_client) -> None:
    store_a, _store_b = _two_stores(db)

    assert anon_client.get("/customers", params={"store_id": store_a.id}).status_code == 401
    assert anon_client.get(f"/config/stores/{store_a.id}/context").status_code == 401
    assert anon_client.get("/health").status_code == 200


# -- the session cookie ------------------------------------------------------
def test_the_session_cookie_is_httponly_and_secure(db, anon_client) -> None:
    """A token in a cookie that a script can read, or that travels in clear
    text, is a token that leaks. Both attributes are asserted here because both
    were once missing."""
    from app.security import hash_password
    from app.models.admin import User

    db.add(
        User(
            name="Cookie owner",
            email="cookie@example.com",
            password_hash=hash_password("password123"),
            role="owner",
            store_id=None,
        )
    )
    db.commit()

    response = anon_client.post(
        "/auth/login", json={"email": "cookie@example.com", "password": "password123"}
    )

    assert response.status_code == 200
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header


# -- pagination totals, which a page-numbered UI cannot be built without ------
def test_customers_report_the_whole_store_total_not_the_page(db, role_client) -> None:
    store_a, _store_b = _two_stores(db)
    for index in range(12):
        db.add(
            Customer(
                store_id=store_a.id, name=f"Customer {index:02d}", phone=f"98000000{index:02d}"
            )
        )
    db.commit()

    client = role_client("manager", store_id=store_a.id)
    response = client.get("/customers", params={"store_id": store_a.id, "limit": 5, "offset": 0})

    assert response.status_code == 200
    assert len(response.json()) == 5
    assert response.headers["X-Total-Count"] == "12"
    assert response.headers["X-Has-More"] == "true"

    last = client.get("/customers", params={"store_id": store_a.id, "limit": 5, "offset": 10})
    assert len(last.json()) == 2
    assert last.headers["X-Has-More"] == "false"


def test_search_scans_the_whole_store_not_just_the_first_page(db, role_client) -> None:
    """The bug this guards against: searching only what the first page already
    loaded. Ronit sorts last by name and is well past a page of 5."""
    store_a, _store_b = _two_stores(db)
    for index in range(20):
        db.add(
            Customer(
                store_id=store_a.id, name=f"Aarav {index:02d}", phone=f"97000000{index:02d}"
            )
        )
    db.add(Customer(store_id=store_a.id, name="Ronit Verma", phone="9711111111"))
    db.commit()

    client = role_client("manager", store_id=store_a.id)
    response = client.get("/customers", params={"store_id": store_a.id, "q": "Ronit", "limit": 5})

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Ronit Verma"]
    assert response.headers["X-Total-Count"] == "1"


def test_products_report_a_total_so_pages_can_be_numbered(db, role_client) -> None:
    from app.models.core import Product

    store_a, _store_b = _two_stores(db)
    for index in range(7):
        db.add(
            Product(
                store_id=store_a.id,
                sku=f"SKU-{index}",
                name=f"Item {index}",
                cost_price=Decimal("10.00"),
                sell_price=Decimal("20.00"),
                gst_rate=Decimal("5"),
                attributes={},
            )
        )
    db.commit()

    client = role_client("manager", store_id=store_a.id)
    response = client.get("/products", params={"store_id": store_a.id, "limit": 3})

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert response.headers["X-Total-Count"] == "7"
    assert response.headers["X-Has-More"] == "true"


def test_pagination_headers_are_exposed_to_browser_clients(db, role_client) -> None:
    """A browser hides every response header outside a short safelist unless the
    server names it in Access-Control-Expose-Headers. Without this the new front
    end could read the customer rows but not the total that pages them."""
    from app.observability import PAGINATION_HEADERS

    store_a, _store_b = _two_stores(db)
    client = role_client("manager", store_id=store_a.id)

    response = client.get(
        "/customers",
        params={"store_id": store_a.id, "limit": 5, "offset": 0},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    exposed = {
        name.strip().lower()
        for name in response.headers.get("access-control-expose-headers", "").split(",")
    }
    for header in PAGINATION_HEADERS:
        assert header.lower() in exposed, f"{header} is invisible to a browser client"


def test_repeated_wrong_passwords_are_throttled(db, anon_client) -> None:
    """Brute force is the one attack a login endpoint invites by existing.
    Ten wrong guesses a minute is generous for a mistyped password."""
    from app.models.admin import User
    from app.ratelimit import login_limiter
    from app.security import hash_password

    db.add(
        User(
            name="Throttled",
            email="throttle@example.com",
            password_hash=hash_password("password123"),
            role="owner",
            store_id=None,
        )
    )
    db.commit()
    login_limiter.reset()

    wrong = {"email": "throttle@example.com", "password": "not-the-password"}
    codes = [anon_client.post("/auth/login", json=wrong).status_code for _ in range(11)]

    assert codes[:10] == [404] * 10, "the first ten wrong guesses are ordinary refusals"
    assert codes[10] == 429, "the eleventh is throttled"

    blocked = anon_client.post("/auth/login", json=wrong)
    assert "Retry-After" in blocked.headers

    # A correct password clears the budget, so a busy counter is never locked
    # out by its own successful sign-ins.
    login_limiter.reset()
    good = anon_client.post(
        "/auth/login", json={"email": "throttle@example.com", "password": "password123"}
    )
    assert good.status_code == 200
    assert anon_client.post("/auth/login", json=wrong).status_code == 404
