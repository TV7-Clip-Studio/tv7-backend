from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize(
    ("endpoint", "expected_body"),
    [
        ("/health", {"status": "ok"}),
        ("/readyz", {"status": "ready"}),
    ],
)
async def test_health_and_readyz(
    async_client: AsyncClient, endpoint: str, expected_body: dict[str, str]
) -> None:
    response = await async_client.get(endpoint)
    assert response.status_code == HTTPStatus.OK
    assert response.json() == expected_body


async def test_metrics(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")
    assert response.status_code == HTTPStatus.OK
    body = response.text
    assert "http_request_duration_seconds" in body
