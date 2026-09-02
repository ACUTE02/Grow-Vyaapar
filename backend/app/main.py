"""FastAPI application: router registration, CORS and error translation."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.middleware import AuditMiddleware, AuthorizationMiddleware
from app.observability import RequestIdMiddleware, configure_logging
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.settings import settings
from app.verticals.context import StoreNotFound

configure_logging(json_logs=settings.json_logs, level=getattr(logging, settings.log_level, logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Billing, inventory and customers for small Indian retail stores, with an "
        "autonomous marketing agent on top. Vertical behaviour is configuration, not code."
    ),
)

# Order matters. The last one added is the outermost, so a request id exists
# before anything else runs, and the audit middleware wraps authorisation so it
# only ever records requests that were actually allowed through.
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthorizationMiddleware)

app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StoreNotFound)
async def _store_not_found_handler(_: Request, exc: StoreNotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(NotFoundError)
async def _not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def _conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def _validation_handler(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc), "errors": exc.errors},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """The last line: log the detail, tell the caller almost nothing.

    A stack trace in a response body is a gift to an attacker and useless to a
    shopkeeper. The request id ties the message to the log entry that has it all.
    """
    from app.observability import request_id

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": (
                "Something went wrong on our side. Nothing was changed. Quote request "
                f"id {request_id.get()} if you report this."
            ),
            "request_id": request_id.get(),
        },
    )


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


def _register_routers() -> None:
    from app.routers import (  # noqa: PLC0415  (imported late so models load first)
        analytics,
        auth,
        billing,
        config,
        customers,
        jobs,
        loyalty,
        marketing,
        purchasing,
        ml,
        products,
    )

    app.include_router(auth.router)
    app.include_router(config.router)
    app.include_router(customers.router)
    app.include_router(products.router)
    app.include_router(billing.router)
    app.include_router(jobs.router)
    app.include_router(loyalty.router)
    app.include_router(purchasing.router)
    app.include_router(analytics.router)
    app.include_router(marketing.router)
    app.include_router(ml.router)


_register_routers()
