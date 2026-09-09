"""WhatsApp delivery through the Twilio sandbox. Flag-gated by DELIVERY_ADAPTER.

Only used for the one real demo message. Without credentials it refuses rather
than pretending to have sent anything.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from app.delivery.base import Adapter, DeliveryResult
from app.models.agent import Reminder
from app.models.config import Store
from app.models.core import Customer
from app.settings import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

# What TWILIO_CONTENT_VARIABLES may map a template placeholder to. Deliberately
# short: every entry is something the reminder already knows, so a template can
# be filled without inventing data to fill it with.
TEMPLATE_FIELDS = (
    "customer_name",
    "store_name",
    "store_city",
    "store_address",
    "review_url",
    "message",
)


def _template_values(reminder: Reminder, customer: Customer | None, store: Store | None) -> dict:
    """The value behind each name in TEMPLATE_FIELDS, for this one reminder."""
    return {
        "customer_name": (customer.name if customer else "") or "",
        "store_name": (store.name if store else "") or "",
        "store_city": (store.city if store else "") or "",
        "store_address": (getattr(store, "address", None) or "") if store else "",
        "review_url": (store.google_review_url if store else "") or "",
        "message": reminder.message or "",
    }


def content_variables(reminder: Reminder, customer: Customer | None, store: Store | None) -> str | None:
    """Twilio's ContentVariables for the configured template, as a JSON string.

    Meta numbers a template's placeholders ({{1}}, {{2}}) and says nothing
    about what they mean, so the mapping is configuration - the person who had
    the template approved is the only one who knows. Unset, or unparseable,
    means send none: a template with no placeholders needs none, and a bad
    mapping must not stop the message going out with an obscure Twilio error.
    """
    raw = settings.twilio_content_variables
    if not raw or not raw.strip():
        return None
    try:
        mapping = json.loads(raw)
    except ValueError:
        logger.error(
            "TWILIO_CONTENT_VARIABLES is not valid JSON; sending the template with no variables"
        )
        return None
    if not isinstance(mapping, dict) or not mapping:
        return None

    values = _template_values(reminder, customer, store)
    unknown = sorted(str(field) for field in mapping.values() if field not in values)
    if unknown:
        logger.error(
            "TWILIO_CONTENT_VARIABLES names unknown field(s) %s; known fields are %s",
            ", ".join(unknown),
            ", ".join(TEMPLATE_FIELDS),
        )
    return json.dumps(
        {str(key): values.get(str(field), "") for key, field in mapping.items()}
    )


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

        store = db.get(Store, reminder.store_id)

        data = {"From": f"whatsapp:{from_number}", "To": f"whatsapp:{to_number}"}
        if settings.twilio_content_sid:
            # No active 24-hour session can be assumed for a reminder the
            # customer didn't initiate, so a free-form Body would be rejected
            # (error 21654: "ContentSid Required"). A Content Template is
            # accepted at any time, session or not - but its approved text is
            # fixed by Twilio/Meta, so this path does not carry
            # reminder.message; that is a WhatsApp platform rule, not a
            # choice made here.
            data["ContentSid"] = settings.twilio_content_sid
            variables = content_variables(reminder, customer, store)
            if variables:
                data["ContentVariables"] = variables
        else:
            data["Body"] = reminder.message

        try:
            response = httpx.post(
                TWILIO_URL.format(sid=settings.twilio_account_sid),
                data=data,
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

        sid = response.json().get("sid", "")
        if settings.twilio_content_sid:
            # Say which template went out, because it is not the text the
            # Outbox is showing: WhatsApp fixes a template's wording at
            # approval time, so reminder.message never leaves the building on
            # this path. A shopkeeper reading "Sent" deserves to know that.
            return DeliveryResult(
                "sent",
                f"twilio sid {sid} (approved template {settings.twilio_content_sid}, "
                "not the drafted text)",
            )
        return DeliveryResult("sent", f"twilio sid {sid}")
