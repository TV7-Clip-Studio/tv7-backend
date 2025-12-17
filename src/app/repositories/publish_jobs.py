from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PublishJob, PublishJobStatus


class PublishJobRepository:
    """Persistence helpers for publish jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_job(  # noqa: PLR0913
        self,
        *,
        clip_id: int,
        platform: str,
        asset_url: str | None = None,
        asset_checksum: str | None = None,
        asset_size_bytes: int | None = None,
        status: PublishJobStatus = PublishJobStatus.PENDING,
    ) -> PublishJob:
        job = PublishJob(
            clip_id=clip_id,
            platform=platform,
            status=status.value,
            asset_url=asset_url,
            asset_checksum=asset_checksum,
            asset_size_bytes=asset_size_bytes,
        )
        self._session.add(job)
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def get(self, job_id: int) -> PublishJob | None:
        job = await self._session.get(PublishJob, job_id)
        return cast(PublishJob | None, job)

    async def list_for_clip(self, clip_id: int) -> list[PublishJob]:
        result = await self._session.execute(
            select(PublishJob).where(PublishJob.clip_id == clip_id)
        )
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self._session.commit()
