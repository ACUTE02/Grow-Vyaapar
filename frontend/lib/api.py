"""Thin HTTP client for the FastAPI backend.

Every call returns (ok, payload). A failed call never raises into a page - the
page renders its error state instead.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 30.0


def auth_headers() -> dict[str, str]:
    """The signed-in user's token, if there is one."""
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(method: str, path: str, **kwargs: Any) -> tuple[bool, Any]:
    url = f"{BASE_URL}{path}"
    headers = {**auth_headers(), **(kwargs.pop("headers", None) or {})}
    try:
        response = httpx.request(method, url, timeout=TIMEOUT, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        return False, f"Cannot reach the API at {BASE_URL}. Is uvicorn running? ({exc})"

    if response.status_code >= 400:
        try:
            body = response.json()
            detail = body.get("detail", response.text)
            errors = body.get("errors")
            if errors:
                detail = f"{detail}\n\n- " + "\n- ".join(errors)
        except Exception:
            detail = response.text
        return False, detail

    if response.headers.get("content-type", "").startswith("application/json"):
        return True, response.json()
    return True, response.content


def get(path: str, params: dict | None = None) -> tuple[bool, Any]:
    return _request("GET", path, params=params or {})


def post(path: str, params: dict | None = None, json: dict | None = None) -> tuple[bool, Any]:
    return _request("POST", path, params=params or {}, json=json)


def patch(path: str, params: dict | None = None, json: dict | None = None) -> tuple[bool, Any]:
    return _request("PATCH", path, params=params or {}, json=json)


def put(path: str, params: dict | None = None, json: dict | None = None) -> tuple[bool, Any]:
    return _request("PUT", path, params=params or {}, json=json)


def login(email: str, password: str) -> tuple[bool, Any]:
    """Exchange credentials for a token. The password is never stored anywhere."""
    return post("/auth/login", json={"email": email, "password": password})


@st.cache_data(ttl=30, show_spinner=False)
def stores(_token: str | None = None) -> tuple[bool, Any]:
    return get("/config/stores")


@st.cache_data(ttl=15, show_spinner=False)
def store_context(store_id: int, _token: str | None = None) -> tuple[bool, Any]:
    return get(f"/config/stores/{store_id}/context")


def invalidate() -> None:
    """Called whenever the selected store changes or data is written."""
    stores.clear()
    store_context.clear()
