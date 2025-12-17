from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clip,
    ClipGenerationMode,
    ClipStatus,
    Video,
    VideoIngestType,
    VideoStatus,
)
from app.deps.db import get_session, get_video_repository
from app.repositories.clips import ClipRepository
from app.repositories.videos import VideoRepository
from app.schemas import ClipRead, VideoRead

router = APIRouter()


class ClipUpsert(BaseModel):
    start_sec: int
    end_sec: int
    local_path: str | None = None
    asset_url: str | None = None
    asset_checksum: str | None = None
    asset_size_bytes: int | None = None
    ready_local_only: bool = False
    caption_text: str | None = None
    render_width: int | None = None
    render_height: int | None = None
    frame_rate: float | None = None
    file_size_bytes: int | None = None
    thumbnail_path: str | None = None
    status: ClipStatus = ClipStatus.READY


class LocalVideoCreate(BaseModel):
    source_url: str = Field(
        ..., description="Identifier for the local video (e.g., file:// or local://)"
    )
    title: str | None = Field(
        default=None,
        description="Human-friendly title from desktop (mapped to original_filename).",
    )
    local_path: str | None = None
    original_filename: str | None = None
    upload_checksum: str | None = None
    upload_file_size_bytes: int | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    transcript_text: str | None = None
    transcript_language: str | None = None
    workspace_root: str | None = None
    status: VideoStatus = VideoStatus.READY
    clip_generation_mode: ClipGenerationMode = ClipGenerationMode.REPLACE
    clips: list[ClipUpsert] | None = None


@router.get("", response_model=list[VideoRead])
async def list_videos(
    repo: VideoRepository = Depends(get_video_repository),
) -> list[VideoRead]:
    videos = await repo.list_with_clips()
    return [
        cast(VideoRead, VideoRead.model_validate(video, from_attributes=True)) for video in videos
    ]


@router.get("/{video_id}", response_model=VideoRead)
async def get_video_status(
    video_id: int, repo: VideoRepository = Depends(get_video_repository)
) -> VideoRead:
    video = await repo.get_with_clips(video_id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    video_schema: VideoRead = VideoRead.model_validate(video, from_attributes=True)
    return video_schema


@router.post(
    "/{video_id}/clips",
    status_code=status.HTTP_201_CREATED,
    response_model=ClipRead,
)
async def create_clip_for_video(
    video_id: int,
    payload: ClipUpsert,
    session: AsyncSession = Depends(get_session),
) -> ClipRead:
    video_repo = VideoRepository(session)
    clip_repo = ClipRepository(session)

    video = await video_repo.get(video_id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    clip = Clip(
        video_id=video.id,
        start_sec=payload.start_sec,
        end_sec=payload.end_sec,
        local_path=payload.local_path,
        asset_url=payload.asset_url,
        asset_checksum=payload.asset_checksum,
        asset_size_bytes=payload.asset_size_bytes,
        ready_local_only=payload.ready_local_only,
        caption_text=payload.caption_text,
        render_width=payload.render_width,
        render_height=payload.render_height,
        frame_rate=payload.frame_rate,
        file_size_bytes=payload.file_size_bytes,
        thumbnail_path=payload.thumbnail_path,
        status=payload.status.value,
    )
    await clip_repo.add(clip)
    await session.commit()
    await session.refresh(clip)

    return cast(ClipRead, ClipRead.model_validate(clip, from_attributes=True))


@router.post(
    "/local",
    status_code=status.HTTP_201_CREATED,
    response_model=VideoRead,
)
async def register_local_video(
    payload: LocalVideoCreate,
    session: AsyncSession = Depends(get_session),
) -> VideoRead:
    video_repo = VideoRepository(session)
    clip_repo = ClipRepository(session)

    # Desktop-managed entries never upload source media to the server.
    video_status = payload.status
    payload = payload.model_copy(update={"local_path": None})

    video = Video(
        source_url=payload.source_url,
        local_path=payload.local_path,
        ingest_type=VideoIngestType.UPLOAD.value,
        original_filename=payload.title or payload.original_filename,
        upload_checksum=payload.upload_checksum,
        upload_file_size_bytes=payload.upload_file_size_bytes,
        transcript_text=payload.transcript_text,
        transcript_language=payload.transcript_language,
        duration_seconds=payload.duration_seconds,
        file_size_bytes=payload.file_size_bytes,
        workspace_root=payload.workspace_root,
        status=video_status.value,
        clip_generation_mode=payload.clip_generation_mode.value,
    )
    await video_repo.add(video)
    await session.flush()
    await session.refresh(video)

    if payload.clips:
        for clip_payload in payload.clips:
            clip = Clip(
                video_id=video.id,
                start_sec=clip_payload.start_sec,
                end_sec=clip_payload.end_sec,
                local_path=clip_payload.local_path,
                asset_url=clip_payload.asset_url,
                asset_checksum=clip_payload.asset_checksum,
                asset_size_bytes=clip_payload.asset_size_bytes,
                ready_local_only=clip_payload.ready_local_only,
                caption_text=clip_payload.caption_text,
                render_width=clip_payload.render_width,
                render_height=clip_payload.render_height,
                frame_rate=clip_payload.frame_rate,
                file_size_bytes=clip_payload.file_size_bytes,
                status=clip_payload.status.value,
            )
            await clip_repo.add(clip)

    await session.commit()
    await session.refresh(video)
    video_with_clips = await video_repo.get_with_clips(video.id)
    if not video_with_clips:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Video not found after create"
        )
    return cast(VideoRead, VideoRead.model_validate(video_with_clips, from_attributes=True))
