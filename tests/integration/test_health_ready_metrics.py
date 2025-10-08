from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_health(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


async def test_readyz(async_client: AsyncClient) -> None:
    response = await async_client.get("/readyz")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ready"}


async def test_metrics(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")
    assert response.status_code == HTTPStatus.OK
    body = response.text
    assert "http_request_duration_seconds" in body
