from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


async def store_video_source(video_id: int, file: UploadFile) -> tuple[Path, str, int]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("Unsupported video file extension")

    directory = Path(settings.SOURCE_MEDIA_STORAGE_DIR) / str(video_id)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".{uuid4().hex}.tmp"
    final = directory / f"source{suffix}"
    maximum = settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise ValueError("Video exceeds configured size limit")
                output.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise ValueError("Uploaded video is empty")
        temporary.replace(final)
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()

    return final, digest.hexdigest(), size
