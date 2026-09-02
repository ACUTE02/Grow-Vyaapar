"""Meta WhatsApp Cloud API adapter. Selected with DELIVERY_ADAPTER=whatsapp_cloud.

Two things worth knowing before switching this on:

* Meta only allows free-form text inside a 24-hour customer service window.
  Outside it a pre-approved template is required, and the send will come back
  with a 131047 error. That error text is stored on the reminder rather than
  swallowed, so the outbox shows exactly why a message did not go.
* Nothing here runs on a schedule. Sending is always an explicit action on an
  explicitly chosen set of reminders (rule 10).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.delivery.base import Adapter, DeliveryResult
from app.models.agent import Reminder
from app.models.core import Customer
from app.settings import settings

logger = logging.getLogger(__name__)


def to_e164(phone: str, default_country: str = "91") -> str:
    """Indian mobiles are stored as ten digits; the API wants full international."""
    digits = "".join(character for character in phone if character.isdigit())
    if phone.strip().startswith("+"):
        return digits
    if len(digits) == 10:
        return f"{default_country}{digits}"
    return digits


class WhatsAppCloudAdapter(Adapter):
    name = "whatsapp_cloud"

    def send(self, reminder: Reminder) -> DeliveryResult:
        if not (settings.whatsapp_token and settings.whatsapp_phone_number_id):
            return DeliveryResult(
                "failed",
                "WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID are not configured",
            )

        with SessionLocal() as db:
            customer = db.scalar(select(Customer).where(Customer.id == reminder.customer_id))
            phone = customer.phone if customer else None
            opted_in = bool(customer.marketing_opt_in) if customer else False

        if not phone:
            return DeliveryResult("failed", "customer has no phone number on record")
        if not opted_in:
            return DeliveryResult("failed", "customer has opted out of marketing messages")

        url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}"
            f"/{settings.whatsapp_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_e164(phone),
            "type": "text",
            "text": {"preview_url": False, "body": reminder.message},
        }
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            logger.error("WhatsApp Cloud send failed for reminder %s: %s", reminder.id, exc)
            return DeliveryResult("failed", f"network error: {exc}")

        if response.status_code >= 400:
            detail = response.text[:500]
            logger.error(
                "WhatsApp Cloud rejected reminder %s: %s %s",
                reminder.id,
                response.status_code,
                detail,
            )
            return DeliveryResult("failed", f"{response.status_code}: {detail}")

        body = response.json()
        message_id = (body.get("messages") or [{}])[0].get("id", "")
        return DeliveryResult("sent", f"accepted, message id {message_id}")
