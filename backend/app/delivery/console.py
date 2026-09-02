"""Default adapter: log the message and mark it sent. Safe in every environment."""
from __future__ import annotations

import logging

from app.delivery.base import Adapter
from app.models.agent import Reminder

logger = logging.getLogger(__name__)


class ConsoleAdapter(Adapter):
    name = "console"

    def send(self, reminder: Reminder) -> str:
        logger.info(
            "[outbox] store=%s customer=%s kind=%s -> %s",
            reminder.store_id,
            reminder.customer_id,
            reminder.kind,
            reminder.message,
        )
        return "sent"
