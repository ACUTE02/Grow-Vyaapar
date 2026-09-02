"""One provider-agnostic call(). Groq primary, Gemini fallback, None on failure.

Hard rule 5: every LLM call has a non-LLM fallback. This function never raises
into a request - it returns None and the caller uses a template or a cached row.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)


def available() -> bool:
    """True when at least one provider key is configured."""
    return bool(settings.groq_api_key or settings.gemini_api_key)


def _call_groq(prompt: str, max_tokens: int, timeout: float) -> str | None:
    if not settings.groq_api_key:
        return None
    payload: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.6,
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


def _call_gemini(prompt: str, max_tokens: int, timeout: float) -> str | None:
    if not settings.gemini_api_key:
        return None
    url = (
        f"{settings.gemini_base_url}/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6},
    }
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return ("".join(part.get("text", "") for part in parts)).strip() or None


def call(
    prompt: str,
    *,
    max_tokens: int = 400,
    timeout: float | None = None,
    retries: int | None = None,
) -> str | None:
    """Ask a model for text. Returns None if every provider and retry fails."""
    timeout = timeout if timeout is not None else settings.llm_timeout_seconds
    retries = retries if retries is not None else settings.llm_max_retries

    for provider_name, provider in (("groq", _call_groq), ("gemini", _call_gemini)):
        for attempt in range(retries + 1):
            try:
                text = provider(prompt, max_tokens, timeout)
            except Exception as exc:  # network, auth, rate limit, malformed body
                logger.warning(
                    "LLM %s attempt %s failed: %s", provider_name, attempt + 1, exc
                )
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                continue
            if text:
                return text
            break  # provider is not configured, move to the next one

    logger.info("No LLM output available, caller must fall back")
    return None
