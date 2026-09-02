"""Request ids, structured logs and pagination metadata.

Every log line carries the request id of the call that produced it, and the same
id goes back in the X-Request-Id header. When a shopkeeper says "it broke at
about four o'clock", that is the difference between grep and guesswork.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

request_id: ContextVar[str] = ContextVar("request_id", default="-")

MAX_LIMIT = 500
DEFAULT_LIMIT = 50


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: greppable by a human, parseable by anything else."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(json_logs: bool = False, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get("X-Request-Id")
        token = request_id.set(incoming or uuid.uuid4().hex[:12])
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id.get()
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"
        logging.getLogger("access").info(
            "%s %s -> %s in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        request_id.reset(token)
        return response


def set_pagination(
    response: Response, *, total: int | None, limit: int, offset: int, returned: int
) -> None:
    """Pagination metadata in headers, so list bodies stay plain arrays.

    An envelope would have been the other option; headers keep every existing
    client and test working while still telling a caller how much more there is.
    """
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    response.headers["X-Returned"] = str(returned)
    if total is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Has-More"] = "true" if offset + returned < total else "false"
    else:
        response.headers["X-Has-More"] = "true" if returned >= limit else "false"
