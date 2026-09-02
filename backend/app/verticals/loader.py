"""Read app/verticals/definitions/*.json into the verticals table.

This is the only module that knows the definition files exist. It is idempotent:
running it again updates existing rows in place, so the seed can be re-run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.config import Vertical

DEFINITIONS_DIR = Path(__file__).parent / "definitions"

REQUIRED_KEYS = (
    "code",
    "name",
    "unit_labels",
    "default_config",
    "feature_flags",
    "product_schema",
    "prompt_profile",
)


def read_definitions(directory: Path | None = None) -> list[dict[str, Any]]:
    """Parse every definition file, sorted by code for deterministic ordering."""
    directory = directory or DEFINITIONS_DIR
    definitions: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in REQUIRED_KEYS if key not in payload]
        if missing:
            raise ValueError(f"{path.name} is missing keys: {', '.join(missing)}")
        definitions.append(payload)
    if not definitions:
        raise ValueError(f"No vertical definitions found in {directory}")
    return definitions


def load_verticals(db: Session, directory: Path | None = None) -> list[Vertical]:
    """Upsert every definition file into the verticals table."""
    loaded: list[Vertical] = []
    for payload in read_definitions(directory):
        vertical = db.scalar(select(Vertical).where(Vertical.code == payload["code"]))
        if vertical is None:
            vertical = Vertical(code=payload["code"])
            db.add(vertical)
        vertical.name = payload["name"]
        vertical.unit_labels = payload["unit_labels"]
        vertical.default_config = payload["default_config"]
        vertical.feature_flags = payload["feature_flags"]
        vertical.product_schema = payload["product_schema"]
        vertical.prompt_profile = payload["prompt_profile"]
        loaded.append(vertical)
    db.flush()
    return loaded


def known_codes(directory: Path | None = None) -> list[str]:
    """Codes of every shipped vertical. Used by the isolation test and the seed."""
    return [payload["code"] for payload in read_definitions(directory)]
