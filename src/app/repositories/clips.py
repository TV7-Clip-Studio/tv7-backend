from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip


class ClipRepository:
    """Persistence helpers for Clip entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, clip_id: int) -> Clip | None:
        clip: Clip | None = await self._session.get(Clip, clip_id)
        return clip

    async def list_for_video(self, video_id: int) -> list[Clip]:
        result = await self._session.execute(select(Clip).where(Clip.video_id == video_id))
        return list(result.scalars().all())

    async def add(self, clip: Clip) -> None:
        self._session.add(clip)

    async def commit(self) -> None:
        await self._session.commit()
