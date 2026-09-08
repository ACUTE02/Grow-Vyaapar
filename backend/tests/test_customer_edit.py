"""Correcting a customer's identity: every field, still store-scoped.

Records stay append-only - a correction there is a new row. Identity is the
opposite: a mistyped name or phone must be fixable in place, and until now a
phone could not be, because CustomerUpdate had no phone field at all and the
PATCH quietly returned 200 having changed nothing.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.core import Customer
from tests.test_segmentation import _store


def _add(client, store, **overrides) -> dict:
    payload = {"name": "Meera Iyer", "phone": "9876543210"}
    payload.update(overrides)
    response = client.post(f"/customers?store_id={store.id}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_every_identity_field_can_be_corrected(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, store)

    response = client.patch(
        f"/customers/{created['id']}?store_id={store.id}",
        json={
            "name": "Meera Iyer-Rao",
            "phone": "9812345678",
            "dob": "1990-04-12",
            "anniversary": "2015-11-30",
            "notes": "prefers evening delivery",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["name"] == "Meera Iyer-Rao"
    assert updated["phone"] == "9812345678", "a mistyped phone must be correctable"
    assert updated["dob"] == "1990-04-12"
    assert updated["anniversary"] == "2015-11-30"
    assert updated["notes"] == "prefers evening delivery"

    db.expire_all()
    stored = db.get(Customer, created["id"])
    assert stored.phone == "9812345678", "and it must actually reach the database"


def test_a_partial_update_leaves_other_fields_alone(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, store, dob="1990-04-12", notes="keep me")

    updated = client.patch(
        f"/customers/{created['id']}?store_id={store.id}", json={"phone": "9812345678"}
    ).json()

    assert updated["phone"] == "9812345678"
    assert updated["name"] == created["name"]
    assert updated["dob"] == "1990-04-12"
    assert updated["notes"] == "keep me"


def test_a_phone_that_is_not_an_indian_mobile_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, store)

    for bad in ("12345", "1234567890", "abcdefghij"):
        response = client.patch(
            f"/customers/{created['id']}?store_id={store.id}", json={"phone": bad}
        )
        assert response.status_code == 422, f"{bad!r} should not be accepted"

    db.expire_all()
    assert db.get(Customer, created["id"]).phone == "9876543210", "nothing was corrupted"


def test_taking_another_customers_phone_is_a_clear_conflict(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    first = _add(client, store, name="Meera Iyer", phone="9876543210")
    second = _add(client, store, name="Ravi Kumar", phone="9812345678")

    response = client.patch(
        f"/customers/{second['id']}?store_id={store.id}", json={"phone": first["phone"]}
    )
    assert response.status_code == 409, response.text
    assert "Meera Iyer" in response.json()["detail"], "say who already has it"

    db.expire_all()
    assert db.get(Customer, second["id"]).phone == "9812345678"


def test_keeping_your_own_phone_is_not_a_conflict(client, db) -> None:
    """Re-submitting the form unchanged must not collide with yourself."""
    store = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, store)

    response = client.patch(
        f"/customers/{created['id']}?store_id={store.id}",
        json={"name": "Meera I.", "phone": created["phone"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Meera I."


def test_the_same_phone_may_exist_at_a_different_store(client, db) -> None:
    """The unique constraint is per store, and editing must respect that."""
    first = _store(db, "grocery", "Sharma Kirana")
    second = _store(db, "pharmacy", "Jeevan Medical")
    _add(client, first, phone="9876543210")
    theirs = _add(client, second, name="Ravi Kumar", phone="9812345678")

    response = client.patch(
        f"/customers/{theirs['id']}?store_id={second.id}", json={"phone": "9876543210"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == "9876543210"


def test_a_customer_cannot_be_edited_from_another_store(client, db) -> None:
    theirs = _store(db, "pharmacy", "Jeevan Medical")
    other = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, theirs, phone="9765043210")

    response = client.patch(
        f"/customers/{created['id']}?store_id={other.id}", json={"name": "Hijacked"}
    )
    assert response.status_code == 404, response.text

    db.expire_all()
    assert db.get(Customer, created["id"]).name != "Hijacked"


def test_editing_identity_does_not_disturb_the_record_log(client, db) -> None:
    """Records stay append-only; correcting a name is not a record edit."""
    store = _store(db, "pharmacy", "Jeevan Medical")
    created = _add(client, store)
    client.post(
        f"/customers/{created['id']}/records?store_id={store.id}",
        json={"record_type": "prescription", "data": {"note": "original"}},
    )

    client.patch(
        f"/customers/{created['id']}?store_id={store.id}",
        json={"name": "Meera Iyer-Rao", "phone": "9812345678"},
    )

    records = client.get(
        f"/customers/{created['id']}/records?store_id={store.id}"
    ).json()
    assert len(records) == 1
    assert records[0]["data"] == {"note": "original"}


def test_a_new_customer_is_only_listed_under_its_own_store(client, db) -> None:
    """Problem 1, as a test: the row persists, it is just store-scoped."""
    theirs = _store(db, "pharmacy", "Jeevan Medical")
    other = _store(db, "grocery", "Sharma Kirana")
    created = _add(client, theirs, name="Ronit", phone="7652042022")

    here = client.get(f"/customers?store_id={theirs.id}&q=Ronit").json()
    assert [row["id"] for row in here] == [created["id"]]

    elsewhere = client.get(f"/customers?store_id={other.id}&q=Ronit").json()
    assert elsewhere == [], "no cross-store leakage"

    assert db.scalar(select(Customer).where(Customer.id == created["id"])) is not None
