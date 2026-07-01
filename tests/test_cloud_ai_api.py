from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CloudAiRequest, User
from app.repositories.cloud_ai import CloudAiRepository
from app.services import cloud_ai as cloud_ai_service
from app.services.cloud_ai import ProviderResult


async def _grant_credits(db_session: AsyncSession, email: str, amount: int) -> None:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    repo = CloudAiRepository(db_session)
    await repo.grant_credits(user.id, amount, reason="test_grant")
    await db_session.commit()


async def _cloud_ai_requests_for_user(
    db_session: AsyncSession,
    email: str,
) -> list[CloudAiRequest]:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    return list(
        (await db_session.execute(select(CloudAiRequest).where(CloudAiRequest.user_id == user.id)))
        .scalars()
        .all()
    )


async def test_engine_cloud_ai_token_requires_credits(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "AI_QUOTA_EXCEEDED"


async def test_engine_cloud_ai_token_issued_with_scope_and_balance(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    await _grant_credits(db_session, login_credentials[0], 25)

    response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["scope"] == "engine:cloud_ai"
    assert body["credits_remaining"] == 25


async def test_engine_cloud_ai_token_rejects_inactive_account(
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

    response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AI_LICENSE_REQUIRED"


async def test_cloud_ai_execute_rejects_normal_access_token(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AI_AUTH_REQUIRED"


async def test_cloud_ai_execute_requires_bearer_token(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AI_AUTH_REQUIRED"


async def test_cloud_ai_execute_charges_credits_and_records_usage(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    await _grant_credits(db_session, login_credentials[0], 2)
    token_response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)
    engine_token = token_response.json()["token"]

    class FakeDeepSeekAdapter:
        async def complete(self, _payload):
            return ProviderResult(
                content="cloud result",
                model="deepseek-test",
                prompt_tokens=3,
                completion_tokens=5,
                total_tokens=8,
                finish_reason="stop",
            )

    monkeypatch.setattr(cloud_ai_service, "DeepSeekAdapter", FakeDeepSeekAdapter)

    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        headers={"Authorization": f"Bearer {engine_token}"},
        json={"messages": [{"role": "user", "content": "write a caption"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "cloud result"
    assert body["usage"]["credits_charged"] == 1
    assert body["usage"]["credits_remaining"] == 1
    assert body["usage"]["total_tokens"] == 8

    requests = await _cloud_ai_requests_for_user(db_session, login_credentials[0])
    assert len(requests) == 1
    assert requests[0].status == "succeeded"
    assert requests[0].credits_charged == 1


async def test_cloud_ai_execute_rejects_oversized_context_and_records_failure(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    await _grant_credits(db_session, login_credentials[0], 2)
    monkeypatch.setattr(cloud_ai_service.settings, "CLOUD_AI_CONTEXT_MAX_CHARS", 4)
    token_response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)
    engine_token = token_response.json()["token"]

    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        headers={"Authorization": f"Bearer {engine_token}"},
        json={"messages": [{"role": "user", "content": "too long"}]},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "AI_CONTEXT_TOO_LARGE"

    requests = await _cloud_ai_requests_for_user(db_session, login_credentials[0])
    assert len(requests) == 1
    assert requests[0].status == "failed"
    assert requests[0].error_code == "AI_CONTEXT_TOO_LARGE"


async def test_cloud_ai_execute_records_provider_configuration_failure(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    await _grant_credits(db_session, login_credentials[0], 2)
    monkeypatch.setattr(cloud_ai_service.settings, "DEEPSEEK_API_KEY", None)
    token_response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)
    engine_token = token_response.json()["token"]

    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        headers={"Authorization": f"Bearer {engine_token}"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"

    requests = await _cloud_ai_requests_for_user(db_session, login_credentials[0])
    assert len(requests) == 1
    assert requests[0].status == "failed"
    assert requests[0].error_code == "AI_PROVIDER_UNAVAILABLE"


async def test_cloud_ai_execute_rejects_inactive_delegated_user(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    await _grant_credits(db_session, login_credentials[0], 2)
    token_response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)
    engine_token = token_response.json()["token"]

    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    user.is_active = False
    await db_session.commit()

    response = await async_client.post(
        "/api/v1/cloud-ai/engine/execute",
        headers={"Authorization": f"Bearer {engine_token}"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AI_LICENSE_REQUIRED"


async def test_admin_user_receives_large_testing_credit_grant(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(cloud_ai_service.settings, "ADMIN_USERNAME", login_credentials[0])
    monkeypatch.setattr(cloud_ai_service.settings, "ADMIN_CLOUD_AI_INITIAL_CREDITS", 999)

    response = await async_client.post("/api/v1/cloud-ai/engine-token", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["credits_remaining"] == 999
