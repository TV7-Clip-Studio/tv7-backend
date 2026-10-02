from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clip,
    PublishJob,
    PublishJobStatus,
    UploadedAsset,
    User,
    Video,
    YouTubeCredential,
)
from app.deps.db import get_session
from app.deps.security import require_jwt_user
from app.repositories.publish_jobs import PublishJobRepository
from app.schemas import (
    PublishJobRead,
    PublishRequest,
    ScheduleDraftRequest,
    ScheduleRescheduleRequest,
)
from app.services.asset_storage import AssetStorageError, asset_available
from app.services.publish_adapters import youtube_publishing_ready

router = APIRouter(dependencies=[Depends(require_jwt_user)])


def _future_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail="scheduled_at must include a timezone")
    normalized = value.astimezone(UTC)
    if normalized <= datetime.now(tz=UTC):
        raise HTTPException(status_code=422, detail="scheduled_at must be in the future")
    return normalized


async def _owned_job(job_id: int, user: User, session: AsyncSession) -> PublishJob:
    job = await session.get(PublishJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Schedule job not found")
    return job


@router.get("/schedule-jobs", response_model=list[PublishJobRead])
async def list_schedule_jobs(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> list[PublishJobRead]:
    jobs = (
        (
            await session.execute(
                select(PublishJob)
                .where(PublishJob.user_id == user.id)
                .order_by(PublishJob.scheduled_at, PublishJob.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [PublishJobRead.model_validate(job, from_attributes=True) for job in jobs]


@router.patch("/schedule-jobs/{job_id}", response_model=PublishJobRead)
async def reschedule_job(
    job_id: int,
    payload: ScheduleRescheduleRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> PublishJobRead:
    await _owned_job(job_id, user, session)
    scheduled_at = _future_utc(payload.scheduled_at)
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job_id,
            PublishJob.user_id == user.id,
            PublishJob.status == PublishJobStatus.PENDING.value,
            PublishJob.attempt_count == 0,
            PublishJob.lease_token.is_(None),
        )
        .values(scheduled_at=scheduled_at, updated_at=datetime.now(tz=UTC))
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Only unattempted pending drafts can be rescheduled"
        )
    await session.commit()
    updated = cast(PublishJob, await session.get(PublishJob, job_id, populate_existing=True))
    return PublishJobRead.model_validate(updated, from_attributes=True)


@router.post("/schedule-jobs/{job_id}/cancel", response_model=PublishJobRead)
async def cancel_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> PublishJobRead:
    job = await _owned_job(job_id, user, session)
    if job.status == PublishJobStatus.CANCELLED.value:
        return PublishJobRead.model_validate(job, from_attributes=True)
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job_id,
            PublishJob.user_id == user.id,
            PublishJob.status == PublishJobStatus.PENDING.value,
            PublishJob.attempt_count == 0,
            PublishJob.lease_token.is_(None),
        )
        .values(status=PublishJobStatus.CANCELLED.value, updated_at=datetime.now(tz=UTC))
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Only unattempted pending drafts can be cancelled"
        )
    await session.commit()
    updated = cast(PublishJob, await session.get(PublishJob, job_id, populate_existing=True))
    return PublishJobRead.model_validate(updated, from_attributes=True)


async def owned_clip(clip_id: int, user: User, session: AsyncSession) -> Clip:
    clip = await session.get(Clip, clip_id)
    video = await session.get(Video, clip.video_id) if clip else None
    if clip is None or video is None or video.requested_by_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")
    return clip


@router.post("/clips/{clip_id}/publish", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
async def publish_clip(
    clip_id: int,
    payload: PublishRequest,  # noqa: ARG001
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> None:
    await owned_clip(clip_id, user, session)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Publishing is unavailable until connected platform adapters are enabled",
    )


@router.post(
    "/clips/{clip_id}/schedule-drafts",
    status_code=status.HTTP_201_CREATED,
    response_model=PublishJobRead,
)
async def create_schedule_draft(
    clip_id: int,
    payload: ScheduleDraftRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> PublishJobRead:
    await owned_clip(clip_id, user, session)
    if payload.scheduled_at.tzinfo is None or payload.scheduled_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="scheduled_at must include a timezone",
        )
    scheduled_at = payload.scheduled_at.astimezone(UTC)
    repo = PublishJobRepository(session)
    existing = await repo.get_by_idempotency_key(user.id, payload.idempotency_key)
    if existing is not None:
        return _matching_draft(existing, clip_id, payload, scheduled_at)
    if scheduled_at <= datetime.now(tz=UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="scheduled_at must be in the future",
        )

    asset = await session.get(UploadedAsset, payload.asset_id)
    if asset is None or asset.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    try:
        available = await asset_available(asset)
    except AssetStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if payload.platform == "youtube_shorts" and youtube_publishing_ready():
        credential = (
            await session.execute(
                select(YouTubeCredential).where(YouTubeCredential.user_id == user.id)
            )
        ).scalar_one_or_none()
        if (
            credential is None
            or credential.token_encryption_version != 1
            or payload.target_account_ref != f"youtube:{credential.channel_id}"
        ):
            raise HTTPException(status_code=404, detail="YouTube target not connected")

    job = PublishJob(
        clip_id=clip_id,
        user_id=user.id,
        asset_id=asset.id,
        platform=payload.platform,
        target_account_ref=payload.target_account_ref,
        caption=payload.caption,
        scheduled_at=scheduled_at,
        idempotency_key=payload.idempotency_key,
        asset_url=f"/api/v1/uploads/assets/{asset.id}",
        asset_checksum=asset.checksum,
        asset_size_bytes=asset.size_bytes,
        status=PublishJobStatus.PENDING.value,
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raced = await repo.get_by_idempotency_key(user.id, payload.idempotency_key)
        if raced is None:
            raise
        return _matching_draft(raced, clip_id, payload, scheduled_at)
    await session.refresh(job)
    return PublishJobRead.model_validate(job, from_attributes=True)


def _matching_draft(
    job: PublishJob,
    clip_id: int,
    payload: ScheduleDraftRequest,
    scheduled_at: datetime,
) -> PublishJobRead:
    job_time = job.scheduled_at
    if job_time is not None and job_time.tzinfo is None:
        job_time = job_time.replace(tzinfo=UTC)
    if (
        job.clip_id != clip_id
        or job.asset_id != payload.asset_id
        or job.platform != payload.platform
        or job.target_account_ref != payload.target_account_ref
        or job.caption != payload.caption
        or job_time != scheduled_at
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key already used for a different draft",
        )
    return PublishJobRead.model_validate(job, from_attributes=True)


@router.get("/clips/{clip_id}/publish", response_model=list[PublishJobRead])
async def list_publish_jobs(
    clip_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> list[PublishJobRead]:
    await owned_clip(clip_id, user, session)
    jobs = await PublishJobRepository(session).list_for_clip_and_user(clip_id, user.id)
    return [PublishJobRead.model_validate(job, from_attributes=True) for job in jobs]
