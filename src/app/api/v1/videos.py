from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import Video, VideoStatus
from app.deps.security import require_beta_key
from app.schemas import VideoRead
from app.services.ingest import enqueue_video

router = APIRouter(dependencies=[Depends(require_beta_key)])
logger = logging.getLogger(__name__)


YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


class VideoIngestRequest(BaseModel):
    youtube_url: HttpUrl


class VideoIngestResponse(BaseModel):
    video: VideoRead
    queued: bool = True
    created: bool


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_scope() as session:
        yield session


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED, response_model=VideoIngestResponse)
async def ingest_video(
    payload: VideoIngestRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VideoIngestResponse:
    if payload.youtube_url.host not in YOUTUBE_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL must point to YouTube",
        )

    existing = (
        await db.execute(select(Video).where(Video.source_url == str(payload.youtube_url)))
    ).scalar_one_or_none()

    created = False

    if existing:
        video = existing
        logger.info(
            "Video already ingested; re-queueing",
            extra={"video_id": video.id, "source_url": video.source_url},
        )
    else:
        video = Video(source_url=str(payload.youtube_url), status=VideoStatus.INGESTED.value)
        db.add(video)
        await db.flush()
        await db.refresh(video)
        created = True
        logger.info("Created new video record", extra={"video_id": video.id})

    await enqueue_video(video.id, source_url=video.source_url)
    await db.refresh(video)

    video_schema = VideoRead(
        id=video.id,
        source_url=video.source_url,
        local_path=video.local_path,
        transcript_text=video.transcript_text,
        status=VideoStatus(video.status),
        created_at=video.created_at,
        updated_at=video.updated_at,
        clips=[],
    )
    payload_model = VideoIngestResponse(video=video_schema, queued=True, created=created)
    return payload_model
