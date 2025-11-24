from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

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


def ensure_media_storage(subdir: str) -> Path:
    root = Path(settings.MEDIA_STORAGE_DIR) / subdir
    root.mkdir(parents=True, exist_ok=True)
    return root


class StoredAsset:
    def __init__(self, *, asset_url: str, checksum: str, size_bytes: int, content_type: str):
        self.asset_url = asset_url
        self.checksum = checksum
        self.size_bytes = size_bytes
        self.content_type = content_type


async def store_uploaded_asset(file: UploadFile, *, max_bytes: int) -> StoredAsset:
    """Persist an uploaded asset under MEDIA_STORAGE_DIR/uploads/assets."""

    assets_dir = ensure_media_storage("uploads/assets")
    suffix = Path(file.filename or "").suffix or ".bin"
    target = assets_dir / f"{Path(file.filename or 'asset').stem}_{uuid4().hex}{suffix}"

    hasher = hashlib.sha256()
    total = 0
    with target.open("wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                target.unlink(missing_ok=True)
                raise ValueError("Asset exceeds configured size limit")
            hasher.update(chunk)
            buffer.write(chunk)
    await file.close()

    if total == 0:
        target.unlink(missing_ok=True)
        raise ValueError("Uploaded asset is empty")

    checksum = hasher.hexdigest()
    asset_url = str(target)
    content_type = file.content_type or "application/octet-stream"
    return StoredAsset(
        asset_url=asset_url,
        checksum=checksum,
        size_bytes=total,
        content_type=content_type,
    )
