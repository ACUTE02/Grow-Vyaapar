"""Test fixtures: an isolated SQLite database, wired into the FastAPI app."""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Set before app.settings is imported anywhere.
os.environ["DATABASE_URL"] = "sqlite:///./test_localai.db"
os.environ["DELIVERY_ADAPTER"] = "console"
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models import Base  # noqa: E402
from app.verticals.loader import load_verticals  # noqa: E402


@pytest.fixture()
def engine(tmp_path: Path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def db(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = factory()
    load_verticals(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine, db):
    """A TestClient whose get_db dependency points at the temp database."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def rules(db):
    """Reminder rules and fallback templates, seeded the same way the demo seeds them."""
    from scripts.seed import seed_rules_and_templates

    seed_rules_and_templates(db)
    db.commit()
    return db
