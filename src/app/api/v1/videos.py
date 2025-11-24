from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, HttpUrl

from app.db.models import ClipGenerationMode, VideoIngestType, VideoStatus
from app.deps.db import get_video_repository
from app.repositories.videos import VideoRepository
from app.schemas import VideoRead
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
