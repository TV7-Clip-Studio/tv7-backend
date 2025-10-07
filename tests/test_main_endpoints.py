from __future__ import annotations

from http import HTTPStatus
from importlib import metadata as importlib_metadata

import pytest
from httpx import AsyncClient
from pytest import MonkeyPatch

from app.core.config import settings

pytestmark = pytest.mark.asyncio


async def test_readyz(async_client: AsyncClient) -> None:
    response = await async_client.get("/readyz")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ready"}


async def test_version_package_missing(async_client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    def _raise(_: str) -> str:
        raise importlib_metadata.PackageNotFoundError

    monkeypatch.setattr(importlib_metadata, "version", _raise)

    response = await async_client.get("/version")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"version": settings.VERSION}


async def test_version_package_present(async_client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(importlib_metadata, "version", lambda _: "1.2.3")

    response = await async_client.get("/version")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"version": "1.2.3"}


async def test_security_headers_present(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"
