"""A shop owner edits their own store's details, and nobody else's.

PATCH /config/stores/{id} is the only way these columns change. The tests
below cover the happy path, every validation rule, the two fields that cannot
be cleared because the database will not have it, unknown keys, and the two
ways somebody else's store might be reached.
"""
from __future__ import annotations

from tests.test_segmentation import _store

VALID_GSTIN = "27AAPFU0939F1ZV"


def _details(client, store_id: int) -> dict:
    response = client.get(f"/config/stores/{store_id}/context")
    assert response.status_code == 200, response.text
    return response.json()


# -- the happy path, verified by reading it back -----------------------------
def test_every_declared_field_can_be_edited_and_persists(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = client.patch(
        f"/config/stores/{store.id}",
        json={
            "name": "Sharma Kirana Bazaar",
            "city": "Nagpur",
            "language": "hi-en",
            "address": "12 MG Road, near the bus stand",
            "gstin": VALID_GSTIN,
            "whatsapp_number": "+919812345678",
            "google_review_url": "https://g.page/r/sharma/review",
        },
    )
    assert response.status_code == 200, response.text

    # Read it back through a second request, not from the response body: a
    # write that only appears to have happened is the bug worth testing for.
    context = _details(client, store.id)
    assert context["store_name"] == "Sharma Kirana Bazaar"
    assert context["city"] == "Nagpur"
    assert context["language"] == "hi-en"
    assert context["address"] == "12 MG Road, near the bus stand"
    assert context["gstin"] == VALID_GSTIN
    assert context["whatsapp_number"] == "+919812345678"
    assert context["google_review_url"] == "https://g.page/r/sharma/review"


def test_a_partial_update_leaves_every_other_field_alone(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()
    client.patch(
        f"/config/stores/{store.id}",
        json={"city": "Nagpur", "gstin": VALID_GSTIN, "address": "12 MG Road"},
    )

    client.patch(f"/config/stores/{store.id}", json={"address": "9 Station Road"})

    context = _details(client, store.id)
    assert context["address"] == "9 Station Road"
    assert context["city"] == "Nagpur", "an unsent field was overwritten"
    assert context["gstin"] == VALID_GSTIN, "an unsent field was overwritten"


def test_an_optional_field_can_be_cleared(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()
    client.patch(
        f"/config/stores/{store.id}", json={"address": "12 MG Road", "gstin": VALID_GSTIN}
    )

    assert (
        client.patch(
            f"/config/stores/{store.id}", json={"address": "", "gstin": None}
        ).status_code
        == 200
    )

    context = _details(client, store.id)
    assert context["address"] is None
    assert context["gstin"] is None


def test_values_are_normalised_on_the_way_in(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    client.patch(
        f"/config/stores/{store.id}",
        json={
            "name": "  Sharma Kirana Bazaar  ",
            "gstin": "27aapfu0939f1zv",
            "whatsapp_number": "+91 98123-45678",
        },
    )

    context = _details(client, store.id)
    assert context["store_name"] == "Sharma Kirana Bazaar"
    assert context["gstin"] == VALID_GSTIN
    assert context["whatsapp_number"] == "+919812345678"


# -- validation --------------------------------------------------------------
def test_a_gstin_that_is_not_a_gstin_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = client.patch(f"/config/stores/{store.id}", json={"gstin": "NOT-A-GSTIN"})

    assert response.status_code == 422
    assert "GSTIN" in response.text
    assert _details(client, store.id)["gstin"] is None


def test_a_language_the_app_cannot_write_in_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = client.patch(f"/config/stores/{store.id}", json={"language": "fr"})

    assert response.status_code == 422
    assert "en, hi, hi-en" in response.text


def test_a_phone_number_that_is_not_one_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = client.patch(
        f"/config/stores/{store.id}", json={"whatsapp_number": "call the shop"}
    )

    assert response.status_code == 422


def test_a_review_link_must_be_a_url(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()
    before = _details(client, store.id)["google_review_url"]

    response = client.patch(
        f"/config/stores/{store.id}", json={"google_review_url": "javascript:alert(1)"}
    )

    assert response.status_code == 422
    assert _details(client, store.id)["google_review_url"] == before


def test_a_one_character_name_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    assert client.patch(f"/config/stores/{store.id}", json={"name": "x"}).status_code == 422
    assert client.patch(f"/config/stores/{store.id}", json={"name": "   "}).status_code == 422


def test_the_name_and_city_cannot_be_cleared(client, db) -> None:
    """Both are NOT NULL. A null here is a sentence, not an integrity error."""
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = client.patch(f"/config/stores/{store.id}", json={"name": None, "city": None})

    assert response.status_code == 422
    assert "cannot be cleared" in response.text
    assert _details(client, store.id)["store_name"] == "Sharma Kirana"


# -- mass assignment ---------------------------------------------------------
def test_a_field_that_is_not_a_setting_is_rejected_not_ignored(client, db) -> None:
    """store_id and vertical_id are identity, not settings. A payload trying to
    move a store between tenants or verticals should fail loudly."""
    store = _store(db, "grocery", "Sharma Kirana")
    other = _store(db, "pharmacy", "Jeevan Medical")
    db.commit()

    for payload in (
        {"store_id": other.id},
        {"vertical_id": other.vertical_id},
        {"id": other.id},
        {"created_at": "2020-01-01T00:00:00"},
    ):
        response = client.patch(f"/config/stores/{store.id}", json=payload)
        assert response.status_code == 422, f"{payload} was not rejected"

    db.expire_all()
    assert db.get(type(store), store.id).vertical_id != other.vertical_id


# -- authorisation -----------------------------------------------------------
def test_another_stores_settings_cannot_be_edited(db, role_client) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "pharmacy", "Store B")
    db.commit()

    client = role_client("manager", store_id=store_b.id)
    response = client.patch(f"/config/stores/{store_a.id}", json={"name": "Taken over"})

    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(type(store_a), store_a.id).name == "Store A"


def test_settings_cannot_be_edited_without_signing_in(db, anon_client) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = anon_client.patch(f"/config/stores/{store.id}", json={"name": "Anonymous"})

    assert response.status_code == 401
    db.expire_all()
    assert db.get(type(store), store.id).name == "Sharma Kirana"


def test_a_cashier_cannot_rename_their_own_store(db, role_client) -> None:
    """Editing the shop's identity is a manager action, enforced in the API
    rather than by hiding the button."""
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    client = role_client("cashier", store_id=store.id)
    response = client.patch(f"/config/stores/{store.id}", json={"name": "Cashier's Kirana"})

    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(type(store), store.id).name == "Sharma Kirana"


def test_a_manager_can_edit_the_store_they_belong_to(db, role_client) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    client = role_client("manager", store_id=store.id)
    response = client.patch(f"/config/stores/{store.id}", json={"city": "Nagpur"})

    assert response.status_code == 200, response.text
    assert response.json()["city"] == "Nagpur"
