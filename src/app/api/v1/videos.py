from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, HttpUrl
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
from app.services.upload_storage import (
    UploadError,
    UploadTooLargeError,
    persist_upload_temporarily,
)
from app.services.videos import (
    InvalidYouTubeURL,
    UploadIngestError,
    VideoIngestionResult,
    ingest_uploaded_video,
)
from app.services.videos import ingest_video as ingest_video_service

router = APIRouter()


class YouTubeIngestRequest(BaseModel):
    youtube_url: HttpUrl
    append_clips: bool = False


class VideoIngestResponse(BaseModel):
    video: VideoRead
    queued: bool = True
    created: bool


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
    metadata_only: bool = Field(
        default=False,
        description="If true, server will not attempt to download or host the source video.",
    )


@router.post(
    "/ingest/youtube",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VideoIngestResponse,
)
async def ingest_youtube_endpoint(
    payload: YouTubeIngestRequest,
    repo: VideoRepository = Depends(get_video_repository),
) -> VideoIngestResponse:
    try:
        mode = ClipGenerationMode.APPEND if payload.append_clips else ClipGenerationMode.REPLACE
        result = await ingest_video_service(
            str(payload.youtube_url),
            repo=repo,
            clip_mode=mode,
        )
    except InvalidYouTubeURL as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return _serialize_response(result)


@router.post(
    "/ingest/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VideoIngestResponse,
)
async def ingest_upload_endpoint(
    file: UploadFile = File(...),
    append_clips: bool = Form(False),
    repo: VideoRepository = Depends(get_video_repository),
) -> VideoIngestResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded file name missing",
        )

    try:
        stored = await persist_upload_temporarily(file)
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except UploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    try:
        mode = ClipGenerationMode.APPEND if append_clips else ClipGenerationMode.REPLACE
        result = await ingest_uploaded_video(
            stored,
            repo=repo,
            clip_mode=mode,
        )
    except UploadIngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _serialize_response(result)


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VideoIngestResponse,
    include_in_schema=False,
)
async def ingest_video_legacy(
    payload: YouTubeIngestRequest,
    repo: VideoRepository = Depends(get_video_repository),
) -> VideoIngestResponse:
    """Backward compatible alias for /ingest/youtube."""

    response: VideoIngestResponse = await ingest_youtube_endpoint(payload, repo)
    return response


def _serialize_response(result: VideoIngestionResult) -> VideoIngestResponse:
    video = result.video
    video_schema = VideoRead(
        id=video.id,
        source_url=video.source_url,
        local_path=video.local_path,
        ingest_type=VideoIngestType(video.ingest_type),
        original_filename=video.original_filename,
        upload_checksum=video.upload_checksum,
        upload_file_size_bytes=video.upload_file_size_bytes,
        transcript_text=video.transcript_text,
        transcript_language=video.transcript_language,
        duration_seconds=video.duration_seconds,
        file_size_bytes=video.file_size_bytes,
        error_message=video.error_message,
        status=VideoStatus(video.status),
        clip_generation_mode=ClipGenerationMode(video.clip_generation_mode),
        created_at=video.created_at,
        updated_at=video.updated_at,
        requested_by_user_id=video.requested_by_user_id,
        clips=[],
    )
    return VideoIngestResponse(video=video_schema, queued=result.queued, created=result.created)


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
    video_status = VideoStatus.READY
    payload = payload.copy(update={"local_path": None})

    video = Video(
        source_url=payload.source_url,
        local_path=payload.local_path,
        ingest_type=VideoIngestType.UPLOAD.value,
        original_filename=payload.original_filename,
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
