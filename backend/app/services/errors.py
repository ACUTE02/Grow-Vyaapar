"""Domain exceptions. Services raise these; routers translate them to HTTP codes."""
from __future__ import annotations


class DomainError(Exception):
    """Base class. The message is shown to the user, so it must be actionable."""


class NotFoundError(DomainError):
    """A referenced row does not exist."""


class ConflictError(DomainError):
    """The request contradicts current state, e.g. an oversell."""


class ValidationError(DomainError):
    """The request is well-formed but not acceptable, e.g. bad attributes."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]
