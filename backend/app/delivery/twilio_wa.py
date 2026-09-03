"""WhatsApp delivery through the Twilio sandbox. Flag-gated by DELIVERY_ADAPTER.

Only used for the one real demo message. Without credentials it refuses rather
than pretending to have sent anything.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from app.delivery.base import Adapter, DeliveryResult
from app.models.agent import Reminder
from app.models.core import Customer
from app.settings import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioWhatsAppAdapter(Adapter):
    name = "twilio_wa"

    def send(self, reminder: Reminder, db: "Session") -> DeliveryResult:
        if not (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_whatsapp_from
        ):
            logger.error("Twilio adapter selected but credentials are missing")
            return DeliveryResult("failed", "Twilio credentials are not configured")

        customer = db.scalar(select(Customer).where(Customer.id == reminder.customer_id))
        phone = customer.phone if customer else None
        opted_in = bool(customer.marketing_opt_in) if customer else False

        if not phone:
            logger.error("Reminder %s has no reachable phone number", reminder.id)
            return DeliveryResult("failed", "customer has no phone number on record")
        if not opted_in:
            return DeliveryResult("failed", "customer has opted out of marketing messages")

        to_number = phone if phone.startswith("+") else f"+91{phone[-10:]}"
        # TWILIO_WHATSAPP_FROM is documented as a bare E.164 number, but Twilio's
        # own dashboard hands it out pre-fixed with "whatsapp:" - accept either so
        # the two prefixes never stack into "whatsapp:whatsapp:+1...".
        from_number = settings.twilio_whatsapp_from.removeprefix("whatsapp:")
        try:
            response = httpx.post(
                TWILIO_URL.format(sid=settings.twilio_account_sid),
                data={
                    "From": f"whatsapp:{from_number}",
                    "To": f"whatsapp:{to_number}",
                    "Body": reminder.message,
                },
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            logger.error("Twilio send failed for reminder %s: %s", reminder.id, exc)
            return DeliveryResult("failed", f"network error: {exc}"[:500])

        if response.status_code >= 400:
            # Twilio's body carries a numeric error code and a human message
            # (e.g. 21211: "'To' number is not a valid phone number") - that is
            # what actually explains a failed send in the Outbox, not the
            # generic "400 Bad Request" an httpx exception would have said.
            try:
                body = response.json()
                code, message = body.get("code"), body.get("message")
                detail = f"Twilio error {code}: {message}" if code is not None else response.text
            except Exception:
                detail = response.text
            logger.error(
                "Twilio rejected reminder %s: %s %s", reminder.id, response.status_code, detail
            )
            return DeliveryResult("failed", detail[:500])

        return DeliveryResult("sent", f"twilio sid {response.json().get('sid', '')}")
