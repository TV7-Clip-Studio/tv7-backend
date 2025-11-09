from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl

from app.db.models import VideoStatus
from app.deps.db import get_video_repository
from app.repositories.videos import VideoRepository
from app.schemas import VideoRead
from app.services.videos import (
    InvalidYouTubeURL,
    VideoIngestionResult,
)
from app.services.videos import ingest_video as ingest_video_service

router = APIRouter()


class VideoIngestRequest(BaseModel):
    youtube_url: HttpUrl


class VideoIngestResponse(BaseModel):
    video: VideoRead
    queued: bool = True
    created: bool


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED, response_model=VideoIngestResponse)
async def ingest_video_endpoint(
    payload: VideoIngestRequest,
    repo: VideoRepository = Depends(get_video_repository),
) -> VideoIngestResponse:
    try:
        result = await ingest_video_service(str(payload.youtube_url), repo=repo)
    except InvalidYouTubeURL as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return _serialize_response(result)


def _serialize_response(result: VideoIngestionResult) -> VideoIngestResponse:
    video = result.video
    video_schema = VideoRead(
        id=video.id,
        source_url=video.source_url,
        local_path=video.local_path,
        transcript_text=video.transcript_text,
        transcript_language=video.transcript_language,
        duration_seconds=video.duration_seconds,
        file_size_bytes=video.file_size_bytes,
        error_message=video.error_message,
        status=VideoStatus(video.status),
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
