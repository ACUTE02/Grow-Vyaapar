"""Declarative base and shared column helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import DeclarativeBase

# Money is Numeric(10, 2) everywhere in this codebase. Never a float.
Money = Numeric(10, 2)

# Timestamps are stored in UTC and rendered in Asia/Kolkata by the frontend.
TimeStamp = DateTime(timezone=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass
