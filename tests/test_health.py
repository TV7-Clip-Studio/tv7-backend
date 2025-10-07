from http import HTTPStatus

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def test_health() -> None:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
            if response.status_code != HTTPStatus.OK:
                pytest.fail(f"Unexpected status code: {response.status_code}")  # pragma: no cover
            payload = response.json()
            if payload.get("status") != "ok":
                pytest.fail(f"Unexpected payload: {payload!r}")  # pragma: no cover
