from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import YouTubeCredential


@dataclass(slots=True)
class CredentialTokenData:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str | None = None
    token_type: str | None = None


@dataclass(slots=True)
class CredentialTokenUpdate:
    access_token: str
    expires_at: datetime
    refresh_token: str | None = None
    scope: str | None = None
    token_type: str | None = None


class YouTubeCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: int) -> YouTubeCredential | None:
        stmt = select(YouTubeCredential).where(YouTubeCredential.user_id == user_id)
        result = await self._session.execute(stmt)
        credential: YouTubeCredential | None = result.scalar_one_or_none()
        return credential

    async def upsert(
        self,
        *,
        user_id: int,
        data: CredentialTokenData,
    ) -> YouTubeCredential:
        credential = await self.get_by_user_id(user_id)
        if credential is None:
            credential = YouTubeCredential(
                user_id=user_id,
                access_token=data.access_token,
                refresh_token=data.refresh_token,
                expires_at=data.expires_at,
                scope=data.scope,
                token_type=data.token_type,
            )
            self._session.add(credential)
        else:
            credential.access_token = data.access_token
            credential.refresh_token = data.refresh_token
            credential.expires_at = data.expires_at
            credential.scope = data.scope
            credential.token_type = data.token_type
            credential.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        return credential

    async def update_tokens(
        self,
        credential: YouTubeCredential,
        data: CredentialTokenUpdate,
    ) -> YouTubeCredential:
        credential.access_token = data.access_token
        credential.expires_at = data.expires_at
        if data.refresh_token:
            credential.refresh_token = data.refresh_token
        if data.scope:
            credential.scope = data.scope
        if data.token_type:
            credential.token_type = data.token_type
        credential.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        return credential

    async def delete_for_user(self, user_id: int) -> None:
        credential = await self.get_by_user_id(user_id)
        if credential is not None:
            await self._session.delete(credential)
            await self._session.flush()
