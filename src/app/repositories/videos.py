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

    async def get_by_source_url_for_user(self, source_url: str, user_id: int) -> Video | None:
        result = await self._session.execute(
            select(Video).where(
                Video.source_url == source_url,
                Video.requested_by_user_id == user_id,
            )
        )
        return result.scalars().first()

    async def add(self, video: Video) -> None:
        self._session.add(video)

    async def refresh(self, video: Video) -> Video:
        await self._session.flush()
        await self._session.refresh(video)
        return video

    async def update(self, video: Video) -> Video:
        """Update video and commit changes."""
        await self._session.flush()
        await self._session.refresh(video)
        return video

    async def get_with_clips(self, video_id: int, *, user_id: int | None = None) -> Video | None:
        """Fetch a single video with clips eagerly loaded."""
        stmt = select(Video).options(selectinload(Video.clips)).where(Video.id == video_id)
        if user_id is not None:
            stmt = stmt.where(Video.requested_by_user_id == user_id)
        result = await self._session.execute(stmt)
        video: Video | None = result.scalar_one_or_none()
        return video

    async def list_with_clips(
        self, *, limit: int | None = None, user_id: int | None = None
    ) -> list[Video]:
        stmt = select(Video).options(selectinload(Video.clips)).order_by(Video.created_at.desc())
        if user_id is not None:
            stmt = stmt.where(Video.requested_by_user_id == user_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        rows = result.scalars().unique().all()
        return list(rows)

    async def delete(self, video_id: int) -> None:
        """Delete a video by ID."""
        video = await self.get(video_id)
        if video:
            await self._session.delete(video)
            await self._session.flush()

    async def commit(self) -> None:
        """Persist pending changes so other sessions can observe them."""
        await self._session.commit()
