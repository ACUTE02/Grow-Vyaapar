"""Auth, roles, the audit trail, suppliers and purchasing.

The role checks matter most: the UI hiding a button proves nothing, so every
assertion here is a hand-crafted request, exactly what an examiner would try.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.admin import AuditLog, User
from app.models.core import Batch, Product, StockLevel
from app.security import decode_token, hash_password, verify_password
from tests.test_segmentation import _store


def _product(db, store, sku: str = "STP-1", price: str = "100.00") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("60.00"),
        sell_price=Decimal(price),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal("10"), reorder_point=Decimal("2"))
    )
    db.commit()
    return product


# -- passwords ---------------------------------------------------------------
def test_passwords_are_hashed_not_stored() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert hashed.startswith("$2")                      # bcrypt
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong password", hashed)


def test_two_hashes_of_the_same_password_differ() -> None:
    assert hash_password("password123") != hash_password("password123")


def test_a_short_password_is_refused() -> None:
    try:
        hash_password("short")
    except ValueError as exc:
        assert "8 characters" in str(exc)
    else:
        raise AssertionError("a short password must be refused")


# -- login -------------------------------------------------------------------
def test_login_returns_a_token_and_never_the_password(anon_client, db) -> None:
    from tests.conftest import _make_user

    _make_user(db, role="manager", email="manager@example.com")
    response = anon_client.post(
        "/auth/login", json={"email": "manager@example.com", "password": "password123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "password" not in response.text
    claims = decode_token(body["access_token"])
    assert claims["role"] == "manager"
    assert body["user"]["email"] == "manager@example.com"


def test_a_wrong_password_is_vague_on_purpose(anon_client, db) -> None:
    from tests.conftest import _make_user

    _make_user(db, role="cashier", email="cashier@example.com")
    response = anon_client.post(
        "/auth/login", json={"email": "cashier@example.com", "password": "not-the-password"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Email or password is not correct"


def test_a_deactivated_user_cannot_sign_in(anon_client, db) -> None:
    from tests.conftest import _make_user

    user = _make_user(db, role="cashier", email="gone@example.com")
    user.is_active = False
    db.commit()
    response = anon_client.post(
        "/auth/login", json={"email": "gone@example.com", "password": "password123"}
    )
    assert response.status_code == 404


def test_no_token_means_401(anon_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    response = anon_client.get(f"/customers?store_id={store.id}")
    assert response.status_code == 401
    assert "Sign in first" in response.json()["detail"]


def test_a_forged_token_is_refused(anon_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    anon_client.headers["Authorization"] = "Bearer not.a.real.token"
    assert anon_client.get(f"/customers?store_id={store.id}").status_code == 401


# -- roles -------------------------------------------------------------------
def test_a_cashier_cannot_create_a_product_even_by_hand(role_client, db) -> None:
    """The acceptance case: refused by the API, not merely hidden in the UI."""
    store = _store(db, "grocery", "Sharma Kirana")
    client = role_client("cashier")

    response = client.post(
        f"/products?store_id={store.id}",
        json={
            "sku": "SNEAK-1",
            "name": "Snuck in",
            "sell_price": "10.00",
            "attributes": {"brand": "X", "pack_size": "1 kg"},
        },
    )
    assert response.status_code == 403
    assert "manager role" in response.json()["detail"]
    assert db.scalar(select(Product).where(Product.sku == "SNEAK-1")) is None


def test_a_cashier_can_still_bill(role_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    client = role_client("cashier")

    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 1}]},
    )
    assert response.status_code == 201


def test_a_cashier_can_read_the_catalog(role_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store)
    client = role_client("cashier")
    assert client.get(f"/products?store_id={store.id}").status_code == 200


def test_a_manager_can_create_a_product_but_not_a_user(role_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    client = role_client("manager")

    created = client.post(
        f"/products?store_id={store.id}",
        json={
            "sku": "MGR-1",
            "name": "Manager item",
            "sell_price": "10.00",
            "attributes": {"brand": "X", "pack_size": "1 kg"},
        },
    )
    assert created.status_code == 201

    denied = client.post(
        "/auth/users",
        json={
            "name": "New cashier",
            "email": "new@example.com",
            "password": "password123",
            "role": "cashier",
        },
    )
    assert denied.status_code == 403
    assert "owner role" in denied.json()["detail"]


def test_an_owner_can_create_users(client) -> None:
    response = client.post(
        "/auth/users",
        json={
            "name": "Shop manager",
            "email": "newmanager@example.com",
            "password": "password123",
            "role": "manager",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "manager"
    assert "password" not in response.text


def test_a_user_of_one_store_cannot_reach_another(role_client, db) -> None:
    mine = _store(db, "grocery", "Mine")
    theirs = _store(db, "pharmacy", "Theirs")
    client = role_client("manager", store_id=mine.id)

    assert client.get(f"/customers?store_id={mine.id}").status_code == 200
    blocked = client.get(f"/customers?store_id={theirs.id}")
    assert blocked.status_code == 403
    assert f"store {mine.id}" in blocked.json()["detail"]


def test_me_reports_the_signed_in_user(role_client, db) -> None:
    client = role_client("manager")
    body = client.get("/auth/me").json()
    assert body["role"] == "manager"
    assert body["is_active"] is True


# -- the audit trail ---------------------------------------------------------
def test_a_price_change_is_audited_with_old_and_new_values(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, price="100.00")

    response = client.patch(
        f"/products/{product.id}?store_id={store.id}", json={"sell_price": "125.50"}
    )
    assert response.status_code == 200

    db.expire_all()
    entry = db.scalar(
        select(AuditLog)
        .where(AuditLog.entity == "product", AuditLog.action == "product.update")
        .order_by(AuditLog.id.desc())
    )
    assert entry is not None
    assert entry.before["sell_price"] == "100.00"
    assert entry.after["sell_price"] == "125.50"
    assert entry.entity_id == str(product.id)


def test_an_unchanged_update_writes_no_diff_row(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, price="100.00")
    client.patch(f"/products/{product.id}?store_id={store.id}", json={"sell_price": "100.00"})

    db.expire_all()
    rows = db.scalars(
        select(AuditLog).where(AuditLog.action == "product.update")
    ).all()
    assert rows == []


def test_the_audit_endpoint_lists_the_trail(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    client.patch(f"/products/{product.id}?store_id={store.id}", json={"sell_price": "199.00"})

    trail = client.get(f"/purchasing/audit?store_id={store.id}").json()
    assert any(row["action"] == "product.update" for row in trail)


# -- suppliers and purchasing ------------------------------------------------
def test_receiving_a_purchase_order_raises_stock_and_creates_batches(client, db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")       # expiry flag on
    product = _product(db, store, sku="ANL-1")

    supplier = client.post(
        f"/purchasing/suppliers?store_id={store.id}",
        json={"name": "Nagpur Distributors", "phone": "9876500000", "rating": 4.5},
    ).json()

    order = client.post(
        f"/purchasing/orders?store_id={store.id}",
        json={
            "supplier_id": supplier["id"],
            "items": [
                {
                    "product_id": product.id,
                    "qty": 30,
                    "unit_cost": "55.00",
                    "batch_no": "B-2026-01",
                    "expiry_date": str(date.today() + timedelta(days=200)),
                }
            ],
        },
    ).json()
    assert order["status"] == "ordered"
    assert order["total"] == 1650.0

    received = client.post(f"/purchasing/orders/{order['id']}/receive?store_id={store.id}")
    assert received.status_code == 200
    assert received.json()["batches_created"] == 1

    db.expire_all()
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert Decimal(str(stock.qty_on_hand)) == Decimal("40.000")      # 10 + 30
    batch = db.scalar(select(Batch).where(Batch.product_id == product.id))
    assert batch.batch_no == "B-2026-01"


def test_a_vertical_without_expiry_receives_stock_but_no_batches(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    product = _product(db, store, sku="SHT-1")
    supplier = client.post(
        f"/purchasing/suppliers?store_id={store.id}", json={"name": "Jaipur Textiles"}
    ).json()
    order = client.post(
        f"/purchasing/orders?store_id={store.id}",
        json={
            "supplier_id": supplier["id"],
            "items": [{"product_id": product.id, "qty": 5, "unit_cost": "300.00",
                       "batch_no": "IGNORED"}],
        },
    ).json()
    client.post(f"/purchasing/orders/{order['id']}/receive?store_id={store.id}")

    db.expire_all()
    assert db.scalars(select(Batch)).all() == []
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    assert Decimal(str(stock.qty_on_hand)) == Decimal("15.000")


def test_receiving_twice_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    supplier = client.post(
        f"/purchasing/suppliers?store_id={store.id}", json={"name": "Indore Wholesale"}
    ).json()
    order = client.post(
        f"/purchasing/orders?store_id={store.id}",
        json={"supplier_id": supplier["id"],
              "items": [{"product_id": product.id, "qty": 5, "unit_cost": "50.00"}]},
    ).json()

    assert client.post(f"/purchasing/orders/{order['id']}/receive?store_id={store.id}").status_code == 200
    again = client.post(f"/purchasing/orders/{order['id']}/receive?store_id={store.id}")
    assert again.status_code == 409
    assert "already received" in again.json()["detail"]


def test_pending_payments_add_up(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    supplier = client.post(
        f"/purchasing/suppliers?store_id={store.id}", json={"name": "Indore Wholesale"}
    ).json()
    for _ in range(2):
        client.post(
            f"/purchasing/orders?store_id={store.id}",
            json={"supplier_id": supplier["id"],
                  "items": [{"product_id": product.id, "qty": 10, "unit_cost": "40.00"}]},
        )

    pending = client.get(f"/purchasing/pending-payments?store_id={store.id}").json()
    assert pending["orders"] == 2
    assert pending["amount"] == 800.0

    orders = client.get(f"/purchasing/orders?store_id={store.id}").json()
    client.post(f"/purchasing/orders/{orders[0]['id']}/pay?store_id={store.id}")

    pending = client.get(f"/purchasing/pending-payments?store_id={store.id}").json()
    assert pending["orders"] == 1


def test_a_cashier_cannot_touch_purchasing(role_client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    client = role_client("cashier")
    response = client.post(
        f"/purchasing/suppliers?store_id={store.id}", json={"name": "Sneaky Supplier"}
    )
    assert response.status_code == 403
