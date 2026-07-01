from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.jwt import JWTDecodeError, TokenType, create_token, decode_token
from app.db.models import CloudAiRequestStatus, User
from app.repositories.cloud_ai import CloudAiRepository, CloudAiRequestCreate
from app.repositories.users import UserRepository
from app.schemas import (
    CloudAiExecuteRequest,
    CloudAiExecuteResponse,
    CloudAiUsage,
    EngineCloudAiTokenResponse,
    LicenseReadinessResponse,
)

ENGINE_CLOUD_AI_SCOPE = "engine:cloud_ai"


class CloudAiErrorCode:
    AUTH_REQUIRED = "AI_AUTH_REQUIRED"
    LICENSE_REQUIRED = "AI_LICENSE_REQUIRED"
    QUOTA_EXCEEDED = "AI_QUOTA_EXCEEDED"
    PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    NETWORK_UNAVAILABLE = "AI_NETWORK_UNAVAILABLE"
    CONTEXT_TOO_LARGE = "AI_CONTEXT_TOO_LARGE"


class CloudAiHTTPException(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                "details": {},
            },
        )


@dataclass(frozen=True)
class ProviderResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None


class DeepSeekAdapter:
    async def complete(self, payload: CloudAiExecuteRequest) -> ProviderResult:
        if not settings.DEEPSEEK_API_KEY:
            raise CloudAiHTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                CloudAiErrorCode.PROVIDER_UNAVAILABLE,
                "TV7 cloud AI provider is not configured.",
            )

        body: dict[str, Any] = {
            "model": payload.model or settings.DEEPSEEK_MODEL,
            "messages": [message.model_dump() for message in payload.messages],
        }
        if payload.temperature is not None:
            body["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            body["max_tokens"] = payload.max_tokens

        return await asyncio.to_thread(self._post_completion, body)

    def _post_completion(self, body: dict[str, Any]) -> ProviderResult:
        request = urllib.request.Request(
            settings.DEEPSEEK_API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == status.HTTP_413_CONTENT_TOO_LARGE:
                raise CloudAiHTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    CloudAiErrorCode.CONTEXT_TOO_LARGE,
                    "Cloud AI context is too large.",
                ) from exc
            raise CloudAiHTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                CloudAiErrorCode.PROVIDER_UNAVAILABLE,
                "Cloud AI provider could not complete the request.",
            ) from exc
        except urllib.error.URLError as exc:
            raise CloudAiHTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                CloudAiErrorCode.NETWORK_UNAVAILABLE,
                "Cloud AI provider is unreachable.",
            ) from exc

        data = json.loads(response_body)
        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        usage = data.get("usage") or {}
        return ProviderResult(
            content=str(message.get("content") or ""),
            model=str(data.get("model") or body["model"]),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            finish_reason=first_choice.get("finish_reason"),
        )


async def ensure_testing_admin_credit_grant(user: User, repo: CloudAiRepository) -> None:
    if user.email != settings.ADMIN_USERNAME:
        return
    balance = await repo.get_credit_balance(user.id)
    if balance <= 0:
        await repo.grant_credits(
            user.id,
            settings.ADMIN_CLOUD_AI_INITIAL_CREDITS,
            reason="testing_admin_initial_grant",
        )


async def get_cloud_ai_license_readiness(
    user: User,
    repo: CloudAiRepository,
) -> LicenseReadinessResponse:
    if not user.is_active:
        return LicenseReadinessResponse(
            account_active=False,
            license_status="required",
            cloud_ai_available=False,
            cloud_ai_credits_remaining=0,
            can_request_engine_cloud_ai_token=False,
            reason_code="AI_LICENSE_REQUIRED",
        )

    await ensure_testing_admin_credit_grant(user, repo)
    balance = await repo.get_credit_balance(user.id)
    if balance <= 0:
        return LicenseReadinessResponse(
            account_active=True,
            license_status="active",
            cloud_ai_available=False,
            cloud_ai_credits_remaining=0,
            can_request_engine_cloud_ai_token=False,
            reason_code="AI_QUOTA_EXCEEDED",
        )

    return LicenseReadinessResponse(
        account_active=True,
        license_status="active",
        cloud_ai_available=True,
        cloud_ai_credits_remaining=balance,
        can_request_engine_cloud_ai_token=True,
        reason_code="READY",
    )


async def issue_engine_cloud_ai_token(
    user: User,
    repo: CloudAiRepository,
) -> EngineCloudAiTokenResponse:
    readiness = await get_cloud_ai_license_readiness(user, repo)
    if not readiness.account_active:
        raise CloudAiHTTPException(
            status.HTTP_403_FORBIDDEN,
            CloudAiErrorCode.LICENSE_REQUIRED,
            "Cloud AI requires an active TV7 account.",
        )

    if not readiness.can_request_engine_cloud_ai_token:
        raise CloudAiHTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            CloudAiErrorCode.QUOTA_EXCEEDED,
            "Cloud AI credits are exhausted.",
        )

    token = create_token(
        subject=user.email,
        token_type=TokenType.ENGINE_CLOUD_AI,
        scopes=[ENGINE_CLOUD_AI_SCOPE],
    )
    return EngineCloudAiTokenResponse(
        token=token,
        expires_in_seconds=settings.ENGINE_CLOUD_AI_TOKEN_EXPIRES_MINUTES * 60,
        credits_remaining=readiness.cloud_ai_credits_remaining,
    )


async def resolve_engine_cloud_ai_user(
    token: str,
    user_repo: UserRepository,
) -> User:
    try:
        payload = decode_token(token, expected_type=TokenType.ENGINE_CLOUD_AI)
    except JWTDecodeError as exc:
        raise CloudAiHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            CloudAiErrorCode.AUTH_REQUIRED,
            "A valid Engine cloud AI token is required.",
        ) from exc

    scopes = payload.get("scopes") or []
    if ENGINE_CLOUD_AI_SCOPE not in scopes:
        raise CloudAiHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            CloudAiErrorCode.AUTH_REQUIRED,
            "Engine cloud AI token is missing the required scope.",
        )

    subject = payload.get("sub")
    if subject is None:
        raise CloudAiHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            CloudAiErrorCode.AUTH_REQUIRED,
            "Engine cloud AI token is invalid.",
        )

    user = await user_repo.get_by_email(str(subject))
    if user is None:
        raise CloudAiHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            CloudAiErrorCode.AUTH_REQUIRED,
            "Engine cloud AI user is not available.",
        )
    return user


def _request_context_size(payload: CloudAiExecuteRequest) -> int:
    return sum(len(message.content) for message in payload.messages)


async def execute_cloud_ai(
    user: User,
    payload: CloudAiExecuteRequest,
    repo: CloudAiRepository,
    provider: DeepSeekAdapter | None = None,
) -> CloudAiExecuteResponse:
    if not user.is_active:
        raise CloudAiHTTPException(
            status.HTTP_403_FORBIDDEN,
            CloudAiErrorCode.LICENSE_REQUIRED,
            "Cloud AI requires an active TV7 account.",
        )

    if _request_context_size(payload) > settings.CLOUD_AI_CONTEXT_MAX_CHARS:
        await repo.create_request(
            CloudAiRequestCreate(
                user_id=user.id,
                provider=settings.CLOUD_AI_PROVIDER,
                model=payload.model or settings.DEEPSEEK_MODEL,
                status=CloudAiRequestStatus.FAILED,
                error_code=CloudAiErrorCode.CONTEXT_TOO_LARGE,
            )
        )
        await repo.commit()
        raise CloudAiHTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            CloudAiErrorCode.CONTEXT_TOO_LARGE,
            "Cloud AI context is too large.",
        )

    charge = settings.CLOUD_AI_DEFAULT_REQUEST_CREDITS
    await ensure_testing_admin_credit_grant(user, repo)
    balance = await repo.get_credit_balance(user.id)
    if balance < charge:
        raise CloudAiHTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            CloudAiErrorCode.QUOTA_EXCEEDED,
            "Cloud AI credits are exhausted.",
        )

    adapter = provider or DeepSeekAdapter()
    start = time.perf_counter()
    try:
        result = await adapter.complete(payload)
    except CloudAiHTTPException as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        code = str(exc.detail.get("code")) if isinstance(exc.detail, dict) else None
        await repo.create_request(
            CloudAiRequestCreate(
                user_id=user.id,
                provider=settings.CLOUD_AI_PROVIDER,
                model=payload.model or settings.DEEPSEEK_MODEL,
                status=CloudAiRequestStatus.FAILED,
                error_code=code,
                latency_ms=latency_ms,
            )
        )
        await repo.commit()
        raise

    latency_ms = int((time.perf_counter() - start) * 1000)
    request = await repo.create_request(
        CloudAiRequestCreate(
            user_id=user.id,
            provider=settings.CLOUD_AI_PROVIDER,
            model=result.model,
            status=CloudAiRequestStatus.SUCCEEDED,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            credits_charged=charge,
            latency_ms=latency_ms,
        )
    )
    await repo.charge_credits(user.id, charge, request_id=request.id)
    remaining = await repo.get_credit_balance(user.id)

    return CloudAiExecuteResponse(
        provider=settings.CLOUD_AI_PROVIDER,
        model=result.model,
        content=result.content,
        raw_finish_reason=result.finish_reason,
        usage=CloudAiUsage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            credits_charged=charge,
            credits_remaining=remaining,
            latency_ms=latency_ms,
        ),
    )
