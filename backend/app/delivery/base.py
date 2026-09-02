"""Delivery adapters. An adapter takes a queued reminder and reports a status."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.agent import Reminder


class Adapter(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, reminder: Reminder) -> str:
        """Return the new reminder status: sent or failed."""


def get_adapter(name: str | None = None) -> Adapter:
    """Resolve the configured adapter, defaulting to the console one."""
    from app.settings import settings
    from app.delivery.console import ConsoleAdapter

    chosen = (name or settings.delivery_adapter or "console").lower()
    if chosen == "twilio_wa":
        from app.delivery.twilio_wa import TwilioWhatsAppAdapter

        return TwilioWhatsAppAdapter()
    return ConsoleAdapter()
