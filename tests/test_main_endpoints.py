from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from importlib import metadata as importlib_metadata

import pytest
from httpx import AsyncClient
from pytest import MonkeyPatch

from app.core.config import settings

pytestmark = pytest.mark.asyncio


def _raise_package_not_found(_: str) -> str:
    raise importlib_metadata.PackageNotFoundError


async def test_readyz(async_client: AsyncClient) -> None:
    response = await async_client.get("/readyz")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize(
    ("stub", "expected"),
    [
        pytest.param(
            _raise_package_not_found,
            {"version": settings.VERSION},
            id="package-missing",
        ),
        pytest.param(
            lambda _: "1.2.3",
            {"version": "1.2.3"},
            id="package-present",
        ),
    ],
)
async def test_version_endpoint(
    async_client: AsyncClient,
    monkeypatch: MonkeyPatch,
    stub: Callable[[str], str],
    expected: dict[str, str],
) -> None:
    monkeypatch.setattr(importlib_metadata, "version", stub)

    response = await async_client.get("/version")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == expected


async def test_security_headers_present(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"
