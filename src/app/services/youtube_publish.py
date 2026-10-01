"""Real YouTube resumable upload adapter with persisted unknown-outcome state."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PublishJob, PublishJobStatus, YouTubeCredential
from app.services.publish_execution import (
    IndeterminatePublishError,
    PermanentPublishError,
    ProviderReceipt,
    SafeRetryError,
    VerifiedTarget,
)
from app.services.youtube_oauth import (
    YouTubeOAuthError,
    access_token_for,
    decrypt_secret,
    encrypt_secret,
)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=30.0))


def _valid_session_uri(uri: str) -> bool:
    parsed = urlsplit(uri)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.googleapis.com"
        and parsed.path.startswith("/upload/youtube/v3/videos")
    )


async def _asset_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as source:
        while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
            yield chunk


class YouTubePublishAdapter:
    guarantees_idempotent_publish = False
    supports_safe_initial_attempt = True

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def _credential(self, user_id: int) -> YouTubeCredential:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(YouTubeCredential).where(YouTubeCredential.user_id == user_id)
                )
            ).scalar_one_or_none()
            if row is None or row.token_encryption_version != 1 or not row.channel_id:
                raise PermanentPublishError("YOUTUBE_NOT_CONNECTED", "Connect a YouTube channel")
            return row

    async def resolve_target(self, user_id: int, account_ref: str) -> VerifiedTarget:
        credential = await self._credential(user_id)
        expected = f"youtube:{credential.channel_id}"
        if account_ref != expected:
            raise PermanentPublishError(
                "TARGET_MISMATCH", "YouTube channel is not connected to this owner"
            )
        return VerifiedTarget(user_id, "youtube_shorts", account_ref, credential.channel_id or "")

    async def _access_token(self, user_id: int) -> str:
        async with self.session_factory() as session:
            credential = (
                await session.execute(
                    select(YouTubeCredential)
                    .where(YouTubeCredential.user_id == user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if credential is None:
                raise PermanentPublishError("YOUTUBE_NOT_CONNECTED", "YouTube account disconnected")
            try:
                return await access_token_for(session, credential)
            except YouTubeOAuthError as exc:
                raise PermanentPublishError("YOUTUBE_RECONNECT_REQUIRED", str(exc)) from exc

    async def _save_session(self, job: PublishJob, uri: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                update(PublishJob)
                .where(
                    PublishJob.id == job.id,
                    PublishJob.status == PublishJobStatus.PUBLISHING.value,
                    PublishJob.lease_token == job.lease_token,
                )
                .values(provider_upload_uri_encrypted=encrypt_secret(uri))
            )
            await session.commit()
            if int(getattr(result, "rowcount", 0)) != 1:
                raise IndeterminatePublishError("LEASE_LOST", "Upload lease was lost")

    async def _save_remote_id(self, job: PublishJob, video_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(PublishJob)
                .where(PublishJob.id == job.id, PublishJob.lease_token == job.lease_token)
                .values(remote_post_id=video_id)
            )
            await session.commit()

    async def _verify_video(
        self, token: str, video_id: str, target: VerifiedTarget
    ) -> ProviderReceipt:
        async with _client() as client:
            try:
                response = await client.get(
                    VIDEO_URL,
                    params={"part": "snippet,status", "id": video_id},
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.RequestError as exc:
                raise IndeterminatePublishError(
                    "YOUTUBE_VERIFY_UNKNOWN", "Video verification timed out"
                ) from exc
        if response.status_code != HTTPStatus.OK:
            raise IndeterminatePublishError(
                "YOUTUBE_VERIFY_UNKNOWN", "Video verification unavailable"
            )
        items = response.json().get("items", [])
        if len(items) != 1 or items[0].get("id") != video_id:
            raise IndeterminatePublishError(
                "YOUTUBE_VERIFY_UNKNOWN", "Uploaded video is not yet visible"
            )
        item = items[0]
        if item.get("snippet", {}).get("channelId") != target.provider_account_id:
            raise IndeterminatePublishError(
                "YOUTUBE_TARGET_MISMATCH", "Uploaded video belongs to another channel"
            )
        privacy = item.get("status", {}).get("privacyStatus")
        if privacy != "public":
            raise IndeterminatePublishError(
                "YOUTUBE_NOT_PUBLIC", f"Uploaded video is {privacy or 'not yet public'}"
            )
        return ProviderReceipt(
            platform="youtube_shorts",
            provider_account_id=target.provider_account_id,
            remote_post_id=video_id,
            published_at=datetime.now(tz=UTC),
            payload={"video_id": video_id, "privacy_status": privacy},
        )

    async def publish(
        self, job: PublishJob, asset_path: Path, target: VerifiedTarget, idempotency_key: str
    ) -> ProviderReceipt:
        del idempotency_key  # YouTube has no idempotency key; persisted session prevents blind replay.
        assert job.user_id is not None
        token = await self._access_token(job.user_id)
        size = asset_path.stat().st_size
        content_type = "video/mp4" if asset_path.suffix.lower() == ".mp4" else "video/quicktime"
        title = (job.caption or "TV7 clip").splitlines()[0][:100] or "TV7 clip"
        metadata = {
            "snippet": {"title": title, "description": job.caption or ""},
            "status": {"privacyStatus": "public"},
        }
        async with _client() as client:
            try:
                initiated = await client.post(
                    UPLOAD_URL,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Upload-Content-Type": content_type,
                        "X-Upload-Content-Length": str(size),
                    },
                    json=metadata,
                )
            except httpx.RequestError as exc:
                raise SafeRetryError(
                    "YOUTUBE_INIT_UNAVAILABLE", "Upload initiation failed"
                ) from exc
            if initiated.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise SafeRetryError("YOUTUBE_INIT_UNAVAILABLE", "Upload initiation failed")
            if initiated.status_code != HTTPStatus.OK or not (
                uri := initiated.headers.get("Location")
            ):
                raise PermanentPublishError("YOUTUBE_INIT_REJECTED", "YouTube rejected the upload")
            if not _valid_session_uri(uri):
                raise PermanentPublishError(
                    "YOUTUBE_SESSION_INVALID", "YouTube returned an invalid upload URL"
                )
            await self._save_session(job, uri)
            try:
                uploaded = await client.put(
                    uri,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": content_type,
                        "Content-Length": str(size),
                        "Content-Range": f"bytes 0-{size - 1}/{size}",
                    },
                    content=_asset_chunks(asset_path),
                )
            except httpx.RequestError as exc:
                raise IndeterminatePublishError(
                    "YOUTUBE_UPLOAD_UNKNOWN", "Upload outcome is unknown"
                ) from exc
        if uploaded.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
            raise IndeterminatePublishError("YOUTUBE_UPLOAD_UNKNOWN", "Upload needs reconciliation")
        video_id = str(uploaded.json().get("id", ""))
        if not video_id:
            raise IndeterminatePublishError(
                "YOUTUBE_RECEIPT_MISSING", "YouTube did not return a video ID"
            )
        await self._save_remote_id(job, video_id)
        return await self._verify_video(token, video_id, target)

    async def reconcile(self, job: PublishJob, target: VerifiedTarget) -> ProviderReceipt | None:
        assert job.user_id is not None
        token = await self._access_token(job.user_id)
        video_id = job.remote_post_id
        if not video_id and job.provider_upload_uri_encrypted:
            uri = decrypt_secret(job.provider_upload_uri_encrypted)
            if not _valid_session_uri(uri):
                raise PermanentPublishError(
                    "YOUTUBE_SESSION_INVALID", "Stored upload URL is invalid"
                )
            async with _client() as client:
                try:
                    response = await client.put(
                        uri,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Length": "0",
                            "Content-Range": f"bytes */{job.asset_size_bytes}",
                        },
                    )
                except httpx.RequestError:
                    return None
            if response.status_code in {HTTPStatus.OK, HTTPStatus.CREATED}:
                video_id = str(response.json().get("id", ""))
            if not video_id:
                return None
        if not video_id:
            return None
        try:
            return await self._verify_video(token, video_id, target)
        except IndeterminatePublishError:
            return None
