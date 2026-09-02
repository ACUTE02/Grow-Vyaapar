"""Default adapter: log the message and mark it sent. Safe in every environment."""
from __future__ import annotations

import logging

from app.delivery.base import Adapter, DeliveryResult
from app.models.agent import Reminder

logger = logging.getLogger(__name__)


class ConsoleAdapter(Adapter):
    name = "console"

    def send(self, reminder: Reminder) -> DeliveryResult:
        logger.info(
            "[outbox] store=%s customer=%s kind=%s -> %s",
            reminder.store_id,
            reminder.customer_id,
            reminder.kind,
            reminder.message,
        )
        return DeliveryResult("sent", "console adapter: logged, not actually sent")
