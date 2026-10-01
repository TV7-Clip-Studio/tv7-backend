from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings
from app.db.models import UploadedAsset


class AssetStorageError(RuntimeError):
    """Private asset storage is unavailable or misconfigured."""


class AssetNotFoundError(AssetStorageError):
    """A stored asset no longer exists."""


@dataclass(frozen=True)
class StoredApprovedAsset:
    backend: str
    location: str
    checksum: str
    size_bytes: int
    content_type: str


def validate_storage_configuration() -> str:
    backend = settings.ASSET_STORAGE_BACKEND.strip().lower()
    production = settings.APP_ENV.strip().lower() in {"prod", "production", "release"}
    if backend not in {"local", "s3"}:
        raise AssetStorageError("ASSET_STORAGE_BACKEND must be local or s3")
    if production and backend != "s3":
        raise AssetStorageError("Production approved assets require S3-compatible private storage")
    if backend == "s3":
        required = {
            "ASSET_S3_BUCKET": settings.ASSET_S3_BUCKET,
            "ASSET_S3_REGION": settings.ASSET_S3_REGION,
            "ASSET_S3_ACCESS_KEY_ID": settings.ASSET_S3_ACCESS_KEY_ID,
            "ASSET_S3_SECRET_ACCESS_KEY": settings.ASSET_S3_SECRET_ACCESS_KEY,
        }
        missing = [name for name, value in required.items() if not value or not value.strip()]
        if missing:
            raise AssetStorageError(f"S3 storage is missing configuration: {', '.join(missing)}")
        if (
            production
            and settings.ASSET_S3_ENDPOINT_URL
            and urlsplit(settings.ASSET_S3_ENDPOINT_URL).scheme != "https"
        ):
            raise AssetStorageError("Production S3 endpoint must use HTTPS")
        _s3_prefix()
    return backend


def _s3_prefix() -> str:
    prefix = settings.ASSET_S3_PREFIX.strip("/")
    if not prefix or any(part in {"", ".", ".."} for part in prefix.split("/")):
        raise AssetStorageError("ASSET_S3_PREFIX must be a safe nonempty key prefix")
    return prefix


def _s3_client() -> Any:
    validate_storage_configuration()
    return boto3.client(
        "s3",
        region_name=settings.ASSET_S3_REGION,
        endpoint_url=settings.ASSET_S3_ENDPOINT_URL,
        aws_access_key_id=settings.ASSET_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.ASSET_S3_SECRET_ACCESS_KEY,
        aws_session_token=settings.ASSET_S3_SESSION_TOKEN,
        config=Config(signature_version="s3v4"),
    )


def _s3_parts(asset: UploadedAsset) -> tuple[str, str]:
    parsed = urlsplit(asset.storage_path)
    bucket = settings.ASSET_S3_BUCKET or ""
    key = parsed.path.lstrip("/")
    expected_prefix = f"{_s3_prefix()}/{asset.user_id}/"
    if parsed.scheme != "s3" or parsed.netloc != bucket or not key.startswith(expected_prefix):
        raise AssetStorageError("Asset storage location does not match its owner and bucket")
    return bucket, key


def _local_path(asset: UploadedAsset) -> Path:
    root = Path(settings.SCHEDULED_ASSET_STORAGE_DIR).resolve()
    path = Path(asset.storage_path).resolve()
    if not path.is_relative_to(root):
        raise AssetStorageError("Asset storage path leaves its private directory")
    return path


def _client_error_missing(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def _temporary_file(prefix: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(descriptor)
    return Path(name)


async def store_approved_asset(
    file: UploadFile, *, user_id: int, max_bytes: int
) -> StoredApprovedAsset:
    backend = validate_storage_configuration()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise ValueError("Unsupported clip format")
    content_type = file.content_type or "application/octet-stream"
    digest = hashlib.sha256()
    total = 0
    temporary = _temporary_file("tv7-approved-", suffix)
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Asset exceeds configured size limit")
                output.write(chunk)
                digest.update(chunk)
        if total == 0:
            raise ValueError("Uploaded asset is empty")
        checksum = digest.hexdigest()
        if backend == "local":
            directory = Path(settings.SCHEDULED_ASSET_STORAGE_DIR) / str(user_id)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{uuid4().hex}{suffix}"
            temporary.replace(target)
            location = str(target.resolve())
        else:
            bucket = settings.ASSET_S3_BUCKET or ""
            key = f"{_s3_prefix()}/{user_id}/{uuid4().hex}{suffix}"
            client = _s3_client()
            try:
                await asyncio.to_thread(
                    client.upload_file,
                    str(temporary),
                    bucket,
                    key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "Metadata": {"sha256": checksum, "owner-id": str(user_id)},
                    },
                )
                head = await asyncio.to_thread(client.head_object, Bucket=bucket, Key=key)
                if (
                    int(head.get("ContentLength", -1)) != total
                    or head.get("Metadata", {}).get("sha256") != checksum
                ):
                    raise AssetStorageError("Uploaded S3 asset failed integrity verification")
            except Exception:
                with suppress(Exception):
                    await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
                raise AssetStorageError("S3 asset upload is unavailable") from None
            location = f"s3://{bucket}/{key}"
        return StoredApprovedAsset(backend, location, checksum, total, content_type)
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()


async def delete_approved_asset(asset: UploadedAsset) -> None:
    if asset.storage_backend == "local":
        _local_path(asset).unlink(missing_ok=True)
    elif asset.storage_backend == "s3":
        bucket, key = _s3_parts(asset)
        await asyncio.to_thread(_s3_client().delete_object, Bucket=bucket, Key=key)


async def asset_available(asset: UploadedAsset) -> bool:
    backend = validate_storage_configuration()
    if asset.storage_backend != backend:
        return False
    if backend == "local":
        path = _local_path(asset)
        return path.is_file() and path.stat().st_size == asset.size_bytes
    bucket, key = _s3_parts(asset)
    try:
        head = await asyncio.to_thread(_s3_client().head_object, Bucket=bucket, Key=key)
    except ClientError as exc:
        if _client_error_missing(exc):
            return False
        raise AssetStorageError("S3 asset metadata is unavailable") from exc
    except Exception as exc:
        raise AssetStorageError("S3 asset metadata is unavailable") from exc
    return (
        int(head.get("ContentLength", -1)) == asset.size_bytes
        and head.get("Metadata", {}).get("sha256") == asset.checksum
    )


def _stream_s3_body(body: Any) -> Iterator[bytes]:
    try:
        yield from body.iter_chunks(chunk_size=1024 * 1024)
    finally:
        body.close()


async def asset_response(
    asset: UploadedAsset, range_header: str | None
) -> FileResponse | StreamingResponse:
    backend = validate_storage_configuration()
    if asset.storage_backend != backend:
        raise AssetNotFoundError("Asset is stored with another backend")
    if backend == "local":
        path = _local_path(asset)
        if not path.is_file():
            raise AssetNotFoundError("Asset does not exist")
        return FileResponse(path, media_type=asset.content_type)
    bucket, key = _s3_parts(asset)
    kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
    if range_header:
        if re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", range_header) is None:
            raise ValueError("Unsupported Range header")
        kwargs["Range"] = range_header
    try:
        result = await asyncio.to_thread(_s3_client().get_object, **kwargs)
    except ClientError as exc:
        if _client_error_missing(exc):
            raise AssetNotFoundError("Asset does not exist") from exc
        if str(exc.response.get("Error", {}).get("Code", "")) == "InvalidRange":
            raise ValueError("Range is outside asset") from exc
        raise AssetStorageError("S3 asset download is unavailable") from exc
    except Exception as exc:
        raise AssetStorageError("S3 asset download is unavailable") from exc
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(result["ContentLength"])}
    if content_range := result.get("ContentRange"):
        headers["Content-Range"] = str(content_range)
    return StreamingResponse(
        _stream_s3_body(result["Body"]),
        status_code=206 if "Content-Range" in headers else 200,
        media_type=asset.content_type,
        headers=headers,
    )


@asynccontextmanager
async def materialize_asset(asset: UploadedAsset) -> AsyncIterator[Path]:
    backend = validate_storage_configuration()
    if asset.storage_backend != backend:
        raise AssetNotFoundError("Asset is stored with another backend")
    if backend == "local":
        path = _local_path(asset)
        if not path.is_file():
            raise AssetNotFoundError("Asset does not exist")
        yield path
        return
    bucket, key = _s3_parts(asset)
    temporary = _temporary_file("tv7-publish-", Path(key).suffix)
    try:
        try:
            await asyncio.to_thread(_s3_client().download_file, bucket, key, str(temporary))
        except ClientError as exc:
            if _client_error_missing(exc):
                raise AssetNotFoundError("Asset does not exist") from exc
            raise AssetStorageError("S3 asset download is unavailable") from exc
        except Exception as exc:
            raise AssetStorageError("S3 asset download is unavailable") from exc
        digest = hashlib.sha256()
        size = 0
        with temporary.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        if size != asset.size_bytes or digest.hexdigest() != asset.checksum:
            raise AssetStorageError("Downloaded S3 asset failed integrity verification")
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)
