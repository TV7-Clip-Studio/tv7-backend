from httpx import AsyncClient
from asgi_lifespan import LifespanManager
from app.main import app

import pytest
pytestmark = pytest.mark.asyncio

async def test_health():
    async with LifespanManager(app):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            r = await ac.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"
