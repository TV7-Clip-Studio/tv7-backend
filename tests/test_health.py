from http import HTTPStatus

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def test_health() -> None:
    async with LifespanManager(app):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get("/health")
            if response.status_code != HTTPStatus.OK:
                pytest.fail(f"Unexpected status code: {response.status_code}")
            payload = response.json()
            if payload.get("status") != "ok":
                pytest.fail(f"Unexpected payload: {payload!r}")
