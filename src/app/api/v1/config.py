from fastapi import APIRouter, Depends

from app.core.config import settings
from app.deps.security import require_jwt_user
from app.schemas import ConfigRead

router = APIRouter(dependencies=[Depends(require_jwt_user)])


@router.get("", response_model=ConfigRead)
async def get_config() -> ConfigRead:
    """Expose feature flags and limits for the Flutter client."""

    return ConfigRead(
        publishing_enabled=True,
        asset_upload_required=True,
        allowed_platforms=["youtube_shorts", "tiktok", "instagram"],
        max_asset_size_bytes=settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024,
        max_video_duration_seconds=None,
        publish_modes=["backend_publish"],
    )
