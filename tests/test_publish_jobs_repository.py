from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PublishJobStatus
from app.repositories.publish_jobs import PublishJobRepository


@pytest.mark.anyio
async def test_add_and_list_publish_jobs(db_session: AsyncSession) -> None:
    repo = PublishJobRepository(db_session)
    job1 = await repo.add_job(
        clip_id=1,
        platform="youtube_shorts",
        asset_url="https://example.com/a.mp4",
        asset_checksum="abc",
        asset_size_bytes=123,
        status=PublishJobStatus.PENDING,
    )
    await repo.add_job(
        clip_id=1,
        platform="tiktok",
        status=PublishJobStatus.QUEUED,
    )
    await repo.commit()

    jobs = await repo.list_for_clip(1)
    assert {j.platform for j in jobs} == {"youtube_shorts", "tiktok"}
    assert job1.asset_url == "https://example.com/a.mp4"
