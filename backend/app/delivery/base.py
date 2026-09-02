"""Delivery adapters. An adapter takes a queued reminder and reports what happened."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.agent import Reminder


@dataclass(frozen=True)
class DeliveryResult:
    """The new reminder status, plus whatever the provider said about it."""

    status: str                 # sent | failed
    detail: str | None = None


class Adapter(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, reminder: Reminder) -> DeliveryResult:
        """Attempt one send. Must never raise: report a failure instead."""


def get_adapter(name: str | None = None) -> Adapter:
    """Resolve the configured adapter, defaulting to the console one."""
    from app.delivery.console import ConsoleAdapter
    from app.settings import settings

    chosen = (name or settings.delivery_adapter or "console").lower()
    if chosen == "twilio_wa":
        from app.delivery.twilio_wa import TwilioWhatsAppAdapter

        return TwilioWhatsAppAdapter()
    if chosen == "whatsapp_cloud":
        from app.delivery.whatsapp_cloud import WhatsAppCloudAdapter

        return WhatsAppCloudAdapter()
    return ConsoleAdapter()
