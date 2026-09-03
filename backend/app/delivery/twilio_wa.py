"""WhatsApp delivery through the Twilio sandbox. Flag-gated by DELIVERY_ADAPTER.

Only used for the one real demo message. Without credentials it refuses rather
than pretending to have sent anything.
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

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioWhatsAppAdapter(Adapter):
    name = "twilio_wa"

    def send(self, reminder: Reminder) -> DeliveryResult:
        if not (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_whatsapp_from
        ):
            logger.error("Twilio adapter selected but credentials are missing")
            return DeliveryResult("failed", "Twilio credentials are not configured")

        with SessionLocal() as db:
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
            response.raise_for_status()
        except Exception as exc:
            logger.error("Twilio send failed for reminder %s: %s", reminder.id, exc)
            return DeliveryResult("failed", str(exc)[:500])
        return DeliveryResult("sent", f"twilio sid {response.json().get('sid', '')}")
