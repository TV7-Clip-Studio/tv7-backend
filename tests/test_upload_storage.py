from __future__ import annotations

import io
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from app.services.upload_storage import UploadPersistenceError, persist_upload_temporarily


@pytest.mark.anyio
async def test_persist_upload_temporarily_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.upload_storage.settings.MEDIA_STORAGE_DIR", str(tmp_path))
    upload = UploadFile(filename="demo.mp4", file=io.BytesIO(b"content"))

    stored = await persist_upload_temporarily(upload)

    assert stored.file_size_bytes == len(b"content")
    assert stored.temp_path.exists()
    stored.temp_path.unlink()


@pytest.mark.anyio
async def test_persist_upload_rejects_empty_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.services.upload_storage.settings.MEDIA_STORAGE_DIR", str(tmp_path))
    upload = UploadFile(filename="empty.mp4", file=io.BytesIO(b""))

    with pytest.raises(UploadPersistenceError):
        await persist_upload_temporarily(upload)
