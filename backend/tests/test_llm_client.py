"""Provider order, throttle, cache and batching - all with the network stubbed.

A quota error is the expected steady state on a free tier, so it must land as a
template message, never as an exception or a 500.
"""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.agents import reminders as reminder_agent
from app.llm import client as llm
from app.models.agent import Reminder
from app.models.ml import LlmCache


@pytest.fixture(autouse=True)
def _fast_limiter(monkeypatch):
    """Never actually sleep in tests."""
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    llm.limiter().reset()


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(status, request=request, text="quota exceeded")
    return httpx.HTTPStatusError("quota", request=request, response=response)


# -- provider order ----------------------------------------------------------
def test_gemini_is_tried_first_by_default(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    assert llm.configured_providers() == ["gemini", "groq"]


def test_provider_order_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    monkeypatch.setattr(llm.settings, "llm_provider_order", "groq,gemini")
    assert llm.configured_providers() == ["groq", "gemini"]


def test_a_provider_without_a_key_is_skipped(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    assert llm.configured_providers() == ["groq"]
    assert llm.available() is True


# -- 429 handling ------------------------------------------------------------
def test_a_429_falls_through_to_the_next_provider(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    monkeypatch.setattr(llm.settings, "llm_max_retries", 1)

    calls: list[str] = []

    def throttled(*args, **kwargs):
        calls.append("gemini")
        raise _http_error(429)

    def works(*args, **kwargs):
        calls.append("groq")
        return "second provider answered"

    monkeypatch.setitem(llm.PROVIDERS, "gemini", throttled)
    monkeypatch.setitem(llm.PROVIDERS, "groq", works)

    assert llm.call("hello", use_cache=False) == "second provider answered"
    assert calls == ["gemini", "gemini", "groq"], "one retry, then the next provider"


def test_a_429_everywhere_returns_none_not_an_exception(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    monkeypatch.setattr(llm.settings, "llm_max_retries", 1)

    def throttled(*args, **kwargs):
        raise _http_error(429)

    monkeypatch.setitem(llm.PROVIDERS, "gemini", throttled)
    monkeypatch.setitem(llm.PROVIDERS, "groq", throttled)

    assert llm.call("hello", use_cache=False) is None


def test_quota_text_without_a_status_code_is_still_retryable() -> None:
    assert llm._is_rate_limited(RuntimeError("RESOURCE_EXHAUSTED: quota"))
    assert llm._is_rate_limited(_http_error(503))
    assert not llm._is_rate_limited(ValueError("bad json"))


# -- throttle ----------------------------------------------------------------
def test_the_limiter_sleeps_instead_of_failing() -> None:
    limiter = llm.RateLimiter(per_minute=2)
    slept: list[float] = []
    limiter.acquire(sleeper=slept.append)
    limiter.acquire(sleeper=slept.append)
    limiter.acquire(sleeper=slept.append)      # third call in the same minute
    assert len(slept) == 1 and slept[0] > 0


# -- cache -------------------------------------------------------------------
def test_an_identical_prompt_is_answered_from_the_cache(monkeypatch, engine) -> None:
    """The second identical prompt must not touch the network."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", None)

    calls = {"count": 0}

    def once(*args, **kwargs):
        calls["count"] += 1
        return "answered once"

    monkeypatch.setitem(llm.PROVIDERS, "gemini", once)

    assert llm.call("same prompt") == "answered once"
    assert llm.call("same prompt") == "answered once"
    assert calls["count"] == 1, "the second call must be served from llm_cache"

    with factory() as db:
        assert len(db.scalars(select(LlmCache)).all()) == 1


def test_cache_can_be_bypassed(monkeypatch, engine) -> None:
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", None)

    calls = {"count": 0}
    monkeypatch.setitem(
        llm.PROVIDERS, "gemini", lambda *a, **k: (calls.__setitem__("count", calls["count"] + 1), "x")[1]
    )

    llm.call("prompt", use_cache=False)
    llm.call("prompt", use_cache=False)
    assert calls["count"] == 2


# -- batching ----------------------------------------------------------------
def _lapsed_store(db):
    """A store with customers well past the win-back threshold."""
    from tests.test_segmentation import _catalog, _history, _store

    from app.agents import segmentation
    from app.verticals.context import resolve_store_context

    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    _history(db, store, product, count=6, days_ago=140, spend="600")
    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    db.commit()
    return store, context


def test_one_call_drafts_many_messages(rules, monkeypatch) -> None:
    db = rules
    store, context = _lapsed_store(db)

    prompts_seen: list[str] = []

    def batched(prompt, **kwargs):
        prompts_seen.append(prompt)
        ids = [line.split()[2] for line in prompt.splitlines() if line.startswith("- id ")]
        return json.dumps({"messages": {i: f"Model wrote this for {i}" for i in ids}})

    monkeypatch.setattr(reminder_agent.llm, "available", lambda: True)
    monkeypatch.setattr(reminder_agent.llm, "call", batched)

    created = reminder_agent.run(db, context, llm_budget=2)
    db.commit()

    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    assert sum(created.values()) == len(reminders) > 5
    # Six customers, two rules each: two batched calls instead of twelve, because
    # a batch is keyed by customer id and so holds each customer only once.
    assert len(prompts_seen) == 2 < len(reminders)
    assert all(reminder.message.startswith("Model wrote this") for reminder in reminders)


def test_ids_missing_from_the_reply_keep_their_template(rules, monkeypatch) -> None:
    db = rules
    store, context = _lapsed_store(db)

    def partial(prompt, **kwargs):
        ids = [line.split()[2] for line in prompt.splitlines() if line.startswith("- id ")]
        return json.dumps({"messages": {ids[0]: "Model wrote this one"}})

    monkeypatch.setattr(reminder_agent.llm, "available", lambda: True)
    monkeypatch.setattr(reminder_agent.llm, "call", partial)

    reminder_agent.run(db, context, llm_budget=1)
    db.commit()

    messages = [
        reminder.message
        for reminder in db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    ]
    assert sum(1 for message in messages if message == "Model wrote this one") == 1
    assert any(store.name in message for message in messages), "the rest kept their templates"
    assert all("{" not in message for message in messages)


def test_a_quota_error_mid_run_leaves_every_message_usable(rules, monkeypatch) -> None:
    db = rules
    store, context = _lapsed_store(db)

    monkeypatch.setattr(reminder_agent.llm, "available", lambda: True)
    monkeypatch.setattr(reminder_agent.llm, "call", lambda *a, **k: None)   # as if 429 everywhere

    created = reminder_agent.run(db, context, llm_budget=4)
    db.commit()

    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    assert sum(created.values()) == len(reminders) > 0
    for reminder in reminders:
        assert reminder.message and "{" not in reminder.message
        assert store.name in reminder.message
