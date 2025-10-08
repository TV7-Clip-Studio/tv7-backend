from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_list_users_initially_empty(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/users/")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


async def test_create_user(async_client: AsyncClient) -> None:
    payload = {
        "email": "integration@example.com",
        "full_name": "Integration User",
        "password": "integration-secret",
    }
    response = await async_client.post("/api/v1/users/", json=payload)
    body = response.json()

    assert response.status_code == HTTPStatus.CREATED
    assert body["email"] == payload["email"]
    assert body["full_name"] == payload["full_name"]
    assert isinstance(body["id"], int)
    assert body["is_active"] is True
    assert "created_at" in body
    assert "updated_at" in body
    assert "password_hash" not in body

    listing = await async_client.get("/api/v1/users/")
    users = listing.json()
    assert any(user["email"] == payload["email"] for user in users)
    assert all("password_hash" not in user for user in users)


async def test_create_user_conflict(async_client: AsyncClient) -> None:
    payload = {
        "email": "duplicate@example.com",
        "full_name": "Duplicate User",
        "password": "duplicate-secret",
    }
    first = await async_client.post("/api/v1/users/", json=payload)
    assert first.status_code == HTTPStatus.CREATED

    conflict = await async_client.post("/api/v1/users/", json=payload)
    assert conflict.status_code == HTTPStatus.CONFLICT
    assert conflict.json() == {
        "error": {"code": HTTPStatus.CONFLICT, "message": "Email already in use"}
    }


async def test_create_user_validation_error(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/users/",
        json={"email": "not-an-email", "full_name": "", "password": "invalid-secret"},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    payload = response.json()
    assert payload["error"]["code"] == HTTPStatus.UNPROCESSABLE_ENTITY
