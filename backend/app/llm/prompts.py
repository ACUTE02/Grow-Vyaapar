"""Every prompt template, composed with the store's prompt_profile.

The model is only ever asked to write sentences about numbers it was handed.
It is never asked to calculate anything (hard rule 3).
"""
from __future__ import annotations

import json
from typing import Any

from app.verticals.context import StoreContext


def profile_block(context: StoreContext) -> str:
    profile = context.prompt_profile or {}
    forbidden = profile.get("forbidden") or []
    forbidden_lines = "\n".join(f"- {item}" for item in forbidden) or "- nothing specific"
    signature = str(profile.get("signature", "{store_name}, {city}")).format(
        store_name=context.store_name, city=context.city
    )
    return (
        f"You write for {context.store_name}, a {context.vertical_name.lower()} shop in "
        f"{context.city}, India.\n"
        f"Tone: {profile.get('tone', 'friendly and factual')}.\n"
        f"Language: {profile.get('language', 'simple English')}.\n"
        f"Never write any of the following:\n{forbidden_lines}\n"
        f"Sign off as: {signature}\n"
        "Use only the facts given. Do not invent offers, prices, dates or numbers."
    )


def reminder_prompt(
    context: StoreContext,
    *,
    instruction: str,
    fallback_body: str,
    facts: dict[str, Any],
) -> str:
    fact_lines = "\n".join(f"- {key}: {value}" for key, value in facts.items())
    return (
        f"{profile_block(context)}\n\n"
        f"Task: {instruction}\n"
        "Write ONE WhatsApp message, at most 240 characters, no emoji spam (one emoji at most), "
        "no markdown, no placeholders left unfilled.\n\n"
        f"Facts you may use:\n{fact_lines}\n\n"
        f"A safe version of this message reads: \"{fallback_body}\"\n"
        "Reply with the message text only."
    )


def batch_reminder_prompt(context: StoreContext, items: list[dict[str, Any]]) -> str:
    """One call, many messages. Free tiers are billed per request, not per word.

    Each item carries its own instruction, facts and a safe fallback line, keyed
    by customer id. Any id the model omits keeps its template message.
    """
    blocks = []
    for item in items:
        facts = "; ".join(f"{key}: {value}" for key, value in item["facts"].items())
        blocks.append(
            f'- id {item["customer_id"]} | task: {item["instruction"]} | '
            f'customer: {item["customer_name"]} | facts: {facts} | '
            f'safe version: "{item["fallback"]}"'
        )
    listing = "\n".join(blocks)
    return (
        f"{profile_block(context)}\n\n"
        f"Write one WhatsApp message for EACH of the {len(items)} customers below. "
        "Each message: at most 240 characters, at most one emoji, no markdown, no "
        "unfilled placeholders, and only the facts given for that customer.\n\n"
        f"CUSTOMERS:\n{listing}\n\n"
        'Reply with JSON only, no prose: {"messages": {"<customer id>": "<message>"}}. '
        "Use the ids exactly as given."
    )


def insights_prompt(context: StoreContext, metrics: dict[str, Any]) -> str:
    return (
        f"{profile_block(context)}\n\n"
        "You are the shop owner's analyst. Below are figures already computed from the "
        "database. Do not recompute or estimate anything; quote the figures as given.\n\n"
        f"FIGURES (JSON):\n{json.dumps(metrics, indent=2, default=str)}\n\n"
        "Write EXACTLY three suggestions. Each suggestion must quote at least one figure "
        "from above verbatim and propose one concrete action the owner can do this week.\n"
        "Reply with JSON only, no prose around it, in this shape:\n"
        '{"suggestions": [{"title": "...", "detail": "...", "figure": "...", '
        '"action": "low_stock|dead_stock|customers|outbox|campaigns"}]}'
    )


def campaign_caption_prompt(
    context: StoreContext,
    *,
    occasion: str,
    products: list[dict[str, Any]],
    segment_counts: dict[str, int],
) -> str:
    product_lines = (
        "\n".join(
            f"- {item['name']} (SKU {item['sku']}, {item['qty_on_hand']} "
            f"{context.unit_label} in stock)"
            for item in products
        )
        or "- no specific product, promote the shop itself"
    )
    return (
        f"{profile_block(context)}\n\n"
        f"Occasion: {occasion}\n"
        f"Stock we want to move:\n{product_lines}\n"
        f"Customer mix: {json.dumps(segment_counts)}\n\n"
        "Write one social media post for this shop: a caption of at most 45 words and "
        "5 to 7 hashtags relevant to the shop, the city and the occasion.\n"
        "Reply with JSON only: {\"caption\": \"...\", \"hashtags\": [\"#...\"]}"
    )


def campaign_image_prompt(
    context: StoreContext, *, occasion: str, products: list[dict[str, Any]]
) -> str:
    names = ", ".join(item["name"] for item in products[:3]) or "the shop counter"
    return (
        f"{profile_block(context)}\n\n"
        f"Describe, in at most 30 words, a photograph for a {occasion} poster for this shop "
        f"featuring {names}. Describe only what is visible: subject, setting, lighting, colours. "
        "No text in the image, no logos, no people's faces. Reply with the description only."
    )


def parse_json_block(text: str | None) -> Any | None:
    """Models like to wrap JSON in prose or fences. Recover the first object."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
