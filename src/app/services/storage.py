from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def remove_media_path(path: Path) -> None:
    """Remove a media directory if it exists, logging outcomes."""

    try:
        shutil.rmtree(path)
        logger.info("Deleted media directory", extra={"path": str(path)})
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - unexpected filesystem errors
        logger.warning(
            "Failed to delete media directory",
            extra={"path": str(path), "error": str(exc)},
        )


def delete_video_media(video_id: int, clip_ids: list[int]) -> None:
    base = Path(settings.MEDIA_STORAGE_DIR)
    video_dir = base / "videos" / str(video_id)
    remove_media_path(video_dir)

    for clip_id in clip_ids:
        clip_dir = base / "clips" / str(clip_id)
        remove_media_path(clip_dir)
