from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_list_users_initially_empty(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/users/")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


async def test_create_user(async_client: AsyncClient) -> None:
    payload = {"email": "alice@example.com", "full_name": "Alice Example"}
    response = await async_client.post("/api/v1/users/", json=payload)
    body = response.json()

    assert response.status_code == HTTPStatus.CREATED
    assert body["email"] == payload["email"]
    assert body["full_name"] == payload["full_name"]
    assert isinstance(body["id"], int)

    list_response = await async_client.get("/api/v1/users/")
    assert any(user["email"] == payload["email"] for user in list_response.json())


async def test_create_user_conflict(async_client: AsyncClient) -> None:
    payload = {"email": "duplicate@example.com", "full_name": "Duplicate User"}
    first = await async_client.post("/api/v1/users/", json=payload)
    assert first.status_code == HTTPStatus.CREATED

    conflict = await async_client.post("/api/v1/users/", json=payload)
    assert conflict.status_code == HTTPStatus.CONFLICT
    assert conflict.json() == {
        "error": {"code": HTTPStatus.CONFLICT, "message": "Email already in use"}
    }
