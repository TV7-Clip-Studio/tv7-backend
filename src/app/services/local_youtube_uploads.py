"""Metadata-only local-to-provider upload authorization and reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LocalYouTubeUpload, YouTubeCredential
from app.services.youtube_oauth import access_token_for, decrypt_secret, encrypt_secret
from app.services.youtube_publish import UPLOAD_URL, VIDEO_URL, _valid_session_uri


class LocalUploadError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=False)


async def credential_for(session: AsyncSession, upload: LocalYouTubeUpload) -> YouTubeCredential:
    credential = (
        await session.execute(
            select(YouTubeCredential).where(
                YouTubeCredential.user_id == upload.user_id,
                YouTubeCredential.channel_id == upload.target_account_ref.removeprefix("youtube:"),
            )
        )
    ).scalar_one_or_none()
    if (
        credential is None
        or credential.token_encryption_version != 1
        or credential.creator_profile_id != upload.creator_profile_id
        or upload.target_account_ref != f"youtube:{credential.channel_id}"
    ):
        raise LocalUploadError(
            "YouTube account is disconnected or belongs to another creator profile", 404
        )
    return credential


def provider_error(response: httpx.Response) -> str:
    messages = {
        "quotaExceeded": "YouTube API quota exceeded; retry after the quota resets",
        "dailyLimitExceeded": "YouTube daily API limit reached",
        "uploadLimitExceeded": "This YouTube channel has reached its upload limit",
        "insufficientPermissions": "YouTube upload permission is missing; reconnect the channel",
        "forbidden": "YouTube refused this operation; check channel permissions",
        "youtubeSignupRequired": "The selected Google account needs a YouTube channel",
        "invalidPublishAt": "YouTube rejected the publication time",
        "invalidTitle": "YouTube rejected the video title",
        "invalidDescription": "YouTube rejected the video description",
    }
    try:
        reason = response.json().get("error", {}).get("errors", [{}])[0].get("reason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        reason = None
    return messages.get(
        reason,
        "YouTube rejected upload initiation; check account permissions and API configuration",
    )


async def initiate(session: AsyncSession, upload: LocalYouTubeUpload) -> None:
    credential = await credential_for(session, upload)
    token = await access_token_for(session, credential)
    metadata: dict[str, dict[str, str]] = {
        "snippet": {"title": upload.title, "description": upload.description},
        "status": {"privacyStatus": "private"},
    }
    if upload.scheduled_at:
        metadata["status"]["publishAt"] = utc(upload.scheduled_at).isoformat()
    try:
        async with _client() as client:
            # Reconfirm token identity before any provider upload session is created.
            identity = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id", "mine": "true"},
                headers={"Authorization": f"Bearer {token}"},
            )
            channels = (
                identity.json().get("items", []) if identity.status_code == HTTPStatus.OK else []
            )
            if len(channels) != 1 or channels[0].get("id") != credential.channel_id:
                raise LocalUploadError("YouTube token does not identify the selected channel", 409)
            response = await client.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Upload-Content-Length": str(upload.size_bytes),
                    "X-Upload-Content-Type": upload.content_type,
                },
                json=metadata,
            )
    except LocalUploadError as exc:
        upload.status, upload.last_error = "failed", str(exc)
        await session.commit()
        raise
    except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
        upload.status, upload.last_error = (
            "unknown",
            "Upload initiation outcome unknown; do not start another upload automatically",
        )
        await session.commit()
        raise LocalUploadError(upload.last_error, 503) from exc
    if (
        response.status_code != HTTPStatus.OK
        or not (uri := response.headers.get("Location"))
        or not _valid_session_uri(uri)
    ):
        upload.status, upload.last_error = "failed", provider_error(response)
        await session.commit()
        raise LocalUploadError(upload.last_error, 502)
    upload.provider_upload_uri_encrypted = encrypt_secret(uri)
    upload.status, upload.last_error = "uploading", None
    await session.commit()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def transfer_authorization(session: AsyncSession, upload: LocalYouTubeUpload) -> dict:
    if upload.status not in {"uploading", "unknown"} or not upload.provider_upload_uri_encrypted:
        raise LocalUploadError(
            "This upload has no active resumable session; inspect its status before trying again"
        )
    credential = await credential_for(session, upload)
    token = await access_token_for(session, credential)
    uri = decrypt_secret(upload.provider_upload_uri_encrypted)
    if not _valid_session_uri(uri):
        raise LocalUploadError("Stored YouTube resumable session is invalid")
    return {
        "upload_id": upload.id,
        "status": upload.status,
        "upload_url": uri,
        "upload_headers": {"Authorization": f"Bearer {token}", "Content-Type": upload.content_type},
        "size_bytes": upload.size_bytes,
        "checksum_sha256": upload.checksum_sha256,
    }


async def verify(  # noqa: PLR0912, PLR0915 -- reconciliation validates each provider boundary
    session: AsyncSession, upload: LocalYouTubeUpload, claimed_video_id: str | None
) -> None:
    credential = await credential_for(session, upload)
    token = await access_token_for(session, credential)
    if not upload.provider_upload_uri_encrypted:
        raise LocalUploadError("No resumable session exists to verify")
    uri = decrypt_secret(upload.provider_upload_uri_encrypted)
    if not _valid_session_uri(uri):
        raise LocalUploadError("Stored YouTube resumable session is invalid")
    try:
        async with _client() as client:
            if not upload.remote_video_id:
                response = await client.put(
                    uri,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Length": "0",
                        "Content-Range": f"bytes */{upload.size_bytes}",
                    },
                )
                if response.status_code == HTTPStatus.PERMANENT_REDIRECT:
                    upload.status, upload.last_error = (
                        "uploading",
                        "Upload incomplete; resume the same session",
                    )
                    await session.commit()
                    raise LocalUploadError(upload.last_error)
                if response.status_code not in {
                    HTTPStatus.OK,
                    HTTPStatus.CREATED,
                } or not response.json().get("id"):
                    raise LocalUploadError(
                        "Upload completion unknown; reconcile this session before retrying"
                    )
                upload.remote_video_id = str(response.json()["id"])
                await session.commit()  # Preserve authoritative receipt before subsequent reads.
            if claimed_video_id and claimed_video_id != upload.remote_video_id:
                raise LocalUploadError(
                    "Client video receipt does not match the saved YouTube session"
                )
            response = await client.get(
                VIDEO_URL,
                params={"part": "snippet,status", "id": upload.remote_video_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            items = (
                response.json().get("items", []) if response.status_code == HTTPStatus.OK else []
            )
            if (
                len(items) != 1
                or items[0].get("id") != upload.remote_video_id
                or items[0].get("snippet", {}).get("channelId") != credential.channel_id
            ):
                raise LocalUploadError("YouTube upload account or completion could not be verified")
            status = items[0].get("status", {})
            if status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
                raise LocalUploadError("YouTube rejected the video after transfer")
            if status.get("privacyStatus") != "private":
                raise LocalUploadError("Expected a private pre-upload; provider privacy differs")
            if upload.scheduled_at:
                provider_time = status.get("publishAt")
                if not provider_time or utc(
                    datetime.fromisoformat(provider_time.replace("Z", "+00:00"))
                ) != utc(upload.scheduled_at):
                    raise LocalUploadError("YouTube did not confirm the requested publication time")
                upload.status = "scheduled"
            else:
                upload.status = "private_uploaded"
    except (httpx.RequestError, ValueError, KeyError, TypeError, AttributeError) as exc:
        upload.status, upload.last_error = (
            "unknown",
            "Provider verification unavailable; reconcile the same upload",
        )
        await session.commit()
        raise LocalUploadError(upload.last_error, 503) from exc
    except LocalUploadError as exc:
        if (
            upload.status != "uploading"
            or upload.last_error != "Upload incomplete; resume the same session"
        ):
            upload.status, upload.last_error = "unknown", str(exc)
            await session.commit()
        raise
    if status.get("uploadStatus") != "processed":
        upload.status, upload.last_error = "processing", None
        await session.commit()
        return
    upload.verified_at, upload.last_error = datetime.now(UTC), None
    await session.commit()


async def reschedule(
    session: AsyncSession, upload: LocalYouTubeUpload, scheduled_at: datetime
) -> None:
    """Update the existing provider video; never create another upload."""
    credential = await credential_for(session, upload)
    if not upload.remote_video_id or upload.status not in {"private_uploaded", "scheduled"}:
        raise LocalUploadError("Verify a completed private upload before scheduling")
    token = await access_token_for(session, credential)
    async with _client() as client:
        response = await client.get(
            VIDEO_URL,
            params={"part": "snippet,status", "id": upload.remote_video_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != HTTPStatus.OK:
            raise LocalUploadError(provider_error(response), 502)
        items = response.json().get("items", [])
        if len(items) != 1 or items[0].get("snippet", {}).get("channelId") != credential.channel_id:
            raise LocalUploadError("YouTube video does not belong to the connected channel")
        status = items[0].get("status", {})
        if status.get("privacyStatus") != "private":
            raise LocalUploadError("Only private, unpublished videos can be scheduled")
        # Read-only status properties must not be sent in videos.update.
        new_status = {
            key: status[key]
            for key in (
                "license",
                "embeddable",
                "publicStatsViewable",
                "selfDeclaredMadeForKids",
                "containsSyntheticMedia",
            )
            if key in status
        }
        new_status.update(privacyStatus="private", publishAt=utc(scheduled_at).isoformat())
        changed = await client.put(
            VIDEO_URL,
            params={"part": "status"},
            headers={"Authorization": f"Bearer {token}"},
            json={"id": upload.remote_video_id, "status": new_status},
        )
        if changed.status_code != HTTPStatus.OK:
            raise LocalUploadError(provider_error(changed), 502)
        changed_video = changed.json()
        confirmed = changed_video.get("status", {})
        if (
            changed_video.get("id") != upload.remote_video_id
            or confirmed.get("privacyStatus") != "private"
            or not confirmed.get("publishAt")
            or datetime.fromisoformat(confirmed["publishAt"].replace("Z", "+00:00"))
            != utc(scheduled_at)
        ):
            raise LocalUploadError("YouTube did not confirm the requested release time", 502)
    upload.scheduled_at = utc(scheduled_at)
    upload.status = "scheduled"
    upload.verified_at = datetime.now(UTC)
    upload.last_error = None
    await session.commit()


async def unschedule(session: AsyncSession, upload: LocalYouTubeUpload) -> None:
    """Remove a future provider release without deleting or publishing its video."""
    credential = await credential_for(session, upload)
    if not upload.remote_video_id or upload.status not in {"scheduled", "processing"}:
        raise LocalUploadError("Only verified scheduled videos can be cleared")
    token = await access_token_for(session, credential)
    async with _client() as client:
        response = await client.get(
            VIDEO_URL,
            params={"part": "snippet,status", "id": upload.remote_video_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != HTTPStatus.OK:
            raise LocalUploadError(provider_error(response), 502)
        items = response.json().get("items", [])
        if len(items) != 1 or items[0].get("snippet", {}).get("channelId") != credential.channel_id:
            raise LocalUploadError("YouTube video does not belong to the connected channel")
        status = items[0].get("status", {})
        if status.get("privacyStatus") != "private":
            raise LocalUploadError("This video is already public; its release cannot be cancelled")
        writable = {
            key: status[key]
            for key in (
                "license",
                "embeddable",
                "publicStatsViewable",
                "selfDeclaredMadeForKids",
                "containsSyntheticMedia",
            )
            if key in status
        }
        writable["privacyStatus"] = "private"
        changed = await client.put(
            VIDEO_URL,
            params={"part": "status"},
            headers={"Authorization": f"Bearer {token}"},
            json={"id": upload.remote_video_id, "status": writable},
        )
        if changed.status_code != HTTPStatus.OK:
            raise LocalUploadError(provider_error(changed), 502)
        result = changed.json()
        if (
            result.get("id") != upload.remote_video_id
            or result.get("status", {}).get("privacyStatus") != "private"
            or result.get("status", {}).get("publishAt")
        ):
            raise LocalUploadError("YouTube did not confirm cancellation of the release", 502)
    upload.scheduled_at = None
    upload.status = "private_uploaded"
    upload.verified_at = datetime.now(UTC)
    upload.last_error = None
    await session.commit()
