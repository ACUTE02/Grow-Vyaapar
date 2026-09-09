"""Request-level authorisation and the audit trail.

Roles are enforced here, in front of every route, rather than route by route.
A hidden button is a courtesy to the user; this is the control. A hand-crafted
request from a cashier's token is refused exactly like a click would be.

Every mutating request that succeeds leaves an audit row. Services add the
before/after detail for the entities where it matters (a price change, a user
edit); this guarantees the trail exists even for the ones that do not.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.security import ROLE_LEVEL, decode_token, token_from_request
from app.settings import settings

logger = logging.getLogger(__name__)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

PUBLIC_PATHS = (
    "/health",
    # Composed campaign posters. An <img> tag carries no Authorization header,
    # so anything served here has to be reachable without one - the filename is
    # a hash rather than a guessable id, and a poster is a picture the
    # shopkeeper is about to share anyway.
    "/static/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/login",
    "/favicon.ico",
)

# Minimum role per path prefix for mutating requests. Anything not listed needs
# a signed-in user of any role.
WRITE_RULES: tuple[tuple[str, str], ...] = (
    ("/auth/users", "owner"),
    ("/config", "manager"),
    ("/products", "manager"),
    ("/suppliers", "manager"),
    ("/purchasing", "manager"),
    ("/loyalty/coupons", "manager"),
    ("/ml/", "manager"),
    ("/marketing/reminders/send", "manager"),
    ("/marketing/campaigns", "manager"),
)


def required_role(method: str, path: str) -> str | None:
    """The minimum role for this request, or None when anyone signed in may do it."""
    if method not in MUTATING:
        return None
    for prefix, role in WRITE_RULES:
        if path.startswith(prefix):
            return role
    return "cashier"


def _deny(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


class AuthorizationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        if not settings.auth_enabled or path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        claims = None
        token = token_from_request(request)
        if token:
            claims = decode_token(token)

        if claims is None:
            return _deny(
                401,
                "Sign in first. POST /auth/login and send the token as "
                "'Authorization: Bearer <token>'.",
            )

        role = claims.get("role", "cashier")
        needed = required_role(request.method, path)
        if needed and ROLE_LEVEL.get(role, 0) < ROLE_LEVEL[needed]:
            return _deny(
                403,
                f"This needs the {needed} role. You are signed in as {role}.",
            )

        # A user tied to one store cannot reach another store's data, whatever
        # the query string says. This is the early refusal; the same rule is
        # enforced again in the store-context dependency, which is the one that
        # also sees a store named in the path - middleware runs before routing,
        # so path parameters do not exist yet here.
        user_store = claims.get("store_id")
        asked_for = request.query_params.get("store_id")
        if user_store is not None and asked_for and str(user_store) != str(asked_for):
            return _deny(
                403,
                f"Your account belongs to store {user_store}, not store {asked_for}.",
            )

        from app import audit  # noqa: PLC0415

        audit.set_actor(int(claims["sub"]))
        request.state.user_id = int(claims["sub"])
        request.state.user_role = role
        request.state.user_store_id = user_store
        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """One row per successful mutating request."""

    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)

        if request.method not in MUTATING or response.status_code >= 400:
            return response
        if request.url.path.startswith(PUBLIC_PATHS):
            return response

        try:
            from app.audit import record_request  # noqa: PLC0415

            record_request(
                user_id=getattr(request.state, "user_id", None),
                store_id=request.query_params.get("store_id"),
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
        except Exception as exc:      # auditing must never break the request
            logger.warning("Audit write failed for %s %s: %s", request.method, request.url.path, exc)

        return response
