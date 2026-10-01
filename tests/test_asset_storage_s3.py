from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import UploadFile

from app.core.config import settings
from app.db.models import UploadedAsset
from app.services import asset_storage

pytestmark = pytest.mark.asyncio


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str], str]] = {}

    def upload_file(
        self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, Any]
    ) -> None:  # noqa: N803
        assert bucket == "private-bucket"
        self.objects[key] = (
            Path(filename).read_bytes(),
            ExtraArgs["Metadata"],
            ExtraArgs["ContentType"],
        )

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        assert Bucket == "private-bucket"
        body, metadata, _ = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": metadata}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        assert bucket == "private-bucket"
        Path(filename).write_bytes(self.objects[key][0])

    def get_object(
        self, *, Bucket: str, Key: str, Range: str | None = None
    ) -> dict[str, Any]:  # noqa: N803
        assert Bucket == "private-bucket"
        body = self.objects[Key][0]
        if Range:
            start, end = Range.removeprefix("bytes=").split("-")
            body = body[int(start) : int(end) + 1]
        return {
            "ContentLength": len(body),
            "Body": FakeBody(body),
            **({"ContentRange": "bytes 0-3/8"} if Range else {}),
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        assert Bucket == "private-bucket"
        self.objects.pop(Key, None)


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def iter_chunks(self, *, chunk_size: int) -> list[bytes]:
        return [self.data[i : i + chunk_size] for i in range(0, len(self.data), chunk_size)]

    def close(self) -> None:
        pass


def configure_s3(monkeypatch: pytest.MonkeyPatch, fake: FakeS3) -> None:
    monkeypatch.setattr(settings, "ASSET_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "ASSET_S3_BUCKET", "private-bucket")
    monkeypatch.setattr(settings, "ASSET_S3_REGION", "us-east-1")
    monkeypatch.setattr(settings, "ASSET_S3_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "ASSET_S3_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setattr(asset_storage, "_s3_client", lambda: fake)


async def test_s3_asset_survives_separate_worker_and_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3()
    configure_s3(monkeypatch, fake)
    stored = await asset_storage.store_approved_asset(
        UploadFile(
            filename="clip.mp4", file=BytesIO(b"approved"), headers={"content-type": "video/mp4"}
        ),
        user_id=42,
        max_bytes=20,
    )
    assert stored.location.startswith("s3://private-bucket/tv7/approved-assets/42/")
    assert "clip.mp4" not in stored.location
    asset = UploadedAsset(
        user_id=42,
        storage_backend=stored.backend,
        storage_path=stored.location,
        checksum=stored.checksum,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )
    assert await asset_storage.asset_available(asset)
    async with asset_storage.materialize_asset(asset) as path:
        assert path.read_bytes() == b"approved"
        transient = path
    assert not transient.exists()
    response = await asset_storage.asset_response(asset, "bytes=0-3")
    assert response.status_code == 206
    assert b"".join([part async for part in response.body_iterator]) == b"appr"
    asset.user_id = 7
    with pytest.raises(asset_storage.AssetStorageError, match="owner"):
        await asset_storage.asset_available(asset)
    asset.user_id = 42
    await asset_storage.delete_approved_asset(asset)
    assert fake.objects == {}


async def test_s3_upload_is_bounded_and_checks_integrity(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3()
    configure_s3(monkeypatch, fake)
    with pytest.raises(ValueError, match="size limit"):
        await asset_storage.store_approved_asset(
            UploadFile(filename="clip.mp4", file=BytesIO(b"too large")), user_id=1, max_bytes=2
        )
    assert fake.objects == {}
    stored = await asset_storage.store_approved_asset(
        UploadFile(filename="clip.mp4", file=BytesIO(b"ok")), user_id=1, max_bytes=10
    )
    key = stored.location.split("/", 3)[3]
    body, metadata, content_type = fake.objects[key]
    assert hashlib.sha256(body).hexdigest() == metadata["sha256"] == stored.checksum
    assert metadata["owner-id"] == "1"
    assert content_type == "application/octet-stream"


async def test_production_storage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ASSET_STORAGE_BACKEND", "local")
    with pytest.raises(asset_storage.AssetStorageError, match="require S3"):
        asset_storage.validate_storage_configuration()
    monkeypatch.setattr(settings, "ASSET_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "ASSET_S3_BUCKET", None)
    with pytest.raises(asset_storage.AssetStorageError, match="ASSET_S3_BUCKET"):
        asset_storage.validate_storage_configuration()
