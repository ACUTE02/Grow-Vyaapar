"""WhatsApp delivery through the Twilio sandbox. Flag-gated by DELIVERY_ADAPTER.

Only used for the one real demo message. Without credentials it refuses rather
than pretending to have sent anything.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.delivery.base import Adapter
from app.models.agent import Reminder
from app.models.core import Customer
from app.settings import settings

logger = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioWhatsAppAdapter(Adapter):
    name = "twilio_wa"

    def send(self, reminder: Reminder) -> str:
        if not (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_whatsapp_from
        ):
            logger.error("Twilio adapter selected but credentials are missing")
            return "failed"

        with SessionLocal() as db:
            customer = db.scalar(select(Customer).where(Customer.id == reminder.customer_id))
            phone = customer.phone if customer else None

        if not phone:
            logger.error("Reminder %s has no reachable phone number", reminder.id)
            return "failed"

        to_number = phone if phone.startswith("+") else f"+91{phone[-10:]}"
        try:
            response = httpx.post(
                TWILIO_URL.format(sid=settings.twilio_account_sid),
                data={
                    "From": f"whatsapp:{settings.twilio_whatsapp_from}",
                    "To": f"whatsapp:{to_number}",
                    "Body": reminder.message,
                },
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=15.0,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("Twilio send failed for reminder %s: %s", reminder.id, exc)
            return "failed"
        return "sent"
