"""Jobs: a small state machine, and the reminder it fires without new trigger code."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models.agent import Reminder
from app.models.core import Customer, Job
from tests.test_segmentation import _store

PHONES = iter(range(2_000_000, 3_000_000))


def _customer(db, store, name: str = "Kavita Joshi") -> Customer:
    customer = Customer(store_id=store.id, name=name, phone=f"9{next(PHONES):09d}")
    db.add(customer)
    db.commit()
    return customer


def _job(client, store, customer, job_type: str = "alteration", promised: date | None = None):
    return client.post(
        f"/jobs?store_id={store.id}",
        json={
            "customer_id": customer.id,
            "type": job_type,
            "promised_date": str(promised) if promised else None,
        },
    )


# -- the flag gates the whole feature ----------------------------------------
def test_a_store_without_the_jobs_flag_refuses_to_take_one(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    customer = _customer(db, store)
    response = _job(client, store, customer)
    assert response.status_code == 422
    assert "jobs feature flag" in response.json()["detail"]


def test_the_board_reports_the_job_types_of_this_vertical(client, db) -> None:
    apparel = _store(db, "apparel", "Rangoli Fashion")
    grocery = _store(db, "grocery", "Sharma Kirana")

    apparel_board = client.get(f"/jobs/board?store_id={apparel.id}").json()
    grocery_board = client.get(f"/jobs/board?store_id={grocery.id}").json()

    assert apparel_board["takes_jobs"] is True
    assert "alteration" in apparel_board["job_types"]
    assert grocery_board["takes_jobs"] is False
    assert grocery_board["job_types"] == []


def test_a_job_type_the_store_does_not_offer_is_rejected(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    response = _job(client, store, customer, job_type="lens fitting")
    assert response.status_code == 422
    assert "alteration" in response.json()["detail"]


# -- the state machine -------------------------------------------------------
def test_the_happy_path_walks_every_state(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()
    assert job["status"] == "pending"

    for next_status in ("in_progress", "ready", "delivered"):
        response = client.post(
            f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": next_status}
        )
        assert response.status_code == 200, response.text
        assert response.json()["job"]["status"] == next_status

    db.expire_all()
    row = db.get(Job, job["id"])
    assert row.ready_at is not None and row.delivered_at is not None


def test_an_illegal_transition_returns_409_and_changes_nothing(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()

    response = client.post(
        f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "delivered"}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "pending" in detail and "delivered" in detail

    db.expire_all()
    assert db.get(Job, job["id"]).status == "pending"


def test_a_finished_job_cannot_be_reopened(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()
    for next_status in ("ready", "delivered"):
        client.post(f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": next_status})

    response = client.post(
        f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "in_progress"}
    )
    assert response.status_code == 409
    assert "it is finished" in response.json()["detail"]


def test_anything_open_can_be_cancelled(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()
    response = client.post(
        f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "cancelled"}
    )
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "cancelled"


def test_an_unknown_status_is_422(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()
    response = client.post(
        f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "posted"}
    )
    assert response.status_code == 422


# -- the reminder it fires ---------------------------------------------------
def test_marking_a_job_ready_queues_a_pickup_reminder_in_the_same_request(
    client, rules
) -> None:
    db = rules
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()

    before = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    assert before == []

    response = client.post(
        f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "ready"}
    )
    assert response.status_code == 200
    assert response.json()["reminders_queued"] == 1

    db.expire_all()
    reminders = db.scalars(
        select(Reminder).where(Reminder.store_id == store.id, Reminder.kind == "pickup_ready")
    ).all()
    assert len(reminders) == 1
    assert reminders[0].customer_id == customer.id
    assert "{" not in reminders[0].message


def test_a_job_that_never_becomes_ready_queues_nothing(client, rules) -> None:
    db = rules
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer).json()

    client.post(f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": "in_progress"})
    db.expire_all()
    assert db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all() == []


# -- the board ---------------------------------------------------------------
def test_overdue_jobs_are_flagged(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    late = _job(client, store, customer, promised=date.today() - timedelta(days=3)).json()
    soon = _job(client, store, customer, promised=date.today() + timedelta(days=3)).json()

    rows = {row["id"]: row for row in client.get(f"/jobs?store_id={store.id}").json()}
    assert rows[late["id"]]["is_overdue"] is True
    assert rows[soon["id"]]["is_overdue"] is False


def test_delivered_jobs_are_never_overdue(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    job = _job(client, store, customer, promised=date.today() - timedelta(days=10)).json()
    for next_status in ("ready", "delivered"):
        client.post(f"/jobs/{job['id']}/status?store_id={store.id}", json={"status": next_status})

    row = next(item for item in client.get(f"/jobs?store_id={store.id}").json() if item["id"] == job["id"])
    assert row["is_overdue"] is False


def test_board_counts_group_by_status(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")
    customer = _customer(db, store)
    first = _job(client, store, customer).json()
    _job(client, store, customer)
    client.post(f"/jobs/{first['id']}/status?store_id={store.id}", json={"status": "ready"})

    counts = client.get(f"/jobs/board?store_id={store.id}").json()["counts"]
    assert counts["pending"] == 1
    assert counts["ready"] == 1
    assert counts["delivered"] == 0
