from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024  # 1MB


class UploadError(Exception):
    """Base error for upload persistence failures."""


class UploadTooLargeError(UploadError):
    """Raised when an upload exceeds the configured maximum."""


class UploadPersistenceError(UploadError):
    """Raised when we cannot persist the uploaded file."""


@dataclass(slots=True)
class StoredUpload:
    temp_path: Path
    original_filename: str | None
    file_size_bytes: int
    checksum: str


async def persist_upload_temporarily(upload: UploadFile) -> StoredUpload:
    """
    Stream the uploaded file to disk and return metadata for downstream processing.

    The file is stored under MEDIA_STORAGE_DIR/uploads/tmp/<uuid>.<ext> so workers
    can normalize it asynchronously without exhausting memory.
    """

    max_bytes = settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024
    uploads_dir = Path(settings.MEDIA_STORAGE_DIR) / "uploads" / "tmp"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(upload.filename or "").suffix or ".bin"
    temp_name = f"{uuid4().hex}{suffix}"
    temp_path = uploads_dir / temp_name

    hasher = hashlib.sha256()
    total_bytes = 0

    try:
        with temp_path.open("wb") as buffer:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    with suppress(FileNotFoundError):
                        temp_path.unlink()
                    raise UploadTooLargeError(
                        f"Upload exceeds {settings.UPLOAD_MAX_FILE_SIZE_MB}MB limit"
                    )
                hasher.update(chunk)
                buffer.write(chunk)
    except UploadTooLargeError:
        raise
    except Exception as exc:  # pragma: no cover - unexpected I/O failures
        with suppress(FileNotFoundError):
            temp_path.unlink()
        raise UploadPersistenceError(str(exc)) from exc
    finally:
        await upload.close()

    if total_bytes == 0:
        with suppress(FileNotFoundError):
            temp_path.unlink()
        raise UploadPersistenceError("Uploaded file is empty")

    return StoredUpload(
        temp_path=temp_path,
        original_filename=upload.filename,
        file_size_bytes=total_bytes,
        checksum=hasher.hexdigest(),
    )
