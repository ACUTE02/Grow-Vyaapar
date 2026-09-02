"""The context resolver is the only place configuration is read (hard rule 4)."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models.config import Store, StoreConfig, Vertical
from app.verticals.context import resolve_store_context


def _first_two_verticals(db) -> tuple[Vertical, Vertical]:
    verticals = list(db.scalars(select(Vertical).order_by(Vertical.code)).all())
    assert len(verticals) == 8
    return verticals[0], verticals[1]


def _make_store(db, vertical: Vertical, name: str) -> Store:
    store = Store(vertical_id=vertical.id, name=name, city="Indore", language="en")
    db.add(store)
    db.commit()
    return store


def test_context_merges_defaults_and_overrides(db) -> None:
    vertical, _ = _first_two_verticals(db)
    store = _make_store(db, vertical, "Test Store")

    context = resolve_store_context(db, store.id)
    assert context.vertical_code == vertical.code
    assert context.cfg_int("inactive_days") == vertical.default_config["inactive_days"]

    db.add(StoreConfig(store_id=store.id, key="inactive_days", value=json.dumps(7)))
    db.commit()

    context = resolve_store_context(db, store.id)
    assert context.cfg_int("inactive_days") == 7, "store override must win over the default"


def test_two_stores_of_different_verticals_get_different_thresholds(db) -> None:
    first, second = _first_two_verticals(db)
    store_a = _make_store(db, first, "Store A")
    store_b = _make_store(db, second, "Store B")

    ctx_a = resolve_store_context(db, store_a.id)
    ctx_b = resolve_store_context(db, store_b.id)

    assert ctx_a.vertical_code != ctx_b.vertical_code
    differing = [
        key
        for key in ctx_a.config
        if ctx_a.config.get(key) != ctx_b.config.get(key)
    ]
    assert differing, "two verticals must differ in at least one config value"


def test_context_endpoint_returns_merged_config(client, db) -> None:
    vertical, _ = _first_two_verticals(db)
    store = _make_store(db, vertical, "API Store")

    response = client.get(f"/config/stores/{store.id}/context")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == store.id
    assert body["config"]["inactive_days"] == vertical.default_config["inactive_days"]
    assert set(body["feature_flags"]) == {"expiry", "serial", "jobs", "appointments"}

    put = client.put(
        f"/config/stores/{store.id}/config", json={"key": "inactive_days", "value": 5}
    )
    assert put.status_code == 200
    assert put.json()["config"]["inactive_days"] == 5


def test_unknown_store_is_404(client) -> None:
    assert client.get("/config/stores/9999/context").status_code == 404
