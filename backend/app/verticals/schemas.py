"""Validate product attributes against the vertical's product_schema."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


class AttributeValidationError(Exception):
    """Raised when a product's attributes do not match the vertical schema."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _looks_like_date(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str):
        return False
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "date":
        return _looks_like_date(value)
    return True


def validate_attributes(
    product_schema: dict[str, Any], attributes: dict[str, Any] | None
) -> dict[str, Any]:
    """Return the cleaned attributes, or raise AttributeValidationError.

    Rejects unknown keys and missing required fields, and checks declared types.
    """
    attributes = dict(attributes or {})
    errors: list[str] = []

    allowed = set(product_schema)
    unknown = sorted(set(attributes) - allowed)
    if unknown:
        expected = ", ".join(sorted(allowed)) or "no attributes"
        errors.append(
            f"unknown attribute(s) {', '.join(unknown)} - this store accepts: {expected}"
        )

    for key, spec in product_schema.items():
        required = bool(spec.get("required", False))
        expected_type = str(spec.get("type", "string"))
        if key not in attributes or attributes[key] in (None, ""):
            if required:
                errors.append(f"attribute '{key}' is required ({expected_type})")
            continue
        if not _type_ok(expected_type, attributes[key]):
            errors.append(
                f"attribute '{key}' must be a {expected_type}, got "
                f"{type(attributes[key]).__name__}"
            )

    if errors:
        raise AttributeValidationError(errors)

    return {key: value for key, value in attributes.items() if value not in (None, "")}
