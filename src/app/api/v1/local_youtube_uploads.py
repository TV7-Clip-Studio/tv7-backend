from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import LocalYouTubeUpload, PublishJob, User
from app.deps.db import get_session
from app.deps.security import require_jwt_user
from app.services import local_youtube_uploads as service
from app.services.youtube_oauth import YouTubeOAuthError, oauth_configured

router = APIRouter()


class LocalUploadRequest(BaseModel):
    creator_profile_id: str = Field(min_length=1, max_length=80)
    target_account_ref: str = Field(pattern=r"^youtube:[A-Za-z0-9_-]+$", max_length=255)
    local_clip_id: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=100, pattern=r"^[^<>]+$")
    description: str = Field(default="", max_length=5000)
    size_bytes: int = Field(gt=0, le=256 * 1024**3)
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_type: Literal["video/mp4", "video/quicktime", "video/webm"] = "video/mp4"
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("scheduled_at must include a timezone")
        return value.astimezone(UTC) if value else None


class VerifyRequest(BaseModel):
    remote_video_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$", max_length=128)


def read_upload(item: LocalYouTubeUpload) -> dict:
    return {
        "upload_id": item.id,
        "creator_profile_id": item.creator_profile_id,
        "target_account_ref": item.target_account_ref,
        "local_clip_id": item.local_clip_id,
        "idempotency_key": item.idempotency_key,
        "title": item.title,
        "description": item.description,
        "size_bytes": item.size_bytes,
        "checksum_sha256": item.checksum_sha256,
        "content_type": item.content_type,
        "scheduled_at": service.utc(item.scheduled_at).isoformat() if item.scheduled_at else None,
        "status": item.status,
        "remote_video_id": item.remote_video_id,
        "last_error": item.last_error,
        "verified_at": service.utc(item.verified_at).isoformat() if item.verified_at else None,
        "created_at": service.utc(item.created_at).isoformat(),
    }


async def owned(session: AsyncSession, upload_id: int, user: User) -> LocalYouTubeUpload:
    item = await session.get(LocalYouTubeUpload, upload_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Local upload not found")
    return item


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("")
async def list_uploads(
    creator_profile_id: str = Query(min_length=1, max_length=80),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    items = (
        await session.execute(
            select(LocalYouTubeUpload)
            .where(
                LocalYouTubeUpload.user_id == user.id,
                LocalYouTubeUpload.creator_profile_id == creator_profile_id,
            )
            .order_by(LocalYouTubeUpload.created_at.desc())
            .limit(500)
        )
    ).scalars()
    return [read_upload(item) for item in items]


@router.get("/{upload_id}")
async def get_upload(
    upload_id: int,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return read_upload(await owned(session, upload_id, user))


async def existing_result(
    session: AsyncSession, item: LocalYouTubeUpload, payload: LocalUploadRequest
) -> dict:
    expected = payload.model_dump(exclude={"scheduled_at"})
    if (
        any(getattr(item, key) != value for key, value in expected.items())
        or (service.utc(item.scheduled_at) if item.scheduled_at else None) != payload.scheduled_at
    ):
        raise HTTPException(
            status_code=409, detail="Idempotency key already belongs to different upload metadata"
        )
    if item.status in {"private_uploaded", "scheduled", "processing"}:
        return read_upload(item)
    if item.provider_upload_uri_encrypted:
        return {**read_upload(item), **await service.transfer_authorization(session, item)}
    raise HTTPException(
        status_code=409,
        detail="Upload initiation is already recorded; inspect status before starting another upload",
    )


@router.post("")
async def create_upload(
    payload: LocalUploadRequest,
    response: Response,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    no_store(response)
    item = (
        await session.execute(
            select(LocalYouTubeUpload).where(
                LocalYouTubeUpload.user_id == user.id,
                LocalYouTubeUpload.idempotency_key == payload.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    try:
        if item:
            return await existing_result(session, item, payload)
        # A new browser can generate a new request key for the same render.
        # Keep the existing provider session; copy/date edits use separate updates.
        item = (
            await session.execute(
                select(LocalYouTubeUpload)
                .where(
                    LocalYouTubeUpload.user_id == user.id,
                    LocalYouTubeUpload.creator_profile_id == payload.creator_profile_id,
                    LocalYouTubeUpload.target_account_ref == payload.target_account_ref,
                    LocalYouTubeUpload.checksum_sha256 == payload.checksum_sha256,
                    LocalYouTubeUpload.size_bytes == payload.size_bytes,
                    LocalYouTubeUpload.content_type == payload.content_type,
                )
                .order_by(LocalYouTubeUpload.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if item:
            await service.credential_for(session, item)
            if item.status in {"private_uploaded", "scheduled", "processing"}:
                return read_upload(item)
            if item.provider_upload_uri_encrypted:
                return {**read_upload(item), **await service.transfer_authorization(session, item)}
            raise HTTPException(
                status_code=409,
                detail="This rendered clip already has an upload record; inspect it before retrying",
            )
        if not oauth_configured():
            raise HTTPException(
                status_code=503, detail="YouTube upload authorization is not configured"
            )
        if payload.scheduled_at:
            if payload.scheduled_at <= datetime.now(UTC):
                raise HTTPException(
                    status_code=422, detail="Publication time must be in the future"
                )
            if not settings.YOUTUBE_API_AUDIT_APPROVED:
                raise HTTPException(
                    status_code=503,
                    detail="Public YouTube scheduling requires provider API approval; private test uploads remain available",
                )
        item = LocalYouTubeUpload(user_id=user.id, **payload.model_dump(), status="initiating")
        await service.credential_for(session, item)
        session.add(item)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="This upload is already being initiated"
            ) from None
        await service.initiate(session, item)
        return {**read_upload(item), **await service.transfer_authorization(session, item)}
    except service.LocalUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeOAuthError as exc:
        if item is not None and item.id is not None and not item.provider_upload_uri_encrypted:
            item.status, item.last_error = (
                "failed",
                "YouTube authorization expired; reconnect the channel",
            )
            await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{upload_id}/transfer")
async def transfer(
    upload_id: int,
    response: Response,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    no_store(response)
    try:
        return await service.transfer_authorization(session, await owned(session, upload_id, user))
    except service.LocalUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{upload_id}/verify")
async def verify(
    upload_id: int,
    payload: VerifyRequest,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await owned(session, upload_id, user)
    try:
        await service.verify(session, item, payload.remote_video_id)
    except service.LocalUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return read_upload(item)


class RescheduleRequest(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def future_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None or value <= datetime.now(UTC):
            raise ValueError("Choose a future release time with a timezone")
        return value.astimezone(UTC)


@router.put("/{upload_id}/schedule")
async def reschedule_upload(
    response: Response,
    upload_id: int,
    payload: RescheduleRequest,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    no_store(response)
    item = await owned(session, upload_id, user)
    if not settings.YOUTUBE_API_AUDIT_APPROVED:
        raise HTTPException(
            status_code=503, detail="YouTube API audit approval is required for public releases"
        )
    try:
        await service.reschedule(session, item, payload.scheduled_at)
    except service.LocalUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except (httpx.HTTPError, ValueError, YouTubeOAuthError) as error:
        raise HTTPException(
            status_code=502,
            detail="Could not verify the YouTube schedule update; retry the same video",
        ) from error
    return read_upload(item)


class ClearProfileScheduleRequest(BaseModel):
    creator_profile_id: str = Field(min_length=1, max_length=80)


@router.post("/clear-schedule")
async def clear_profile_schedule(
    payload: ClearProfileScheduleRequest,
    response: Response,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    no_store(response)
    uploads = (
        (
            await session.execute(
                select(LocalYouTubeUpload).where(
                    LocalYouTubeUpload.user_id == user.id,
                    LocalYouTubeUpload.creator_profile_id == payload.creator_profile_id,
                    LocalYouTubeUpload.status.in_(["scheduled", "processing"]),
                    LocalYouTubeUpload.scheduled_at > datetime.now(UTC),
                    LocalYouTubeUpload.remote_video_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    cleared = []
    errors = []
    for item in uploads:
        try:
            await service.unschedule(session, item)
            cleared.append(item.id)
        except (service.LocalUploadError, httpx.HTTPError, ValueError, YouTubeOAuthError):
            errors.append(
                {
                    "upload_id": item.id,
                    "message": "Could not confirm release cancellation. Refresh and retry.",
                }
            )
    unfinished = (
        (
            await session.execute(
                select(LocalYouTubeUpload).where(
                    LocalYouTubeUpload.user_id == user.id,
                    LocalYouTubeUpload.creator_profile_id == payload.creator_profile_id,
                    LocalYouTubeUpload.scheduled_at > datetime.now(UTC),
                    or_(
                        LocalYouTubeUpload.status.in_(["initiating", "uploading", "unknown"]),
                        and_(
                            LocalYouTubeUpload.status == "processing",
                            LocalYouTubeUpload.remote_video_id.is_(None),
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for item in unfinished:
        errors.append(
            {
                "upload_id": item.id,
                "message": "Upload is in progress or needs reconciliation before cancelling its release.",
            }
        )
    jobs = (
        (
            await session.execute(
                select(PublishJob).where(
                    PublishJob.user_id == user.id,
                    PublishJob.creator_profile_id == payload.creator_profile_id,
                    PublishJob.status == "pending",
                    PublishJob.attempt_count == 0,
                    PublishJob.lease_token.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    cancelled = []
    for job in jobs:
        changed = await session.execute(
            update(PublishJob)
            .where(
                PublishJob.id == job.id,
                PublishJob.status == "pending",
                PublishJob.attempt_count == 0,
                PublishJob.lease_token.is_(None),
            )
            .values(status="cancelled")
            .execution_options(synchronize_session=False)
        )
        if getattr(changed, "rowcount", 0) == 1:
            cancelled.append(job.id)
        else:
            errors.append(
                {
                    "job_id": job.id,
                    "message": "Publishing started; cancellation could not be confirmed.",
                }
            )
    blocked = (
        (
            await session.execute(
                select(PublishJob).where(
                    PublishJob.user_id == user.id,
                    PublishJob.creator_profile_id == payload.creator_profile_id,
                    or_(
                        PublishJob.status.in_(["queued", "publishing", "partial", "reconcile"]),
                        and_(
                            PublishJob.status == "pending",
                            or_(PublishJob.attempt_count > 0, PublishJob.lease_token.is_not(None)),
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for job in blocked:
        errors.append(
            {"job_id": job.id, "message": "Publishing is in progress or needs reconciliation."}
        )
    await session.commit()
    return {"cleared_upload_ids": cleared, "cancelled_job_ids": cancelled, "errors": errors}
