from fastapi import APIRouter, Depends, HTTPException, status

from app.db.models import PublishJobStatus
from app.deps.db import (
    get_clip_repository,
    get_publish_job_repository,
    get_video_repository,
)
from app.deps.security import require_jwt_user
from app.repositories.clips import ClipRepository
from app.repositories.publish_jobs import PublishJobRepository
from app.repositories.videos import VideoRepository
from app.schemas import PublishJobRead, PublishRequest

router = APIRouter(dependencies=[Depends(require_jwt_user)])


@router.post(
    "/clips/{clip_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=list[PublishJobRead],
)
async def publish_clip(
    clip_id: int,
    payload: PublishRequest,
    clip_repo: ClipRepository = Depends(get_clip_repository),
    video_repo: VideoRepository = Depends(get_video_repository),
    job_repo: PublishJobRepository = Depends(get_publish_job_repository),
) -> list[PublishJobRead]:
    clip = await clip_repo.get(clip_id)
    if not clip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")

    video = await video_repo.get(clip.video_id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    if not payload.platforms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one platform is required",
        )

    jobs = []
    for platform in payload.platforms:
        job = await job_repo.add_job(
            clip_id=clip_id,
            platform=platform,
            asset_url=payload.asset_url or clip.asset_url or clip.local_path,
            asset_checksum=payload.asset_checksum or clip.asset_checksum,
            asset_size_bytes=payload.asset_size_bytes or clip.asset_size_bytes,
            status=PublishJobStatus.QUEUED,
        )
        jobs.append(job)

    await job_repo.commit()
    return [PublishJobRead.model_validate(job, from_attributes=True) for job in jobs]


@router.get(
    "/clips/{clip_id}/publish",
    response_model=list[PublishJobRead],
)
async def list_publish_jobs(
    clip_id: int,
    clip_repo: ClipRepository = Depends(get_clip_repository),
    job_repo: PublishJobRepository = Depends(get_publish_job_repository),
) -> list[PublishJobRead]:
    clip = await clip_repo.get(clip_id)
    if not clip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")

    jobs = await job_repo.list_for_clip(clip_id)
    return [PublishJobRead.model_validate(job, from_attributes=True) for job in jobs]
