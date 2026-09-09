"""Cross-tenant access through a resource id, not through the store id.

The store-context guard covers the store id, wherever it arrives - query
string, path, or both. It cannot cover this: the attacker passes their OWN
store id, so every check on that value passes, and smuggles another store's
resource id into the path. Whether that works is decided further in, by
whether the service loading the row also checks who owns it.

One test per by-id route that takes a tenant-owned resource. A refusal is 403
or 404 - which of the two is a design choice, and both are correct here as
long as no data comes back and no write lands.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.agent import Campaign, Reminder
from app.models.commerce import Coupon
from app.models.core import Customer, Job, Product, StockLevel, Transaction
from tests.test_segmentation import _store

REFUSED = (403, 404)


@pytest.fixture()
def victim_and_attacker(db):
    """Store B holds the data. The attacker is a manager of store A and always
    asks with store A's id, which is genuinely theirs."""
    attacker_store = _store(db, "grocery", "Attacker Store")
    victim_store = _store(db, "optical", "Victim Store")
    db.flush()
    return attacker_store, victim_store


def _client_for(role_client, store):
    return role_client("manager", store_id=store.id)


def _customer(db, store, name="Victim Customer", phone="9000000001"):
    customer = Customer(store_id=store.id, name=name, phone=phone)
    db.add(customer)
    db.flush()
    return customer


def _product(db, store, sku="VIC-1"):
    product = Product(
        store_id=store.id,
        sku=sku,
        name="Victim Product",
        cost_price=Decimal("10.00"),
        sell_price=Decimal("25.00"),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal("50"), reorder_point=Decimal("5"))
    )
    db.flush()
    return product


# -- customers ---------------------------------------------------------------
def test_a_foreign_customer_cannot_be_read(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.get(f"/customers/{customer.id}", params={"store_id": attacker_store.id})

    assert response.status_code in REFUSED, response.text
    assert "Victim Customer" not in response.text


def test_a_foreign_customer_cannot_be_edited(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.patch(
        f"/customers/{customer.id}",
        params={"store_id": attacker_store.id},
        json={"name": "Renamed by an outsider"},
    )

    assert response.status_code in REFUSED, response.text
    db.expire_all()
    assert db.get(Customer, customer.id).name == "Victim Customer"


def test_a_foreign_customers_records_are_closed(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}
    assert client.get(f"/customers/{customer.id}/records", params=params).status_code in REFUSED
    assert (
        client.post(
            f"/customers/{customer.id}/records",
            params=params,
            json={"record_type": "note", "data": {"text": "injected"}},
        ).status_code
        in REFUSED
    )


# -- products ----------------------------------------------------------------
def test_a_foreign_product_cannot_be_read_or_edited(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    product = _product(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}

    assert client.get(f"/products/{product.id}", params=params).status_code in REFUSED
    assert (
        client.patch(
            f"/products/{product.id}", params=params, json={"sell_price": "0.01"}
        ).status_code
        in REFUSED
    )
    db.expire_all()
    assert db.get(Product, product.id).sell_price == Decimal("25.00")


# -- billing -----------------------------------------------------------------
def test_a_foreign_transaction_is_closed(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    transaction = Transaction(
        store_id=victim_store.id, invoice_no="VIC-0001", total=Decimal("500.00")
    )
    db.add(transaction)
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}

    assert (
        client.get(f"/billing/transactions/{transaction.id}", params=params).status_code in REFUSED
    )
    assert (
        client.get(
            f"/billing/transactions/{transaction.id}/invoice.html", params=params
        ).status_code
        in REFUSED
    )
    assert (
        client.post(f"/billing/transactions/{transaction.id}/refund", params=params).status_code
        in REFUSED
    )
    db.expire_all()
    assert db.get(Transaction, transaction.id).status == "completed"


# -- marketing ---------------------------------------------------------------
def test_a_foreign_reminder_cannot_be_sent_retried_or_dismissed(
    db, role_client, victim_and_attacker
) -> None:
    """The most dangerous one on the list: a send spends the victim's delivery
    budget and messages the victim's customer."""
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    reminder = Reminder(
        store_id=victim_store.id,
        customer_id=customer.id,
        kind="revisit",
        message="Victim store reminder",
        status="failed",
    )
    db.add(reminder)
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}

    assert (
        client.post(f"/marketing/reminders/{reminder.id}/send", params=params).status_code
        in REFUSED
    )
    assert (
        client.post(f"/marketing/reminders/{reminder.id}/retry", params=params).status_code
        in REFUSED
    )
    assert (
        client.post(f"/marketing/reminders/{reminder.id}/dismiss", params=params).status_code
        in REFUSED
    )

    db.expire_all()
    assert db.get(Reminder, reminder.id).status == "failed", "no state change may survive"


def test_a_foreign_reminder_cannot_be_swept_into_a_bulk_send(
    db, role_client, victim_and_attacker
) -> None:
    """The bulk endpoint takes a list of ids in the body - a third way in, and
    the one a store-id check never sees."""
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    reminder = Reminder(
        store_id=victim_store.id,
        customer_id=customer.id,
        kind="revisit",
        message="Victim store reminder",
        status="queued",
    )
    db.add(reminder)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.post(
        "/marketing/reminders/send",
        params={"store_id": attacker_store.id},
        json={"reminder_ids": [reminder.id]},
    )

    db.expire_all()
    assert db.get(Reminder, reminder.id).status == "queued", (
        f"a foreign reminder was touched by a bulk send (HTTP {response.status_code})"
    )


def test_a_foreign_campaign_cannot_be_edited_or_regenerated(
    db, role_client, victim_and_attacker
) -> None:
    attacker_store, victim_store = victim_and_attacker
    campaign = Campaign(store_id=victim_store.id, occasion="Diwali", status="draft")
    db.add(campaign)
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}

    assert (
        client.patch(
            f"/marketing/campaigns/{campaign.id}", params=params, json={"status": "published"}
        ).status_code
        in REFUSED
    )
    assert (
        client.post(f"/marketing/campaigns/{campaign.id}/regenerate", params=params).status_code
        in REFUSED
    )
    db.expire_all()
    assert db.get(Campaign, campaign.id).status == "draft"


# -- jobs --------------------------------------------------------------------
def test_a_foreign_job_cannot_be_advanced(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    job = Job(
        store_id=victim_store.id,
        customer_id=customer.id,
        type="lens fitting",
        status="pending",
        promised_date=date.today() + timedelta(days=2),
    )
    db.add(job)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.post(
        f"/jobs/{job.id}/status",
        params={"store_id": attacker_store.id},
        json={"status": "delivered"},
    )

    assert response.status_code in REFUSED, response.text
    db.expire_all()
    assert db.get(Job, job.id).status == "pending"


# -- loyalty -----------------------------------------------------------------
def test_a_foreign_customers_loyalty_is_not_readable(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    customer = _customer(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.get(
        f"/loyalty/customers/{customer.id}", params={"store_id": attacker_store.id}
    )
    assert response.status_code in REFUSED, response.text


def test_a_foreign_coupon_cannot_be_quoted(db, role_client, victim_and_attacker) -> None:
    attacker_store, victim_store = victim_and_attacker
    coupon = Coupon(
        store_id=victim_store.id,
        code="VICTIM50",
        discount_type="percent",
        discount_value=Decimal("50"),
        valid_from=date.today(),
        valid_to=date.today() + timedelta(days=30),
    )
    db.add(coupon)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.get(
        "/loyalty/coupons/VICTIM50/quote",
        params={"store_id": attacker_store.id, "subtotal": "1000"},
    )
    assert response.status_code in REFUSED, response.text


# -- purchasing --------------------------------------------------------------
def test_a_foreign_supplier_cannot_be_edited(db, role_client, victim_and_attacker) -> None:
    from app.models.admin import Supplier

    attacker_store, victim_store = victim_and_attacker
    supplier = Supplier(store_id=victim_store.id, name="Victim Supplier")
    db.add(supplier)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.patch(
        f"/purchasing/suppliers/{supplier.id}",
        params={"store_id": attacker_store.id},
        json={"name": "Renamed by an outsider"},
    )

    assert response.status_code in REFUSED, response.text
    db.expire_all()
    assert db.get(Supplier, supplier.id).name == "Victim Supplier"


# -- and the attacker's own resources still work -----------------------------
def test_none_of_this_blocks_the_attackers_own_data(db, role_client, victim_and_attacker) -> None:
    """A guard that refuses everything is not a guard, it is an outage."""
    attacker_store, _victim = victim_and_attacker
    customer = _customer(db, attacker_store, name="Own Customer", phone="9000000009")
    product = _product(db, attacker_store, sku="OWN-1")
    db.commit()

    client = _client_for(role_client, attacker_store)
    params = {"store_id": attacker_store.id}

    assert client.get(f"/customers/{customer.id}", params=params).status_code == 200
    assert client.get(f"/products/{product.id}", params=params).status_code == 200


# -- the request body, which is the third way a foreign id arrives ------------
def test_a_bill_cannot_be_built_from_another_stores_product(
    db, role_client, victim_and_attacker
) -> None:
    """Selling somebody else's stock would decrement their shelf and bank the
    money here. The product id arrives in the body, so no store-id check sees it."""
    attacker_store, victim_store = victim_and_attacker
    victim_product = _product(db, victim_store)
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.post(
        "/billing/transactions",
        params={"store_id": attacker_store.id},
        json={"lines": [{"product_id": victim_product.id, "qty": "2"}]},
    )

    assert response.status_code in (400, 403, 404, 409, 422), response.text
    db.expire_all()
    stock = db.scalar(
        select(StockLevel).where(StockLevel.product_id == victim_product.id)
    )
    assert stock.qty_on_hand == Decimal("50"), "the victim's stock moved"


def test_a_bill_cannot_be_attached_to_another_stores_customer(
    db, role_client, victim_and_attacker
) -> None:
    attacker_store, victim_store = victim_and_attacker
    victim_customer = _customer(db, victim_store)
    own_product = _product(db, attacker_store, sku="OWN-2")
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.post(
        "/billing/transactions",
        params={"store_id": attacker_store.id},
        json={
            "customer_id": victim_customer.id,
            "lines": [{"product_id": own_product.id, "qty": "1"}],
        },
    )

    assert response.status_code in (400, 403, 404, 409, 422), response.text
    db.expire_all()
    assert db.scalar(
        select(Transaction).where(Transaction.customer_id == victim_customer.id)
    ) is None, "a bill was attached to another store's customer"


def test_a_store_id_in_the_body_cannot_override_the_one_in_the_query(
    db, role_client, victim_and_attacker
) -> None:
    """Mass assignment: if the model took store_id from the payload, this
    customer would be created inside the victim's store."""
    attacker_store, victim_store = victim_and_attacker
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.post(
        "/customers",
        params={"store_id": attacker_store.id},
        json={"name": "Smuggled", "phone": "9000000077", "store_id": victim_store.id},
    )

    if response.status_code == 201:
        assert response.json()["store_id"] == attacker_store.id
    landed = db.scalars(
        select(Customer).where(Customer.store_id == victim_store.id)
    ).all()
    assert landed == [], "a customer was created inside another store"


# -- a missing or nonsense store context -------------------------------------
def test_a_missing_store_id_is_refused_not_defaulted(db, role_client, victim_and_attacker) -> None:
    attacker_store, _victim = victim_and_attacker
    db.commit()

    client = _client_for(role_client, attacker_store)
    assert client.get("/customers").status_code == 422


def test_a_store_that_does_not_exist_is_refused(db, role_client, victim_and_attacker) -> None:
    attacker_store, _victim = victim_and_attacker
    db.commit()

    client = _client_for(role_client, attacker_store)
    response = client.get("/customers", params={"store_id": 9_999_999})
    assert response.status_code in (403, 404), response.text
