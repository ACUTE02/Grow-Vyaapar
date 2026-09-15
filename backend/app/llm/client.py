"""One provider-agnostic call(). Order from settings, Gemini first by default.

Hard rule 5: every LLM call has a non-LLM fallback. This function never raises
into a request - it returns None and the caller uses a template or a cached row.

Free tiers are the constraint this module is built around:
  * a token bucket sleeps instead of getting throttled,
  * identical prompts are answered from llm_cache instead of the network,
  * 429 and quota errors back off, then fall through to the next provider.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

# Worth trying again: a blip, a timeout, a server that fell over. Sending the
# same request a second later is a reasonable thing to do about any of these.
RETRYABLE_STATUS = {408, 409, 425, 500, 502, 503, 504}

# Not worth trying again, and actively harmful. On Gemini's free tier a
# rejected request still counts against the allowance and pushes the window
# out: measured here, one 429 said "retry in 45s", and each further attempt
# moved that to a full 60s. So the usual three attempts do not ride out a
# throttle - they deepen it, turning a 15-second wait into a self-sustaining
# one and burning three slots per call instead of one. Falling back at once is
# both kinder to the quota and faster for the request that is waiting.
THROTTLED_STATUS = {429}

# Gemini's flash models are reasoning models: they spend part of
# maxOutputTokens on an internal "thinking" pass before writing a single word
# of the reply, and the budget covers both. Measured against gemini-3.6-flash
# on this project's own prompts, thinking cost between 380 and 1441 tokens
# while the answer itself never exceeded 135 - so a caller asking for 320 or
# 400 got a reply cut off mid-sentence every single time, which _call_gemini
# correctly discards and which left every caption, insight and image prompt
# silently falling back to a template. The app looked as though its LLM were
# switched on; nothing it wrote had ever come from one.
#
# Callers ask for the length of the *answer* they want. This reserve is what
# the model needs before it starts writing, added on top, so a caller's number
# keeps meaning what it says. It is set well clear of the worst measured
# thinking pass rather than at it, because that cost varies run to run on an
# identical prompt: a reserve sized to the average brings the bug back
# intermittently, which is harder to notice than having it back always.
# Groq's llama has no such pass and needs none.
GEMINI_THINKING_RESERVE = 2048


# --------------------------------------------------------------------------- #
# throttle
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Token bucket over a rolling minute. Sleeps rather than failing."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(int(per_minute), 0)
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, *, sleeper: Callable[[float], None] = time.sleep) -> float:
        """Block until a slot is free. Returns how long it waited, in seconds."""
        if self.per_minute <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            waited = 0.0
            if len(self._calls) >= self.per_minute:
                waited = 60 - (now - self._calls[0]) + 0.01
                if waited > 0:
                    logger.info("Rate limiter sleeping %.1fs to stay inside the free tier", waited)
                    sleeper(waited)
                    now = time.monotonic()
                    while self._calls and now - self._calls[0] >= 60:
                        self._calls.popleft()
            self._calls.append(time.monotonic())
            return waited

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


_limiter = RateLimiter(settings.llm_rate_limit_per_minute)


def limiter() -> RateLimiter:
    """The process-wide limiter. Tests swap its rate."""
    if _limiter.per_minute != settings.llm_rate_limit_per_minute:
        _limiter.per_minute = max(int(settings.llm_rate_limit_per_minute), 0)
    return _limiter


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def prompt_hash(prompt: str, model_hint: str = "") -> str:
    return hashlib.sha256(f"{model_hint}::{prompt}".encode()).hexdigest()


def _cache_get(digest: str, db: Any = None) -> str | None:
    """Callers that already hold a session pass it in - a second connection would
    queue behind their open write transaction on SQLite."""
    if settings.llm_cache_hours <= 0:
        return None
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.db import SessionLocal  # noqa: PLC0415
    from app.models.base import utcnow  # noqa: PLC0415
    from app.models.ml import LlmCache  # noqa: PLC0415

    cutoff = utcnow() - timedelta(hours=settings.llm_cache_hours)
    statement = (
        select(LlmCache)
        .where(LlmCache.prompt_hash == digest, LlmCache.created_at >= cutoff)
        .order_by(LlmCache.created_at.desc())
        .limit(1)
    )
    try:
        if db is not None:
            row = db.scalar(statement)
            return row.response if row else None
        with SessionLocal() as own:
            row = own.scalar(statement)
            return row.response if row else None
    except Exception as exc:  # a cache miss must never break a call
        logger.debug("LLM cache read failed: %s", exc)
        return None


def _cache_put(digest: str, response: str, db: Any = None) -> None:
    if settings.llm_cache_hours <= 0:
        return
    from app.db import SessionLocal  # noqa: PLC0415
    from app.models.ml import LlmCache  # noqa: PLC0415

    try:
        if db is not None:
            db.add(LlmCache(prompt_hash=digest, response=response))
            db.flush()          # commits with the caller's transaction
            return
        with SessionLocal() as own:
            own.add(LlmCache(prompt_hash=digest, response=response))
            own.commit()
    except Exception as exc:
        logger.warning("LLM cache write failed, continuing uncached: %s", exc)


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
def _call_groq(
    prompt: str, max_tokens: int, timeout: float, temperature: float = 0.6
) -> str | None:
    if not settings.groq_api_key:
        return None
    payload: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    response = httpx.post(
        settings.groq_base_url,
        json=payload,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"]["content"] or "").strip() or None


def _call_gemini(
    prompt: str, max_tokens: int, timeout: float, temperature: float = 0.6
) -> str | None:
    if not settings.gemini_api_key:
        return None
    # The key travels in a header, never in the query string. Google accepts
    # both, but httpx puts the request URL into every error it raises, and
    # `call()` below logs those errors - so `?key=...` would write the live
    # API key into the application log on any 4xx, 5xx or connection failure.
    # A header keeps it out of the URL and therefore out of the logs.
    url = f"{settings.gemini_base_url}/{settings.gemini_model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens + GEMINI_THINKING_RESERVE,
            "temperature": temperature,
        },
    }
    response = httpx.post(
        url,
        json=payload,
        headers={"x-goog-api-key": settings.gemini_api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    candidate = data["candidates"][0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        # A reasoning model can spend most (or all) of maxOutputTokens on its
        # internal "thinking" pass before writing anything, leaving a reply
        # that is empty or cut off mid-sentence. That is worse than no reply -
        # every caller already has a template fallback for "no text", so treat
        # a MAX_TOKENS truncation as exactly that, never as usable text, even
        # when what came back happens to be short enough to look acceptable.
        logger.warning("Gemini reply truncated by MAX_TOKENS, discarding it as a fallback case")
        return None
    parts = candidate.get("content", {}).get("parts") or []
    return ("".join(part.get("text", "") for part in parts)).strip() or None


PROVIDERS: dict[str, Callable[..., str | None]] = {
    "gemini": _call_gemini,
    "groq": _call_groq,
}

PROVIDER_KEYS: dict[str, Callable[[], str | None]] = {
    "gemini": lambda: settings.gemini_api_key,
    "groq": lambda: settings.groq_api_key,
}


def configured_providers() -> list[str]:
    """Providers in the configured order that actually have a key."""
    return [
        name
        for name in settings.provider_order
        if name in PROVIDERS and PROVIDER_KEYS[name]()
    ]


def available() -> bool:
    """True when at least one provider in the order has a key configured."""
    return bool(configured_providers())


def _is_throttled(exc: Exception) -> bool:
    """A quota or rate-limit refusal, which retrying only makes worse."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in THROTTLED_STATUS
    text = str(exc).lower()
    return "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text


def _is_retryable(exc: Exception) -> bool:
    """A transient failure worth one more attempt - never a throttle."""
    if _is_throttled(exc):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    # A timeout or a dropped connection never reached the model, so it cost
    # nothing and is safe to repeat.
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


# --------------------------------------------------------------------------- #
# the call
# --------------------------------------------------------------------------- #
def call(
    prompt: str,
    *,
    max_tokens: int = 400,
    timeout: float | None = None,
    retries: int | None = None,
    use_cache: bool = True,
    db: Any = None,
    temperature: float = 0.6,
) -> str | None:
    """Ask a model for text. Returns None if every provider and retry fails.

    `temperature` is 0.6 for anything factual. Creative work - a campaign that
    should not read like the last one - asks for more, and should also pass
    use_cache=False, since a cached answer is by definition a repeated one.
    """
    timeout = timeout if timeout is not None else settings.llm_timeout_seconds
    retries = retries if retries is not None else settings.llm_max_retries

    providers = configured_providers()
    if not providers:
        return None

    digest = prompt_hash(prompt, providers[0])
    if use_cache:
        cached = _cache_get(digest, db)
        if cached is not None:
            logger.debug("LLM cache hit for %s", digest[:8])
            return cached

    for provider_name in providers:
        provider = PROVIDERS[provider_name]
        for attempt in range(retries + 1):
            limiter().acquire()
            try:
                text = provider(prompt, max_tokens, timeout, temperature)
            except Exception as exc:
                throttled = _is_throttled(exc)
                logger.warning(
                    "LLM %s attempt %s failed (%s): %s",
                    provider_name,
                    attempt + 1,
                    "throttled" if throttled else "error",
                    exc,
                )
                # A throttle is answered by giving up on this provider at once,
                # not by trying harder - see THROTTLED_STATUS above.
                if not throttled and _is_retryable(exc) and attempt < retries:
                    time.sleep(min(2**attempt, 8))     # exponential backoff
                    continue
                break                                   # fall through to next provider
            if text:
                if use_cache:
                    _cache_put(digest, text, db)
                return text
            break

    logger.info("No LLM output available, caller must fall back")
    return None
