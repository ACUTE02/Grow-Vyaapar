"""Test fixtures: an isolated SQLite database, wired into the FastAPI app."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Set before app.settings is imported anywhere.
os.environ["DATABASE_URL"] = "sqlite:///./test_localai.db"
# Trained artefacts are named by store id, and fixture stores reuse the real
# ids, so without this a test run overwrites backend/models/*.joblib - the
# models the running app serves - with ones trained on fixture data. That
# happened: the deployed store-1 stock forecast became a constant predictor.
os.environ["ML_MODEL_DIR"] = tempfile.mkdtemp(prefix="localai-test-models-")
os.environ["DELIVERY_ADAPTER"] = "console"
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
# The developer's own backend/.env holds live WhatsApp credentials, and
# pydantic-settings reads it whatever the test does. Blanked here so a test
# that reaches a real adapter refuses for want of credentials instead of
# messaging somebody's phone. The suite's own Twilio tests set fake values on
# the settings object, which is unaffected by this.
for _credential in (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "TWILIO_CONTENT_SID",
    "WHATSAPP_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
):
    os.environ[_credential] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models import Base  # noqa: E402
from app.verticals.loader import load_verticals  # noqa: E402


@pytest.fixture()
def engine(tmp_path: Path):
    """SQLite by default; set TEST_DATABASE_URL to run the same suite on Postgres.

    Each test gets its own schema on Postgres, so the suite can run in parallel
    against one server without tests treading on each other.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        eng = create_engine(
            f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(eng)
        try:
            yield eng
        finally:
            eng.dispose()
        return

    from sqlalchemy import text

    schema = f"t{uuid.uuid4().hex[:12]}"
    admin = create_engine(url, future=True, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin.dispose()

    eng = create_engine(
        url,
        future=True,
        connect_args={"options": f"-csearch_path={schema}"},
        poolclass=None,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()
        admin = create_engine(url, future=True, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


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


def _make_user(db: Session, *, role: str, email: str, store_id: int | None = None):
    """A signed-in identity for the tests. Auth is on by default, as in production."""
    from app.models.admin import User
    from app.security import hash_password

    user = User(
        name=f"Test {role}",
        email=email,
        password_hash=hash_password("password123"),
        role=role,
        store_id=store_id,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture(autouse=True)
def _no_poster_network(monkeypatch):
    """The campaign agent composites a poster by downloading the generated
    background. Tests must not reach that generator - it is slow, it is a
    third party, and a test that quietly depends on the network is a test that
    fails on a train. Stubbed to the same thing a real failure produces: the
    plain background URL, unchanged.

    tests/test_poster.py exercises the real compositing directly, with its own
    in-memory image.
    """
    from app.agents import campaigns

    monkeypatch.setattr(
        campaigns, "compose_poster", lambda background_url, **kwargs: background_url
    )


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The login limiter is process-wide by design, so it has to be cleared
    between tests - otherwise the suite's own sign-ins trip it and every test
    after the tenth fails with a 429 that has nothing to do with the test."""
    from app.ratelimit import login_limiter

    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.fixture()
def anon_client(engine, db):
    """A client with no token at all."""
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


def _sign_in(test_client, email: str) -> None:
    response = test_client.post(
        "/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


@pytest.fixture()
def client(anon_client, db):
    """The default client: signed in as an owner who can reach every store."""
    _make_user(db, role="owner", email="owner@example.com")
    _sign_in(anon_client, "owner@example.com")
    return anon_client


@pytest.fixture()
def role_client(anon_client, db):
    """Factory: sign the client in as a given role, optionally scoped to a store."""

    def _make(role: str, store_id: int | None = None):
        email = f"{role}-{store_id or 'all'}@example.com"
        _make_user(db, role=role, email=email, store_id=store_id)
        _sign_in(anon_client, email)
        return anon_client

    return _make


@pytest.fixture()
def rules(db):
    """Reminder rules and fallback templates, seeded the same way the demo seeds them."""
    from scripts.seed import seed_rules_and_templates

    seed_rules_and_templates(db)
    db.commit()
    return db


@pytest.fixture(autouse=True)
def _no_outbound_http(monkeypatch):
    """No test may reach a real provider, whatever it forgets to mock.

    Blanking the credentials above stops the adapters getting far enough to
    try. This is the second lock, for the case where a test sets fake
    credentials on the settings object and then forgets to stub the HTTP call:
    the request fails loudly here instead of arriving at Twilio, which is the
    one mistake in this suite that costs money and messages a real person.

    Tests that need a fake response replace httpx.post themselves; their
    monkeypatch is applied after this one and wins for the duration.
    """
    import httpx

    def _refuse(url, *args, **kwargs):
        raise AssertionError(
            f"a test tried to make a real HTTP request to {url}. "
            "Stub the provider call instead - the suite must never reach the network."
        )

    monkeypatch.setattr(httpx, "post", _refuse)
    monkeypatch.setattr(httpx, "get", _refuse)
