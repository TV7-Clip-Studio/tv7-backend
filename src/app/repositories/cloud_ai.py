from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CloudAiCreditTransaction,
    CloudAiCreditTransactionKind,
    CloudAiRequest,
    CloudAiRequestStatus,
    User,
)


@dataclass(frozen=True)
class CloudAiRequestCreate:
    user_id: int
    provider: str
    model: str | None
    status: CloudAiRequestStatus
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    credits_charged: int = 0
    latency_ms: int | None = None


class CloudAiRepository:
    """Persistence helpers for cloud AI credits and request metering."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_credit_balance(self, user_id: int) -> int:
        balance = await self._session.scalar(
            select(func.coalesce(func.sum(CloudAiCreditTransaction.amount), 0)).where(
                CloudAiCreditTransaction.user_id == user_id
            )
        )
        return int(balance or 0)

    async def grant_credits(self, user_id: int, amount: int, *, reason: str) -> None:
        self._session.add(
            CloudAiCreditTransaction(
                user_id=user_id,
                amount=amount,
                kind=CloudAiCreditTransactionKind.GRANT.value,
                reason=reason,
            )
        )
        await self._session.flush()

    async def charge_credits(self, user_id: int, amount: int, *, request_id: int) -> None:
        self._session.add(
            CloudAiCreditTransaction(
                user_id=user_id,
                amount=-amount,
                kind=CloudAiCreditTransactionKind.USAGE.value,
                reason="cloud_ai_request",
                request_id=request_id,
            )
        )
        await self._session.flush()

    async def create_request(self, data: CloudAiRequestCreate) -> CloudAiRequest:
        request = CloudAiRequest(
            user_id=data.user_id,
            provider=data.provider,
            model=data.model,
            status=data.status.value,
            error_code=data.error_code,
            prompt_tokens=data.prompt_tokens,
            completion_tokens=data.completion_tokens,
            total_tokens=data.total_tokens,
            credits_charged=data.credits_charged,
            latency_ms=data.latency_ms,
        )
        self._session.add(request)
        await self._session.flush()
        await self._session.refresh(request)
        return request

    async def list_recent_requests(self, *, limit: int = 100) -> list[CloudAiRequest]:
        result = await self._session.execute(
            select(CloudAiRequest)
            .options(selectinload(CloudAiRequest.user))
            .order_by(CloudAiRequest.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_user_balances(self) -> list[tuple[User, int]]:
        result = await self._session.execute(
            select(User, func.coalesce(func.sum(CloudAiCreditTransaction.amount), 0))
            .outerjoin(CloudAiCreditTransaction, CloudAiCreditTransaction.user_id == User.id)
            .group_by(User.id)
            .order_by(User.email)
        )
        return [(row[0], int(row[1] or 0)) for row in result.all()]

    async def commit(self) -> None:
        await self._session.commit()
