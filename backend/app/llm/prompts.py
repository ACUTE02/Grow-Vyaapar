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


def campaign_design_prompt(
    context: StoreContext,
    *,
    occasion: str,
    offer_text: str | None,
    products: list[dict[str, Any]],
    segment_counts: dict[str, int],
    recent: list[dict[str, str]],
    angle: str,
    style: str,
) -> str:
    """One call that designs the whole campaign: headline, caption, tags, picture.

    Asked as a single design task rather than two narrow ones, so the picture
    and the words come from the same idea - and it costs one request, not two.

    Variety is built in, not hoped for. The model is shown this store's recent
    campaigns and told not to echo them, and it is handed a creative angle and a
    photographic style chosen at random for this draft. Without those, the same
    occasion produced the same post every time.
    """
    product_lines = (
        "\n".join(
            f"- {item['name']} ({item['qty_on_hand']} {context.unit_label} in stock"
            f"{'; ' + item['why'] if item.get('why') else ''})"
            for item in products
        )
        or "- no specific product; promote the shop itself"
    )
    if offer_text:
        offer_block = (
            "THE OFFER (typed by the shopkeeper - a real fact, build the post around it):\n"
            f"  {offer_text}\n"
            "Mention this offer in the caption in your own words, keeping its numbers "
            "exactly as written. Feature the products it is about. Do not add any other "
            "offer, price or discount."
        )
    else:
        offer_block = (
            "There is NO offer. Do not mention any discount, price cut, freebie or deal."
        )
    if recent:
        recent_lines = "\n".join(
            f"- caption: \"{item['caption']}\" | picture: \"{item['visual']}\""
            for item in recent
        )
        recent_block = (
            "RECENT POSTS FROM THIS SHOP - yours must feel clearly different. Do not reuse "
            "their opening words, sentence shapes, featured products or picture scene:\n"
            f"{recent_lines}"
        )
    else:
        recent_block = "This is the shop's first campaign."

    return (
        f"{profile_block(context)}\n\n"
        "You are the creative director for this shop's festival campaign. Think about the "
        "occasion, the offer and the customers, then design ONE social media post and the "
        "photograph for its poster.\n\n"
        f"OCCASION: {occasion}\n\n"
        f"{offer_block}\n\n"
        "PRODUCTS YOU MAY FEATURE (pick the 1 to 3 that best fit the offer and occasion):\n"
        f"{product_lines}\n\n"
        f"CUSTOMER MIX: {json.dumps(segment_counts)}\n\n"
        f"CREATIVE ANGLE FOR THIS DRAFT: {angle}\n"
        f"PHOTO STYLE FOR THIS DRAFT: {style}\n\n"
        f"{recent_block}\n\n"
        "Write:\n"
        "- headline: at most 6 words, catchy, no hashtags\n"
        "- caption: 25 to 50 words, in the language and tone above, natural, not a list\n"
        "- hashtags: 5 to 7, relevant to the occasion, the offer, the shop and the city\n"
        "- visual: at most 40 words describing only what the photograph shows - the "
        "featured products, the occasion's own cultural details, setting, light and "
        "colours - in the photo style above. No text, letters, logos or faces in it.\n\n"
        'Reply with JSON only: {"headline": "...", "caption": "...", '
        '"hashtags": ["#..."], "visual": "..."}'
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
