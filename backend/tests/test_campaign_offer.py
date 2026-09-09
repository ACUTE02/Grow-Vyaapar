"""The offer a shopkeeper types, from the form to the row and back.

The poster drawing itself is covered in test_poster.py. These are about the
round trip and the rules around regenerating one.
"""
from __future__ import annotations

from app.models.agent import Campaign
from tests.test_segmentation import _store


def test_an_offer_is_saved_and_returned(client, db) -> None:
    store = _store(db, "grocery", "Offer Store")

    response = client.post(
        "/marketing/campaigns",
        params={"store_id": store.id},
        json={"occasion": "Diwali", "offer_text": "20% off all toothpaste"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["offer_text"] == "20% off all toothpaste"
    assert body["occasion"] == "Diwali"
    assert body["status"] == "draft"

    # And it survives a reload, which is what the history list depends on.
    listed = client.get("/marketing/campaigns", params={"store_id": store.id}).json()
    assert listed[0]["offer_text"] == "20% off all toothpaste"


def test_an_omitted_offer_stays_null(client, db) -> None:
    """A shopkeeper who just wants a festive poster does not have to invent a
    discount to get one."""
    store = _store(db, "grocery", "Offer Store")

    response = client.post(
        "/marketing/campaigns", params={"store_id": store.id}, json={"occasion": "Holi"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["offer_text"] is None


def test_a_blank_offer_is_stored_as_nothing_not_as_spaces(client, db) -> None:
    store = _store(db, "grocery", "Offer Store")

    response = client.post(
        "/marketing/campaigns",
        params={"store_id": store.id},
        json={"occasion": "Eid", "offer_text": "   "},
    )

    assert response.status_code == 201
    assert response.json()["offer_text"] is None


def test_an_over_long_offer_is_refused_by_the_api(client, db) -> None:
    """140 characters is the limit the poster can lay out; the API says so
    rather than letting the drawing code silently truncate."""
    store = _store(db, "grocery", "Offer Store")

    response = client.post(
        "/marketing/campaigns",
        params={"store_id": store.id},
        json={"occasion": "Diwali", "offer_text": "x" * 200},
    )

    assert response.status_code == 422


# -- regenerate --------------------------------------------------------------
def test_regenerate_redraws_the_same_row(client, db) -> None:
    """In place, so a second attempt does not clutter the history."""
    store = _store(db, "grocery", "Offer Store")
    created = client.post(
        "/marketing/campaigns",
        params={"store_id": store.id},
        json={"occasion": "Diwali", "offer_text": "Buy 1 Get 1 on soap"},
    ).json()

    response = client.post(
        f"/marketing/campaigns/{created['id']}/regenerate", params={"store_id": store.id}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"]
    assert body["occasion"] == "Diwali"
    assert body["offer_text"] == "Buy 1 Get 1 on soap"

    assert db.query(Campaign).filter(Campaign.store_id == store.id).count() == 1


def test_regenerate_is_refused_once_published(client, db) -> None:
    """Replacing a poster already in use is not something to do by accident."""
    store = _store(db, "grocery", "Offer Store")
    created = client.post(
        "/marketing/campaigns",
        params={"store_id": store.id},
        json={"occasion": "Diwali", "offer_text": "20% off"},
    ).json()
    client.patch(
        f"/marketing/campaigns/{created['id']}",
        params={"store_id": store.id},
        json={"status": "published"},
    )

    response = client.post(
        f"/marketing/campaigns/{created['id']}/regenerate", params={"store_id": store.id}
    )

    assert response.status_code == 409
    assert "published" in response.json()["detail"].lower()


def test_regenerate_is_scoped_to_the_store(client, db) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "pharmacy", "Store B")
    created = client.post(
        "/marketing/campaigns", params={"store_id": store_a.id}, json={"occasion": "Diwali"}
    ).json()

    response = client.post(
        f"/marketing/campaigns/{created['id']}/regenerate", params={"store_id": store_b.id}
    )

    assert response.status_code == 404


# -- the store address the poster prints -------------------------------------
def test_the_store_address_can_be_set_and_reaches_the_context(client, db) -> None:
    store = _store(db, "grocery", "Address Store")

    response = client.patch(
        f"/config/stores/{store.id}", json={"address": "12 MG Road, Indore"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["address"] == "12 MG Road, Indore"

    context = client.get(f"/config/stores/{store.id}/context").json()
    assert context["address"] == "12 MG Road, Indore"


def test_updating_the_address_leaves_the_other_columns_alone(client, db) -> None:
    """exclude_unset: clearing one field must not blank its neighbours."""
    store = _store(db, "grocery", "Address Store")
    client.patch(
        f"/config/stores/{store.id}",
        json={"address": "12 MG Road", "whatsapp_number": "+919812345601"},
    )

    client.patch(f"/config/stores/{store.id}", json={"address": "9 Station Road"})

    context = client.get(f"/config/stores/{store.id}/context").json()
    assert context["address"] == "9 Station Road"
    assert context["whatsapp_number"] == "+919812345601"


def test_a_cashier_cannot_change_store_details(db, role_client) -> None:
    """Config is a manager's job, and the middleware already says so - this
    pins that the new route is inside that rule rather than beside it."""
    store = _store(db, "grocery", "Address Store")
    client = role_client("cashier", store_id=store.id)

    response = client.patch(
        f"/config/stores/{store.id}", json={"address": "wherever they like"}
    )

    assert response.status_code == 403
