"""FastAPI application: router registration, CORS and error translation."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.settings import settings
from app.verticals.context import StoreNotFound

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Billing, inventory and customers for small Indian retail stores, with an "
        "autonomous marketing agent on top. Vertical behaviour is configuration, not code."
    ),
)

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


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


def _register_routers() -> None:
    from app.routers import (  # noqa: PLC0415  (imported late so models load first)
        analytics,
        billing,
        config,
        customers,
        marketing,
        products,
    )

    app.include_router(config.router)
    app.include_router(customers.router)
    app.include_router(products.router)
    app.include_router(billing.router)
    app.include_router(analytics.router)
    app.include_router(marketing.router)


_register_routers()
