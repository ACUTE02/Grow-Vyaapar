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
    # Straight to the next provider, with no retry in between: a 429 spends the
    # allowance even when it is refused, so a second attempt would push the
    # first provider's reset further out and delay this request for nothing.
    assert calls == ["gemini", "groq"], "no retry on a throttle, next provider at once"


def test_a_429_everywhere_returns_none_not_an_exception(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", "q-key")
    monkeypatch.setattr(llm.settings, "llm_max_retries", 1)

    def throttled(*args, **kwargs):
        raise _http_error(429)

    monkeypatch.setitem(llm.PROVIDERS, "gemini", throttled)
    monkeypatch.setitem(llm.PROVIDERS, "groq", throttled)

    assert llm.call("hello", use_cache=False) is None


def test_quota_text_without_a_status_code_is_recognised_as_a_throttle() -> None:
    """Not every provider says 429 in a status code; some only say it in prose."""
    assert llm._is_throttled(RuntimeError("RESOURCE_EXHAUSTED: quota"))
    assert llm._is_throttled(_http_error(429))
    assert not llm._is_throttled(_http_error(503))
    assert not llm._is_throttled(ValueError("bad json"))


def test_a_throttle_is_never_retried_but_a_server_error_is() -> None:
    """Retrying a 429 deepens the throttle; retrying a 503 is just a retry.

    On Gemini's free tier a rejected request still spends the allowance and
    pushes the reset out, so three attempts turn a 15-second wait into a
    self-sustaining one. Transient failures cost nothing and stay retryable.
    """
    assert not llm._is_retryable(_http_error(429))
    assert not llm._is_retryable(RuntimeError("rate limit exceeded"))
    assert llm._is_retryable(_http_error(503))
    assert llm._is_retryable(httpx.ConnectTimeout("timed out"))
    assert not llm._is_retryable(ValueError("bad json"))


def test_a_throttled_provider_is_called_exactly_once(monkeypatch) -> None:
    """The whole point: one attempt per provider, not one plus two retries."""
    calls: list[str] = []

    def throttled(*args, **kwargs):
        calls.append("gemini")
        raise _http_error(429)

    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", None)
    monkeypatch.setitem(llm.PROVIDERS, "gemini", throttled)

    assert llm.call("hello", use_cache=False, retries=2) is None
    assert calls == ["gemini"]


def test_a_server_error_still_gets_its_retries(monkeypatch) -> None:
    """The retry path has to survive the change, or this is just a regression."""
    calls: list[int] = []

    def flaky(*args, **kwargs):
        calls.append(1)
        raise _http_error(503)

    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.settings, "groq_api_key", None)
    monkeypatch.setitem(llm.PROVIDERS, "gemini", flaky)

    assert llm.call("hello", use_cache=False, retries=2) is None
    assert len(calls) == 3


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


# -- the key must not reach a log ---------------------------------------------
def test_the_gemini_key_travels_in_a_header_not_the_url(monkeypatch) -> None:
    """A query-string key ends up in httpx's error text, and `call()` logs that.

    Google accepts the key either way, so this is free to get right; getting it
    wrong writes a live credential into the application log the first time
    Gemini answers with a 429, which on a free tier is routine.
    """
    seen: dict[str, object] = {}

    def _capture(url, *, json, headers=None, timeout=None):  # noqa: A002
        seen["url"] = url
        seen["headers"] = headers or {}
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    monkeypatch.setattr(llm.settings, "gemini_api_key", "SECRET-KEY-VALUE")
    monkeypatch.setattr(llm.httpx, "post", _capture)

    assert llm._call_gemini("hello", 100, 5.0) == "ok"
    assert "SECRET-KEY-VALUE" not in str(seen["url"])
    assert seen["headers"]["x-goog-api-key"] == "SECRET-KEY-VALUE"


def test_a_failing_gemini_call_does_not_log_the_key(monkeypatch, caplog) -> None:
    """The end-to-end version of the rule above: force a 429 and read the log."""

    def _refuse(url, *, json, headers=None, timeout=None):  # noqa: A002
        request = httpx.Request("POST", url)
        response = httpx.Response(429, request=request, text="quota exceeded")
        response.raise_for_status()

    monkeypatch.setattr(llm.settings, "gemini_api_key", "SECRET-KEY-VALUE")
    monkeypatch.setattr(llm.settings, "groq_api_key", None)
    monkeypatch.setattr(llm.httpx, "post", _refuse)

    with caplog.at_level("DEBUG"):
        assert llm.call("hello", use_cache=False) is None

    assert "SECRET-KEY-VALUE" not in caplog.text


def test_gemini_gets_a_thinking_budget_on_top_of_the_asked_for_length(monkeypatch) -> None:
    """A caller asking for 400 tokens of answer must not be cut off by thinking.

    gemini-3.6-flash spends 380-1441 tokens reasoning before it writes anything,
    and maxOutputTokens covers both passes. Sending the caller's number
    unchanged meant every reply came back finishReason=MAX_TOKENS and was
    discarded - the app ran entirely on template fallbacks while looking, from
    the outside, as though the LLM were switched on.
    """
    sent: dict[str, object] = {}

    def _capture(url, *, json, headers=None, timeout=None):  # noqa: A002
        sent["config"] = json["generationConfig"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    monkeypatch.setattr(llm.settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(llm.httpx, "post", _capture)

    llm._call_gemini("hello", 400, 5.0)
    budget = sent["config"]["maxOutputTokens"]
    assert budget == 400 + llm.GEMINI_THINKING_RESERVE
    # The reserve has to clear the worst thinking pass measured on this
    # project's own prompts, or the bug comes back for the longest of them.
    assert llm.GEMINI_THINKING_RESERVE >= 1600
