from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Video


class VideoRepository:
    """Persistence helpers for Video entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, video_id: int) -> Video | None:
        video: Video | None = await self._session.get(Video, video_id)
        return video

    async def get_by_source_url(self, source_url: str) -> Video | None:
        result = await self._session.execute(select(Video).where(Video.source_url == source_url))
        video: Video | None = result.scalar_one_or_none()
        return video

    async def add(self, video: Video) -> None:
        self._session.add(video)

    async def refresh(self, video: Video) -> Video:
        await self._session.flush()
        await self._session.refresh(video)
        return video

    async def get_with_clips(self, video_id: int) -> Video | None:
        """Fetch a single video with clips eagerly loaded."""
        stmt = select(Video).options(selectinload(Video.clips)).where(Video.id == video_id)
        result = await self._session.execute(stmt)
        video: Video | None = result.scalar_one_or_none()
        return video

    async def list_with_clips(self, *, limit: int | None = None) -> list[Video]:
        stmt = select(Video).options(selectinload(Video.clips)).order_by(Video.created_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        rows = result.scalars().unique().all()
        return list(rows)
