from __future__ import annotations

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.main import app
from app.repositories.cloud_ai import CloudAiRepository

pytestmark = pytest.mark.asyncio


async def test_app_routes_are_compatible_with_metrics_route_lookup() -> None:
    assert all(hasattr(route, "path") for route in app.routes)


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


async def test_license_readiness_requires_auth(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/auth/license")

    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_license_readiness_reports_quota_required(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await async_client.get("/api/v1/auth/license", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body == {
        "account_active": True,
        "license_status": "active",
        "cloud_ai_available": False,
        "cloud_ai_credits_remaining": 0,
        "can_request_engine_cloud_ai_token": False,
        "engine_cloud_ai_scope": "engine:cloud_ai",
        "reason_code": "AI_QUOTA_EXCEEDED",
    }


async def test_license_readiness_reports_cloud_ai_ready(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    repo = CloudAiRepository(db_session)
    await repo.grant_credits(user.id, 7, reason="license_test")
    await db_session.commit()

    response = await async_client.get("/api/v1/auth/license", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["account_active"] is True
    assert body["license_status"] == "active"
    assert body["cloud_ai_available"] is True
    assert body["cloud_ai_credits_remaining"] == 7
    assert body["can_request_engine_cloud_ai_token"] is True
    assert body["reason_code"] == "READY"


async def test_license_readiness_reports_inactive_account(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    user.is_active = False
    await db_session.commit()

    response = await async_client.get("/api/v1/auth/license", headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["account_active"] is False
    assert body["license_status"] == "required"
    assert body["cloud_ai_available"] is False
    assert body["can_request_engine_cloud_ai_token"] is False
    assert body["reason_code"] == "AI_LICENSE_REQUIRED"
