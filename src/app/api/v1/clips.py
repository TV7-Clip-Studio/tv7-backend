from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UploadedAsset, User, Video
from app.deps.db import get_clip_repository, get_session
from app.deps.security import require_jwt_user
from app.repositories.clips import ClipRepository
from app.schemas import ClipRead

router = APIRouter(dependencies=[Depends(require_jwt_user)])


class ClipUpdateRequest(BaseModel):
    asset_url: str | None = None
    asset_checksum: str | None = None
    asset_size_bytes: int | None = None
    render_width: int | None = None
    render_height: int | None = None
    frame_rate: float | None = None
    file_size_bytes: int | None = None
    caption_text: str | None = None
    ready_local_only: bool | None = None

    model_config = ConfigDict(extra="ignore")


@router.patch(
    "/{clip_id}",
    response_model=ClipRead,
    status_code=status.HTTP_200_OK,
)
async def update_clip(
    clip_id: int,
    payload: ClipUpdateRequest,
    clip_repo: ClipRepository = Depends(get_clip_repository),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_jwt_user),
) -> ClipRead:
    clip = await clip_repo.get(clip_id)
    video = await session.get(Video, clip.video_id) if clip else None
    if clip is None or video is None or video.requested_by_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")

    if payload.asset_url is not None:
        prefix = "/api/v1/uploads/assets/"
        if (
            not payload.asset_url.startswith(prefix)
            or not payload.asset_url[len(prefix) :].isdigit()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Use an uploaded asset URL",
            )
        asset = await session.get(UploadedAsset, int(payload.asset_url[len(prefix) :]))
        if asset is None or asset.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        payload = payload.model_copy(
            update={
                "asset_url": f"{prefix}{asset.id}",
                "asset_checksum": asset.checksum,
                "asset_size_bytes": asset.size_bytes,
            }
        )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(clip, field, value)
    await clip_repo.commit()
    await session.refresh(clip)
    return cast(ClipRead, ClipRead.model_validate(clip, from_attributes=True))
