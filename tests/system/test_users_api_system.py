from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.db.models import User


@pytest.mark.system
class TestUsersApiSystem:
    async def test_create_and_list_users(
        self,
        system_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await db_session.execute(delete(User))
        await db_session.commit()

        payload = {
            "email": "system@example.com",
            "full_name": "System User",
            "password": "secret-password",
        }
        create_response = await system_client.post(
            "/api/v1/users/",
            json=payload,
            headers={"X-API-Key": "test-beta-key"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["email"] == payload["email"]
        assert created["full_name"] == payload["full_name"]
        assert "password_hash" not in created

        list_response = await system_client.get(
            "/api/v1/users/",
            headers={"X-API-Key": "test-beta-key"},
        )
        assert list_response.status_code == 200
        users = list_response.json()
        assert any(user["email"] == payload["email"] for user in users)

        stored = (
            await db_session.execute(select(User).where(User.email == payload["email"]))
        ).scalar_one()
        assert verify_password(payload["password"], stored.password_hash)

    async def test_create_user_conflict_returns_409(
        self,
        system_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        await db_session.execute(delete(User))
        await db_session.commit()

        payload = {
            "email": "duplicate@example.com",
            "full_name": "Dup User",
            "password": "dup-secret",
        }
        first = await system_client.post(
            "/api/v1/users/",
            json=payload,
            headers={"X-API-Key": "test-beta-key"},
        )
        assert first.status_code == 201

        conflict = await system_client.post(
            "/api/v1/users/",
            json=payload,
            headers={"X-API-Key": "test-beta-key"},
        )
        assert conflict.status_code == 409
        body = conflict.json()
        assert body == {"error": {"code": 409, "message": "Email already in use"}}
