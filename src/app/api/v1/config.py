from fastapi import APIRouter, Depends

from app.core.config import settings
from app.deps.security import require_jwt_user
from app.schemas import ConfigRead
from app.services.publish_adapters import youtube_publishing_ready

router = APIRouter(dependencies=[Depends(require_jwt_user)])


@router.get("", response_model=ConfigRead)
async def get_config() -> ConfigRead:
    """Expose feature flags and limits for Studio."""

    youtube_ready = youtube_publishing_ready()
    return ConfigRead(
        publishing_enabled=youtube_ready,
        scheduling_enabled=youtube_ready,
        asset_upload_required=True,
        allowed_platforms=["youtube_shorts"] if youtube_ready else [],
        max_asset_size_bytes=settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024,
        max_video_duration_seconds=None,
        publish_modes=["backend_publish", "local_only"] if youtube_ready else ["local_only"],
    )
