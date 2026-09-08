"""Delivery: consent, the daily cap, and what the provider said.

No test here touches a network. The Cloud adapter is exercised against a stubbed
transport, because a passing test suite must never be able to message a real
person.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.agents import reminders as reminder_agent
from app.agents import segmentation
from app.delivery import twilio_wa, whatsapp_cloud
from app.delivery.base import DeliveryResult, get_adapter
from app.models.agent import Reminder
from app.models.base import utcnow
from app.models.core import Customer
from app.services import delivery_service
from app.settings import settings
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _catalog, _history, _store


@pytest.fixture()
def outbox(rules):
    """A store with a queue of drafted, unsent reminders."""
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    _history(db, store, product, count=6, days_ago=140, spend="600")
    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    reminder_agent.run(db, context, llm_budget=0)
    db.commit()
    return db, store, context


# -- consent -----------------------------------------------------------------
def test_the_engine_never_drafts_for_an_opted_out_customer(rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    customers = _history(db, store, product, count=4, days_ago=140, spend="600")
    customers[0].marketing_opt_in = False
    customers[1].marketing_opt_in = False
    db.commit()

    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    reminder_agent.run(db, context, llm_budget=0)
    db.commit()

    contacted = {
        reminder.customer_id
        for reminder in db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    }
    assert customers[0].id not in contacted
    assert customers[1].id not in contacted
    assert customers[2].id in contacted


def test_the_post_sale_hook_respects_consent(client, rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    customer = _history(db, store, product, count=1, days_ago=3, spend="200")[0]
    customer.marketing_opt_in = False
    db.commit()

    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"customer_id": customer.id, "lines": [{"product_id": product.id, "qty": 1}]},
    )
    assert response.status_code == 201

    db.expire_all()
    assert db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all() == []


def test_consent_is_editable_through_the_api(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    created = client.post(
        f"/customers?store_id={store.id}",
        json={"name": "Meera Iyer", "phone": "9876543210"},
    ).json()
    assert created["marketing_opt_in"] is True

    updated = client.patch(
        f"/customers/{created['id']}?store_id={store.id}",
        json={"marketing_opt_in": False},
    ).json()
    assert updated["marketing_opt_in"] is False

    listed = client.get(f"/customers?store_id={store.id}").json()
    assert listed[0]["marketing_opt_in"] is False


def test_sending_to_an_opted_out_customer_fails_with_a_reason(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    customer = db.get(Customer, reminder.customer_id)
    customer.marketing_opt_in = False
    db.commit()

    outcome = delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()

    assert outcome.sent == 0 and outcome.failed == 1
    db.refresh(reminder)
    assert reminder.status == "failed"
    assert "opted out" in reminder.provider_response


# -- the cap -----------------------------------------------------------------
def test_the_daily_cap_blocks_the_next_send_with_a_clear_message(outbox, monkeypatch) -> None:
    db, store, context = outbox
    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    assert len(reminders) > 3

    monkeypatch.setattr(settings, "delivery_daily_cap", 2)

    first = delivery_service.send_reminders(
        db, context, [reminder.id for reminder in reminders[:3]]
    )
    db.commit()
    assert first.sent == 2, "the cap stops the third"
    assert first.skipped == 1
    assert "daily cap" in first.results[-1]["detail"]
    assert first.cap_remaining == 0

    with pytest.raises(Exception) as excinfo:
        delivery_service.send_reminders(db, context, [reminders[3].id])
    assert "daily send cap" in str(excinfo.value)

    db.refresh(reminders[2])
    assert reminders[2].status == "queued", "a capped message stays in the queue"


def test_cap_status_is_reported(client, outbox, monkeypatch) -> None:
    db, store, context = outbox
    monkeypatch.setattr(settings, "delivery_daily_cap", 5)
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))

    delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()

    status = client.get(f"/marketing/delivery/status?store_id={store.id}").json()
    assert status["adapter"] == "console"
    assert status["daily_cap"] == 5
    assert status["sent_today"] == 1
    assert status["cap_remaining"] == 4


def test_yesterdays_sends_do_not_count_against_todays_cap(outbox, monkeypatch) -> None:
    db, store, context = outbox
    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    for reminder in reminders[:2]:
        reminder.status = "sent"
        reminder.sent_at = utcnow() - timedelta(days=1)
    db.commit()

    monkeypatch.setattr(settings, "delivery_daily_cap", 2)
    assert delivery_service.cap_remaining(db, store.id) == 2


# -- the batch endpoint ------------------------------------------------------
def test_sending_is_an_explicit_act_on_an_explicit_list(client, outbox) -> None:
    db, store, context = outbox
    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    chosen = [reminders[0].id, reminders[1].id]

    response = client.post(
        f"/marketing/reminders/send?store_id={store.id}", json={"reminder_ids": chosen}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] == 2
    assert {row["reminder_id"] for row in body["results"]} == set(chosen)

    db.expire_all()
    untouched = [r for r in db.scalars(select(Reminder)).all() if r.id not in chosen]
    assert all(reminder.status == "queued" for reminder in untouched)


def test_an_already_sent_reminder_is_skipped_not_resent(client, outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()

    outcome = delivery_service.send_reminders(db, context, [reminder.id])
    assert outcome.sent == 0 and outcome.skipped == 1


def test_the_provider_response_is_kept(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()
    db.refresh(reminder)
    assert reminder.status == "sent"
    assert reminder.provider_response and "console" in reminder.provider_response


# -- retrying a failed send ---------------------------------------------------
def _fail(db, reminder: Reminder, detail: str = "Twilio error 21654: ContentSid Required") -> None:
    """A reminder that a real send already knocked into 'failed', without
    needing a network call - the adapter's own job is tested elsewhere."""
    reminder.status = "failed"
    reminder.provider_response = detail
    db.commit()


def test_retry_moves_a_failed_reminder_back_to_queued(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    retried = delivery_service.retry_reminder(db, context, reminder.id)
    db.commit()

    assert retried.status == "queued"
    db.refresh(reminder)
    assert reminder.status == "queued"


def test_retry_clears_the_previous_failure_reason(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder, "Twilio error 21654: ContentSid Required")

    delivery_service.retry_reminder(db, context, reminder.id)
    db.commit()
    db.refresh(reminder)
    assert reminder.provider_response is None
    assert reminder.sent_at is None


def test_retry_does_not_send_anything_itself(outbox) -> None:
    """Retry only flips a status. It never calls the adapter, and Send is
    still the only thing that performs a delivery attempt."""
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    delivery_service.retry_reminder(db, context, reminder.id)
    db.commit()
    db.refresh(reminder)
    assert reminder.status == "queued", "retry must land on queued, never on sent"
    assert reminder.sent_at is None


def test_a_queued_reminder_cannot_be_retried(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    assert reminder.status == "queued"

    with pytest.raises(Exception, match="not failed"):
        delivery_service.retry_reminder(db, context, reminder.id)


def test_a_sent_reminder_cannot_be_retried(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()
    assert reminder.status == "sent"

    with pytest.raises(Exception, match="not failed"):
        delivery_service.retry_reminder(db, context, reminder.id)


def test_a_dismissed_reminder_cannot_be_retried(outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    reminder.status = "dismissed"
    db.commit()

    with pytest.raises(Exception, match="not failed"):
        delivery_service.retry_reminder(db, context, reminder.id)


def test_retrying_twice_in_a_row_is_rejected_the_second_time(outbox) -> None:
    """Double-click protection: the first retry consumes the failed state, so
    a second click (or a retried request) has nothing eligible to act on."""
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    delivery_service.retry_reminder(db, context, reminder.id)
    db.commit()
    assert reminder.status == "queued"

    with pytest.raises(Exception, match="not failed"):
        delivery_service.retry_reminder(db, context, reminder.id)
    db.refresh(reminder)
    assert reminder.status == "queued", "the second call must not have changed anything"


def test_retry_is_scoped_to_the_store(outbox, db) -> None:
    from tests.test_segmentation import _store as make_store

    _, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    other_store = make_store(db, "pharmacy", "Jeevan Medical")
    other_context = resolve_store_context(db, other_store.id)

    with pytest.raises(Exception, match="does not belong to"):
        delivery_service.retry_reminder(db, other_context, reminder.id)
    db.refresh(reminder)
    assert reminder.status == "failed", "a cross-store attempt must not modify the row"


def test_a_retried_reminder_can_be_sent_again_through_the_normal_adapter_path(outbox) -> None:
    """End to end: failed -> retry -> queued -> Send -> the same adapter path
    every other send goes through, not a bypass."""
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    delivery_service.retry_reminder(db, context, reminder.id)
    db.commit()

    outcome = delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()
    db.refresh(reminder)

    assert outcome.sent == 1
    assert reminder.status == "sent"
    assert reminder.provider_response and "console" in reminder.provider_response


# -- the retry endpoint --------------------------------------------------------
def test_the_retry_endpoint_requeues_and_reports_the_new_status(client, outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder, "Twilio error 21654: ContentSid Required")

    response = client.post(
        f"/marketing/reminders/{reminder.id}/retry?store_id={store.id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["provider_response"] is None

    db.expire_all()
    assert db.get(Reminder, reminder.id).status == "queued"


def test_the_retry_endpoint_rejects_a_queued_reminder(client, outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    assert reminder.status == "queued"

    response = client.post(
        f"/marketing/reminders/{reminder.id}/retry?store_id={store.id}"
    )
    assert response.status_code == 409, response.text


def test_the_retry_endpoint_rejects_an_already_sent_reminder(client, outbox) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    delivery_service.send_reminders(db, context, [reminder.id])
    db.commit()

    response = client.post(
        f"/marketing/reminders/{reminder.id}/retry?store_id={store.id}"
    )
    assert response.status_code == 409, response.text


def test_the_retry_endpoint_is_store_scoped(client, outbox, db) -> None:
    from tests.test_segmentation import _store as make_store

    _, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    other_store = make_store(db, "pharmacy", "Jeevan Medical")

    response = client.post(
        f"/marketing/reminders/{reminder.id}/retry?store_id={other_store.id}"
    )
    assert response.status_code == 404, response.text

    db.expire_all()
    assert db.get(Reminder, reminder.id).status == "failed", "no cross-store mutation"


def test_double_clicking_retry_through_the_api_is_rejected_the_second_time(
    client, outbox
) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    _fail(db, reminder)

    first = client.post(f"/marketing/reminders/{reminder.id}/retry?store_id={store.id}")
    assert first.status_code == 200

    second = client.post(f"/marketing/reminders/{reminder.id}/retry?store_id={store.id}")
    assert second.status_code == 409, "the second click has nothing eligible left to retry"

    db.expire_all()
    assert db.get(Reminder, reminder.id).status == "queued"


# -- the Twilio adapter -------------------------------------------------------
def test_twilio_surfaces_the_providers_error_code_and_message(outbox, monkeypatch) -> None:
    db, store, context = outbox
    monkeypatch.setattr(settings, "twilio_account_sid", "ACtest")
    monkeypatch.setattr(settings, "twilio_auth_token", "test-token")
    monkeypatch.setattr(settings, "twilio_whatsapp_from", "+15005550006")

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            400,
            request=httpx.Request("POST", "https://api.twilio.com"),
            json={"code": 21211, "message": "The 'To' number is not a valid phone number"},
        ),
    )

    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    result = twilio_wa.TwilioWhatsAppAdapter().send(reminder, db)

    assert result.status == "failed"
    assert "21211" in result.detail
    assert "not a valid phone number" in result.detail


# -- the WhatsApp Cloud adapter ----------------------------------------------
def test_phone_numbers_are_normalised_to_e164() -> None:
    assert whatsapp_cloud.to_e164("9876543210") == "919876543210"
    assert whatsapp_cloud.to_e164("+91 98765 43210") == "919876543210"


def test_the_cloud_adapter_refuses_without_credentials(outbox, monkeypatch) -> None:
    db, store, context = outbox
    monkeypatch.setattr(settings, "whatsapp_token", None)
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    result = whatsapp_cloud.WhatsAppCloudAdapter().send(reminder, db)
    assert result.status == "failed"
    assert "WHATSAPP_TOKEN" in result.detail


def test_the_cloud_adapter_reports_the_providers_error_verbatim(outbox, monkeypatch) -> None:
    db, store, context = outbox
    monkeypatch.setattr(settings, "whatsapp_token", "test-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1234567890")

    def rejected(*args, **kwargs):
        return httpx.Response(
            400,
            request=httpx.Request("POST", "https://graph.facebook.com"),
            text='{"error":{"code":131047,"message":"Re-engagement message"}}',
        )

    monkeypatch.setattr(httpx, "post", rejected)
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    result = whatsapp_cloud.WhatsAppCloudAdapter().send(reminder, db)

    assert result.status == "failed"
    assert "131047" in result.detail


def test_the_cloud_adapter_reports_success(outbox, monkeypatch) -> None:
    db, store, context = outbox
    monkeypatch.setattr(settings, "whatsapp_token", "test-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1234567890")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200,
            request=httpx.Request("POST", "https://graph.facebook.com"),
            json={"messages": [{"id": "wamid.TEST"}]},
        ),
    )

    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    result = whatsapp_cloud.WhatsAppCloudAdapter().send(reminder, db)
    assert result.status == "sent"
    assert "wamid.TEST" in result.detail


def test_adapter_selection_follows_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "delivery_adapter", "whatsapp_cloud")
    assert get_adapter().name == "whatsapp_cloud"
    monkeypatch.setattr(settings, "delivery_adapter", "twilio_wa")
    assert get_adapter().name == "twilio_wa"
    monkeypatch.setattr(settings, "delivery_adapter", "console")
    assert get_adapter().name == "console"


def test_every_adapter_returns_a_result_rather_than_raising(outbox, monkeypatch) -> None:
    db, store, context = outbox
    reminder = db.scalar(select(Reminder).where(Reminder.store_id == store.id))
    for name in ("console", "twilio_wa", "whatsapp_cloud"):
        monkeypatch.setattr(settings, "delivery_adapter", name)
        result = get_adapter().send(reminder, db)
        assert isinstance(result, DeliveryResult)
        assert result.status in {"sent", "failed"}
