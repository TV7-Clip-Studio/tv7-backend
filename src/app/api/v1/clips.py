from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.deps.db import get_clip_repository
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
) -> ClipRead:
    clip = await clip_repo.get(clip_id)
    if not clip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(clip, field, value)
    await clip_repo.commit()
    return cast(ClipRead, ClipRead.model_validate(clip, from_attributes=True))
