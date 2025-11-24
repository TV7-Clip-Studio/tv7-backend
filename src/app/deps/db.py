from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.repositories.clips import ClipRepository
from app.repositories.publish_jobs import PublishJobRepository
from app.repositories.users import UserRepository
from app.repositories.videos import VideoRepository
from app.repositories.youtube_credentials import YouTubeCredentialRepository


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


async def get_user_repository(session: AsyncSession = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


async def get_video_repository(session: AsyncSession = Depends(get_session)) -> VideoRepository:
    return VideoRepository(session)


async def get_clip_repository(session: AsyncSession = Depends(get_session)) -> ClipRepository:
    return ClipRepository(session)


async def get_publish_job_repository(
    session: AsyncSession = Depends(get_session),
) -> PublishJobRepository:
    return PublishJobRepository(session)


async def get_youtube_credential_repository(
    session: AsyncSession = Depends(get_session),
) -> YouTubeCredentialRepository:
    return YouTubeCredentialRepository(session)
