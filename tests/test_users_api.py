from __future__ import annotations

from collections.abc import Generator
from http import HTTPStatus

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import users as users_api
from app.core.security import verify_password
from app.db.models import User
from app.schemas import UserCreate

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def beta_key(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("BETA_API_KEY", "test-beta-key")
    yield


async def test_list_users_initially_empty(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/users/", headers={"X-API-Key": "test-beta-key"})
    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


async def test_create_user(async_client: AsyncClient) -> None:
    payload = {
        "email": "alice@example.com",
        "full_name": "Alice Example",
        "password": "alice-secret",
    }
    response = await async_client.post(
        "/api/v1/users/", json=payload, headers={"X-API-Key": "test-beta-key"}
    )
    body = response.json()

    assert response.status_code == HTTPStatus.CREATED
    assert body["email"] == payload["email"]
    assert body["full_name"] == payload["full_name"]
    assert isinstance(body["id"], int)
    assert body["is_active"] is True
    assert "created_at" in body
    assert "updated_at" in body
    assert "password_hash" not in body

    list_response = await async_client.get("/api/v1/users/", headers={"X-API-Key": "test-beta-key"})
    users = list_response.json()
    assert any(user["email"] == payload["email"] for user in users)
    assert all("password_hash" not in user for user in users)


async def test_create_user_conflict(async_client: AsyncClient) -> None:
    payload = {
        "email": "duplicate@example.com",
        "full_name": "Duplicate User",
        "password": "duplicate-secret",
    }
    first = await async_client.post(
        "/api/v1/users/", json=payload, headers={"X-API-Key": "test-beta-key"}
    )
    assert first.status_code == HTTPStatus.CREATED

    conflict = await async_client.post(
        "/api/v1/users/", json=payload, headers={"X-API-Key": "test-beta-key"}
    )
    assert conflict.status_code == HTTPStatus.CONFLICT
    assert conflict.json() == {
        "error": {"code": HTTPStatus.CONFLICT, "message": "Email already in use"}
    }


async def test_create_user_hashes_password(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = {
        "email": "bob@example.com",
        "full_name": "Bob Example",
        "password": "bob-secret",
    }
    response = await async_client.post(
        "/api/v1/users/", json=payload, headers={"X-API-Key": "test-beta-key"}
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()

    user = await db_session.get(User, body["id"])
    assert user is not None
    assert user.password_hash != payload["password"]
    assert verify_password(payload["password"], user.password_hash)


async def test_create_user_direct_call(db_session: AsyncSession) -> None:
    payload = UserCreate(
        email="direct@example.com",
        full_name="Direct User",
        password="direct-secret",
    )
    user = await users_api.create_user(payload, db_session)
    assert user.email == payload.email
    assert verify_password(payload.password, user.password_hash)

    with pytest.raises(HTTPException) as exc_info:
        await users_api.create_user(payload, db_session)
    assert exc_info.value.status_code == HTTPStatus.CONFLICT
