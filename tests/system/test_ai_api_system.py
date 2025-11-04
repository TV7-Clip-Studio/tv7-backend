from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.system
class TestAiApiSystem:
    async def test_execute_returns_echo(self, system_client: AsyncClient) -> None:
        response = await system_client.post(
            "/api/v1/ai/execute",
            json={"input": "hello", "agent_id": "demo"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["output"] == "ECHO: hello"
        assert body["meta"]["agent_id"] == "demo"

    async def test_missing_token_is_forbidden(self, async_client: AsyncClient) -> None:
        response = await async_client.post(
            "/api/v1/ai/execute",
            json={"input": "oops", "agent_id": "demo"},
        )
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["message"] == "Not authenticated"
