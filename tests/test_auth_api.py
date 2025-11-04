from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_login_returns_tokens(
    async_client: AsyncClient, login_credentials: tuple[str, str]
) -> None:
    email, password = login_credentials
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_rejects_invalid_credentials(
    async_client: AsyncClient, login_credentials: tuple[str, str]
) -> None:
    email, _ = login_credentials
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"]["message"].startswith("Invalid email or password")


async def test_refresh_token_issues_new_access_token(
    async_client: AsyncClient, login_credentials: tuple[str, str]
) -> None:
    email, password = login_credentials
    login_response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == HTTPStatus.OK
    payload = refresh_response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
