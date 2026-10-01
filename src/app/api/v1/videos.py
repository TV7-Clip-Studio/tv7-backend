from __future__ import annotations

import math
import mimetypes
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Query, Security, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jwt import JWTDecodeError, TokenType, create_token, decode_token
from app.db.models import (
    Clip,
    ClipGenerationMode,
    ClipStatus,
    User,
    Video,
    VideoIngestType,
    VideoStatus,
)
from app.deps.db import get_session, get_user_repository, get_video_repository
from app.deps.security import require_jwt_user
from app.repositories.clips import ClipRepository
from app.repositories.users import UserRepository
from app.repositories.videos import VideoRepository
from app.schemas import ClipRead, VideoRead
from app.services.auth import resolve_user_from_token
from app.services.source_media import store_video_source

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


class SourceTicketResponse(BaseModel):
    url: str
    expires_in_seconds: int


def video_read(video: Video) -> VideoRead:
    result = VideoRead.model_validate(video, from_attributes=True)
    if video.upload_original_path:
        result.source_media_url = f"/api/v1/videos/{video.id}/source"
    return result


async def owned_video(video_id: int, session: AsyncSession, user: User) -> Video:
    video = await session.get(Video, video_id)
    if video is None or video.requested_by_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video


class ClipUpsert(BaseModel):
    start_sec: float = Field(ge=0, allow_inf_nan=False)
    end_sec: float = Field(gt=0, allow_inf_nan=False)
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
    user: User = Depends(require_jwt_user),
) -> list[VideoRead]:
    videos = await repo.list_with_clips(user_id=user.id)
    return [video_read(video) for video in videos]


@router.get("/{video_id}", response_model=VideoRead)
async def get_video_status(
    video_id: int,
    repo: VideoRepository = Depends(get_video_repository),
    user: User = Depends(require_jwt_user),
) -> VideoRead:
    video = await repo.get_with_clips(video_id, user_id=user.id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    return video_read(video)


@router.post(
    "/{video_id}/clips",
    status_code=status.HTTP_201_CREATED,
    response_model=ClipRead,
)
async def create_clip_for_video(
    video_id: int,
    payload: ClipUpsert,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> ClipRead:
    clip_repo = ClipRepository(session)

    video = await owned_video(video_id, session, user)

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
    user: User = Depends(require_jwt_user),
) -> VideoRead:
    video_repo = VideoRepository(session)
    clip_repo = ClipRepository(session)

    existing = await video_repo.get_by_source_url_for_user(payload.source_url, user.id)
    if existing is not None:
        existing_with_clips = await video_repo.get_with_clips(existing.id, user_id=user.id)
        assert existing_with_clips is not None
        return video_read(existing_with_clips)

    # Registration records metadata; source media arrives in a separate owner-only upload.
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
        requested_by_user_id=user.id,
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
    return video_read(video_with_clips)


@router.post("/{video_id}/source", response_model=VideoRead)
async def upload_video_source(
    video_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> VideoRead:
    video = await owned_video(video_id, session, user)
    try:
        path, checksum, size = await store_video_source(video_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    old_path = video.upload_original_path
    video.upload_original_path = str(path.resolve())
    video.upload_checksum = checksum
    video.upload_file_size_bytes = size
    video.file_size_bytes = size
    await session.commit()
    private_root = Path(settings.SOURCE_MEDIA_STORAGE_DIR).resolve()
    if old_path and old_path != video.upload_original_path:
        previous = Path(old_path).resolve()
        if previous.is_relative_to(private_root):
            previous.unlink(missing_ok=True)
    loaded = await VideoRepository(session).get_with_clips(video_id, user_id=user.id)
    assert loaded is not None
    return video_read(loaded)


@router.get("/{video_id}/source")
async def get_video_source(
    video_id: int,
    ticket: str | None = Query(default=None),
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_optional_bearer)] = None,
    user_repo: UserRepository = Depends(get_user_repository),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    if credentials is not None:
        user = await resolve_user_from_token(credentials.credentials, user_repo)
    elif ticket:
        try:
            claims = decode_token(ticket, expected_type=TokenType.VIDEO_SOURCE)
        except JWTDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket"
            ) from exc
        if claims.get("scopes") != [f"video:source:{video_id}"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket scope"
            )
        ticket_user = await user_repo.get_by_email(str(claims.get("sub", "")))
        if ticket_user is None or not ticket_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket user"
            )
        user = ticket_user
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    video = await owned_video(video_id, session, user)
    if not video.upload_original_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not uploaded")
    path = Path(video.upload_original_path)
    expected_root = Path(settings.SOURCE_MEDIA_STORAGE_DIR).resolve()
    if not path.resolve().is_relative_to(expected_root) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/{video_id}/source-ticket", response_model=SourceTicketResponse)
async def create_source_ticket(
    video_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> SourceTicketResponse:
    video = await owned_video(video_id, session, user)
    if not video.upload_original_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not uploaded")
    duration_minutes = math.ceil((video.duration_seconds or 0) / 60)
    lifetime_minutes = min(240, max(15, duration_minutes + 15))
    ticket = create_token(
        subject=user.email,
        token_type=TokenType.VIDEO_SOURCE,
        scopes=[f"video:source:{video_id}"],
        expires_minutes=lifetime_minutes,
    )
    query = urlencode({"ticket": ticket})
    return SourceTicketResponse(
        url=f"/api/v1/videos/{video_id}/source?{query}",
        expires_in_seconds=lifetime_minutes * 60,
    )
