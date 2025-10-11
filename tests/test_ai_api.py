from __future__ import annotations

from collections import defaultdict
from http import HTTPStatus

import pytest
from httpx import AsyncClient

from app.deps import rate_limit

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _beta_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BETA_API_KEY", "test-beta-key")
    monkeypatch.setattr(rate_limit, "_buckets", defaultdict(list))


async def test_execute_requires_api_key(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/ai/execute",
        json={"input": "hola"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"]["message"] == "Invalid API key"


async def test_execute_success(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/ai/execute",
        headers={"X-API-Key": "test-beta-key"},
        json={"input": "hola", "agent_id": "default"},
    )
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["output"] == "ECHO: hola"
    assert payload["meta"]["agent_id"] == "default"


async def test_execute_rate_limit(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS", 1)

    ok = await async_client.post(
        "/api/v1/ai/execute",
        headers={"X-API-Key": "test-beta-key"},
        json={"input": "hola"},
    )
    assert ok.status_code == HTTPStatus.OK

    throttled = await async_client.post(
        "/api/v1/ai/execute",
        headers={"X-API-Key": "test-beta-key"},
        json={"input": "hola"},
    )
    assert throttled.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert throttled.json()["error"]["message"] == "Rate limit"
