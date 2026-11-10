import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.v1.local_youtube_uploads import ClearProfileScheduleRequest, clear_profile_schedule
from app.core.config import settings
from app.db.models import LocalYouTubeUpload, UploadedAsset, User, YouTubeCredential
from app.services import local_youtube_uploads, youtube_oauth
from app.services.publish_adapters import (
    youtube_local_scheduling_ready,
    youtube_publishing_ready,
)
from app.services.youtube_publish import _valid_session_uri

BASE = "/api/v1/youtube/local-uploads"
URI = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-session"


@pytest.fixture
async def local_target(monkeypatch, db_session, login_credentials):
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", False)
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    channel_id = "UC" + uuid4().hex
    profile = "profile-" + uuid4().hex
    credential = YouTubeCredential(
        user_id=user.id,
        channel_id=channel_id,
        channel_title="Creator channel",
        creator_profile_id=profile,
        access_token=youtube_oauth.encrypt_secret("private-access"),
        refresh_token=youtube_oauth.encrypt_secret("private-refresh"),
        token_encryption_version=1,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(credential)
    await db_session.commit()
    return {
        "creator_profile_id": profile,
        "target_account_ref": f"youtube:{channel_id}",
        "local_clip_id": "local-clip-1",
        "idempotency_key": uuid4().hex,
        "title": "Clip title",
        "description": "Caption",
        "size_bytes": 1024,
        "checksum_sha256": "a" * 64,
        "content_type": "video/mp4",
    }


def provider(  # noqa: PLR0913 -- provider test scenarios
    monkeypatch,
    payload,
    *,
    complete=True,
    privacy="private",
    receipt_id="video123",
    verify_channel=None,
    initiation_calls=None,
):
    channel = payload["target_account_ref"].removeprefix("youtube:")

    def respond(request):
        if request.url.path.endswith("channels"):
            return httpx.Response(200, json={"items": [{"id": channel}]})
        if request.method == "POST":
            if initiation_calls is not None:
                initiation_calls.append(request)
            return httpx.Response(200, headers={"Location": URI})
        if request.method == "PUT":
            assert request.headers["Content-Length"] == "0"
            assert request.headers["Content-Range"] == "bytes */1024"
            return (
                httpx.Response(201, json={"id": receipt_id})
                if complete
                else httpx.Response(308, headers={"Range": "bytes=0-511"})
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": receipt_id,
                        "snippet": {"channelId": verify_channel or channel},
                        "status": {
                            "privacyStatus": privacy,
                            "uploadStatus": "processed",
                            **(
                                {"publishAt": payload["scheduled_at"]}
                                if payload.get("scheduled_at")
                                else {}
                            ),
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )


@pytest.mark.asyncio
async def test_private_upload_metadata_only_and_idempotent(
    async_client, auth_headers, local_target, db_session, monkeypatch
):  # noqa: PLR0913
    calls = []
    provider(monkeypatch, local_target, initiation_calls=calls)
    before = await db_session.scalar(select(func.count()).select_from(UploadedAsset))
    response = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert response.status_code == 200
    created = response.json()
    assert created["status"] == "uploading"
    assert created["upload_headers"]["Authorization"] == "Bearer private-access"
    assert "private-refresh" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    repeated = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert repeated.json()["upload_id"] == created["upload_id"]
    assert len(calls) == 1
    assert '"privacyStatus":"private"' in calls[0].content.decode()
    assert "publishAt" not in calls[0].content.decode()
    verified = await async_client.post(
        f"{BASE}/{created['upload_id']}/verify",
        json={"remote_video_id": "video123"},
        headers=auth_headers,
    )
    assert verified.json()["status"] == "private_uploaded"
    assert verified.json()["remote_video_id"] == "video123"
    assert "upload_url" not in verified.json()
    assert "private-access" not in verified.text
    assert await db_session.scalar(select(func.count()).select_from(UploadedAsset)) == before
    listing = await async_client.get(
        BASE,
        params={"creator_profile_id": local_target["creator_profile_id"]},
        headers=auth_headers,
    )
    assert len(listing.json()) == 1
    assert "upload_headers" not in listing.json()[0]
    conflict = await async_client.post(
        BASE, headers=auth_headers, json={**local_target, "title": "Changed title"}
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_new_browser_key_reuses_identical_render(
    async_client, auth_headers, local_target, monkeypatch, completed
):  # noqa: PLR0913
    calls = []
    provider(monkeypatch, local_target, initiation_calls=calls)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    if completed:
        verified = await async_client.post(
            f"{BASE}/{created['upload_id']}/verify",
            headers=auth_headers,
            json={"remote_video_id": "video123"},
        )
        assert verified.json()["status"] == "private_uploaded"
    replay = await async_client.post(
        BASE,
        headers=auth_headers,
        json={
            **local_target,
            "idempotency_key": uuid4().hex,
            "local_clip_id": "another-browser-clip",
            "title": "Edited local title",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["upload_id"] == created["upload_id"]
    assert replay.json()["title"] == "Clip title"
    assert replay.json()["idempotency_key"] == local_target["idempotency_key"]
    assert len(calls) == 1
    assert ("upload_url" in replay.json()) is not completed
    # A changed render is a distinct asset and must not reuse the old video.
    changed = await async_client.post(
        BASE,
        headers=auth_headers,
        json={**local_target, "idempotency_key": uuid4().hex, "checksum_sha256": "b" * 64},
    )
    assert changed.status_code == 200
    assert changed.json()["upload_id"] != created["upload_id"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_schedule_gates_and_provider_confirmed_publish_time(
    async_client, auth_headers, local_target, monkeypatch
):
    local_target["scheduled_at"] = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    denied = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert denied.status_code == 503
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    calls = []
    provider(monkeypatch, local_target, initiation_calls=calls)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    assert "publishAt" in calls[0].content.decode()
    verified = await async_client.post(
        f"{BASE}/{created['upload_id']}/verify", json={}, headers=auth_headers
    )
    assert verified.json()["status"] == "scheduled"
    assert verified.json()["scheduled_at"] == local_target["scheduled_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["another-channel", "client-fake-id", "public-instead"])
async def test_receipt_cannot_claim_wrong_target_or_privacy(
    async_client, auth_headers, local_target, monkeypatch, problem
):
    provider(
        monkeypatch,
        local_target,
        verify_channel="UCwrong" if problem == "another-channel" else None,
        privacy="public" if problem == "public-instead" else "private",
    )
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    response = await async_client.post(
        f"{BASE}/{created['upload_id']}/verify",
        json={"remote_video_id": "fake" if problem == "client-fake-id" else "video123"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    saved = await async_client.get(f"{BASE}/{created['upload_id']}", headers=auth_headers)
    assert saved.json()["status"] == "unknown"
    assert saved.json()["remote_video_id"] == "video123"


@pytest.mark.asyncio
async def test_incomplete_upload_preserves_session_for_resume(
    async_client, auth_headers, local_target, monkeypatch
):
    calls = []
    provider(monkeypatch, local_target, complete=False, initiation_calls=calls)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    result = await async_client.post(
        f"{BASE}/{created['upload_id']}/verify", json={}, headers=auth_headers
    )
    assert result.status_code == 409
    transfer = await async_client.post(
        f"{BASE}/{created['upload_id']}/transfer", headers=auth_headers
    )
    assert transfer.json()["upload_url"] == URI
    assert transfer.json()["status"] == "uploading"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_profile_and_owner_isolation(
    async_client, auth_headers, local_target, monkeypatch, db_session
):  # noqa: PLR0913
    wrong_profile = await async_client.post(
        BASE, headers=auth_headers, json={**local_target, "creator_profile_id": "wrong-profile"}
    )
    assert wrong_profile.status_code == 404
    provider(monkeypatch, local_target)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    item = await db_session.get(LocalYouTubeUpload, created["upload_id"])
    user = User(email=uuid4().hex + "@example.com", full_name="Other", password_hash="hash")
    db_session.add(user)
    await db_session.commit()
    item.user_id = user.id
    await db_session.commit()
    for suffix in ("", "/transfer", "/verify"):
        result = (
            await async_client.get(f"{BASE}/{item.id}", headers=auth_headers)
            if not suffix
            else await async_client.post(f"{BASE}/{item.id}{suffix}", headers=auth_headers, json={})
        )
        assert result.status_code == 404


@pytest.mark.asyncio
async def test_initiation_timeout_is_durable_and_never_restarted(
    async_client, auth_headers, local_target, monkeypatch
):
    calls = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [{"id": local_target["target_account_ref"].removeprefix("youtube:")}]
                },
            )
        calls.append(request)
        raise httpx.ReadTimeout("lost initiation response", request=request)

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    failed = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert failed.status_code == 503
    repeat = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert repeat.status_code == 409
    assert len(calls) == 1
    rows = (
        await async_client.get(
            BASE,
            params={"creator_profile_id": local_target["creator_profile_id"]},
            headers=auth_headers,
        )
    ).json()
    assert rows[0]["status"] == "unknown"
    assert rows[0]["remote_video_id"] is None


@pytest.mark.asyncio
async def test_provider_channel_checked_before_initiation(
    async_client, auth_headers, local_target, monkeypatch
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"items": [{"id": "not-the-selected-channel"}]})

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    response = await async_client.post(BASE, headers=auth_headers, json=local_target)
    assert response.status_code == 409
    assert len(calls) == 1
    rows = (
        await async_client.get(
            BASE,
            params={"creator_profile_id": local_target["creator_profile_id"]},
            headers=auth_headers,
        )
    ).json()
    assert rows[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_schedule_naive_and_past_rejected(
    async_client, auth_headers, local_target, monkeypatch
):
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    for value in (datetime.now().isoformat(), (datetime.now(UTC) - timedelta(days=1)).isoformat()):
        response = await async_client.post(
            BASE, headers=auth_headers, json={**local_target, "scheduled_at": value}
        )
        assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["success", "processing", "wrong_schedule", "invalid_session", "verify_timeout"]
)
async def test_provider_reconciliation_boundaries_without_database_network(monkeypatch, mode):
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    scheduled = datetime.now(UTC) + timedelta(days=10)
    item = LocalYouTubeUpload(
        id=900,
        user_id=1,
        creator_profile_id="profile",
        target_account_ref="youtube:UCtarget",
        local_clip_id="clip",
        idempotency_key="key",
        title="Title",
        description="Caption",
        content_type="video/mp4",
        size_bytes=1024,
        checksum_sha256="b" * 64,
        status="initiating",
        scheduled_at=scheduled,
    )
    session = AsyncMock()
    monkeypatch.setattr(
        local_youtube_uploads,
        "credential_for",
        AsyncMock(return_value=SimpleNamespace(channel_id="UCtarget")),
    )
    monkeypatch.setattr(
        local_youtube_uploads, "access_token_for", AsyncMock(return_value="temporary-access")
    )

    def respond(request):
        if request.url.path.endswith("channels"):
            return httpx.Response(200, json={"items": [{"id": "UCtarget"}]})
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": (
                        "https://attacker.invalid/upload" if mode == "invalid_session" else URI
                    )
                },
            )
        if request.method == "PUT":
            return httpx.Response(201, json={"id": "authoritative-id"})
        if mode == "verify_timeout":
            raise httpx.ReadTimeout("provider delayed", request=request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "authoritative-id",
                        "snippet": {"channelId": "UCtarget"},
                        "status": {
                            "privacyStatus": "private",
                            "uploadStatus": "uploaded" if mode == "processing" else "processed",
                            "publishAt": (
                                scheduled + timedelta(hours=1)
                                if mode == "wrong_schedule"
                                else scheduled
                            ).isoformat(),
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    if mode == "invalid_session":
        with pytest.raises(local_youtube_uploads.LocalUploadError, match="rejected"):
            await local_youtube_uploads.initiate(session, item)
        assert item.status == "failed"
        return
    await local_youtube_uploads.initiate(session, item)
    assert item.status == "uploading"
    capability = await local_youtube_uploads.transfer_authorization(session, item)
    assert capability["upload_headers"]["Authorization"] == "Bearer temporary-access"
    if mode in {"success", "processing"}:
        await local_youtube_uploads.verify(session, item, "authoritative-id")
        assert item.status == ("processing" if mode == "processing" else "scheduled")
        assert (item.verified_at is not None) is (mode != "processing")
    else:
        with pytest.raises(local_youtube_uploads.LocalUploadError):
            await local_youtube_uploads.verify(session, item, "authoritative-id")
        assert item.status == "unknown"
        assert item.remote_video_id == "authoritative-id"


@pytest.mark.parametrize(
    "uri",
    [
        "https://www.googleapis.com/upload/youtube/v3/videos-evil?upload_id=x",
        "https://user@www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
        "https://www.googleapis.com:443/upload/youtube/v3/videos?upload_id=x",
        "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x#fragment",
        "https://www.googleapis.com/upload/youtube/v3/videos",
        "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=one&upload_id=two",
    ],
)
def test_transfer_capability_host_and_session_strict(uri):
    assert _valid_session_uri(uri) is False


def test_safe_provider_quota_error_has_actionable_message():
    result = local_youtube_uploads.provider_error(
        httpx.Response(
            403,
            json={
                "error": {
                    "errors": [{"reason": "quotaExceeded"}],
                    "message": "sensitive provider detail",
                }
            },
        )
    )
    assert "quota" in result
    assert "sensitive" not in result


@pytest.mark.asyncio
async def test_reschedule_existing_video_and_audit_gate(
    async_client, auth_headers, local_target, monkeypatch
):
    provider(monkeypatch, local_target)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    upload_id = created["upload_id"]
    await async_client.post(
        f"{BASE}/{upload_id}/verify",
        headers=auth_headers,
        json={"remote_video_id": "video123"},
    )
    release = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    endpoint = f"{BASE}/{upload_id}/schedule"
    denied = await async_client.put(endpoint, headers=auth_headers, json={"scheduled_at": release})
    assert denied.status_code == 503
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    updates = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video123",
                            "snippet": {
                                "channelId": local_target["target_account_ref"].removeprefix(
                                    "youtube:"
                                )
                            },
                            "status": {"privacyStatus": "private", "uploadStatus": "processed"},
                        }
                    ]
                },
            )
        assert request.method == "PUT"

        body = json.loads(request.content)
        updates.append(body)
        assert body["id"] == "video123"
        assert "uploadStatus" not in body["status"]
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    changed = await async_client.put(endpoint, headers=auth_headers, json={"scheduled_at": release})
    assert changed.status_code == 200
    assert changed.json()["status"] == "scheduled"
    assert changed.json()["remote_video_id"] == "video123"
    assert len(updates) == 1
    invalid = await async_client.put(
        endpoint, headers=auth_headers, json={"scheduled_at": "2020-01-01T00:00:00Z"}
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_database_rejects_concurrent_duplicate_render(
    async_client, auth_headers, local_target, db_session, monkeypatch
):
    provider(monkeypatch, local_target)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    original = await db_session.get(LocalYouTubeUpload, created["upload_id"])
    duplicate = LocalYouTubeUpload(
        user_id=original.user_id,
        **{**local_target, "idempotency_key": uuid4().hex},
        status="initiating",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(LocalYouTubeUpload)
            .where(LocalYouTubeUpload.creator_profile_id == local_target["creator_profile_id"])
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_status", ["scheduled", "processing"])
async def test_clear_schedule_keeps_video_private_and_is_profile_scoped(  # noqa: PLR0913 -- independent provider scenarios and fixtures
    async_client, auth_headers, local_target, db_session, monkeypatch, upload_status
):
    provider(monkeypatch, local_target)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    item = await db_session.get(LocalYouTubeUpload, created["upload_id"])
    item.remote_video_id = "video123"
    item.status = upload_status
    item.scheduled_at = datetime.now(UTC) + timedelta(days=30)
    await db_session.commit()
    updates = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "video123",
                            "snippet": {
                                "channelId": local_target["target_account_ref"].removeprefix(
                                    "youtube:"
                                )
                            },
                            "status": {
                                "privacyStatus": "private",
                                "publishAt": item.scheduled_at.isoformat(),
                                "uploadStatus": "processed",
                            },
                        }
                    ]
                },
            )
        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body["status"] == {"privacyStatus": "private"}
        updates.append(body)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    other = await async_client.post(
        f"{BASE}/clear-schedule", headers=auth_headers, json={"creator_profile_id": "other-profile"}
    )
    assert other.status_code == 200
    assert other.json()["cleared_upload_ids"] == []
    assert updates == []
    cleared = await async_client.post(
        f"{BASE}/clear-schedule",
        headers=auth_headers,
        json={"creator_profile_id": local_target["creator_profile_id"]},
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared_upload_ids"] == [created["upload_id"]]
    assert cleared.json()["errors"] == []
    await db_session.refresh(item)
    assert item.remote_video_id == "video123"
    assert item.status == "private_uploaded"
    assert item.scheduled_at is None
    again = await async_client.post(
        f"{BASE}/clear-schedule",
        headers=auth_headers,
        json={"creator_profile_id": local_target["creator_profile_id"]},
    )
    assert again.json()["cleared_upload_ids"] == []
    assert len(updates) == 1


@pytest.mark.asyncio
async def test_clear_schedule_retains_receipt_when_provider_does_not_confirm(
    async_client, auth_headers, local_target, db_session, monkeypatch
):
    provider(monkeypatch, local_target)
    created = (await async_client.post(BASE, headers=auth_headers, json=local_target)).json()
    item = await db_session.get(LocalYouTubeUpload, created["upload_id"])
    item.remote_video_id = "video123"
    item.status = "scheduled"
    item.scheduled_at = datetime.now(UTC) + timedelta(days=30)
    await db_session.commit()

    def respond(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "channelId": local_target["target_account_ref"].removeprefix(
                                    "youtube:"
                                )
                            },
                            "status": {"privacyStatus": "private"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "video123",
                "status": {"privacyStatus": "private", "publishAt": item.scheduled_at.isoformat()},
            },
        )

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = await async_client.post(
        f"{BASE}/clear-schedule",
        headers=auth_headers,
        json={"creator_profile_id": local_target["creator_profile_id"]},
    )
    assert result.status_code == 200
    assert result.json()["errors"]
    await db_session.refresh(item)
    assert item.status == "scheduled"
    assert item.scheduled_at is not None


def test_direct_scheduling_does_not_require_cloud_worker(monkeypatch):

    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    monkeypatch.setattr(settings, "YOUTUBE_PUBLISH_ENABLED", False)
    assert youtube_local_scheduling_ready()
    assert not youtube_publishing_ready()


@pytest.mark.asyncio
async def test_clear_direct_endpoint_reports_inflight_upload(
    db_session, login_credentials, local_target
):
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    item = LocalYouTubeUpload(
        user_id=user.id,
        **local_target,
        status="uploading",
        scheduled_at=datetime.now(UTC) + timedelta(days=2),
    )
    db_session.add(item)
    await db_session.commit()
    result = await clear_profile_schedule(
        ClearProfileScheduleRequest(creator_profile_id=local_target["creator_profile_id"]),
        Response(),
        user,
        db_session,
    )
    assert result["cleared_upload_ids"] == []
    assert result["errors"][0]["upload_id"] == item.id
    await db_session.refresh(item)
    assert item.status == "uploading"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_rows", [0, 1])
async def test_clear_schedule_worker_race_is_reported(changed_rows):
    responses = [
        [],
        [],
        [SimpleNamespace(id=9)],
        SimpleNamespace(rowcount=changed_rows),
        [SimpleNamespace(id=10)],
    ]

    class Session:
        async def execute(self, _statement):
            value = responses.pop(0)
            if isinstance(value, list):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: value))
            return value

        async def commit(self):
            pass

    result = await clear_profile_schedule(
        ClearProfileScheduleRequest(creator_profile_id="profile"),
        Response(),
        SimpleNamespace(id=1),
        Session(),
    )
    assert result["cancelled_job_ids"] == ([9] if changed_rows else [])
    assert any(error.get("job_id") == 10 for error in result["errors"])
    assert any(error.get("job_id") == 9 for error in result["errors"]) == (changed_rows == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "privacy,channel", [("private", "channel"), ("public", "channel"), ("private", "other")]
)
async def test_unschedule_rejects_public_or_foreign_videos(monkeypatch, privacy, channel):
    monkeypatch.setattr(
        local_youtube_uploads,
        "credential_for",
        AsyncMock(return_value=SimpleNamespace(channel_id="channel")),
    )
    monkeypatch.setattr(
        local_youtube_uploads, "access_token_for", AsyncMock(return_value="test-token")
    )
    updates = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {"channelId": channel},
                            "status": {
                                "privacyStatus": privacy,
                                "license": "youtube",
                                "publishAt": "2099-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        body = json.loads(request.content)
        updates.append(body)
        assert "publishAt" not in body["status"]
        assert body["status"]["license"] == "youtube"
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        local_youtube_uploads,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    session = SimpleNamespace(commit=AsyncMock())
    upload = SimpleNamespace(
        remote_video_id="video123",
        status="scheduled",
        scheduled_at=datetime.now(UTC),
        last_error="old",
    )
    if privacy != "private" or channel != "channel":
        with pytest.raises(local_youtube_uploads.LocalUploadError):
            await local_youtube_uploads.unschedule(session, upload)
        assert updates == []
        session.commit.assert_not_awaited()
    else:
        await local_youtube_uploads.unschedule(session, upload)
        assert upload.status == "private_uploaded"
        assert upload.scheduled_at is None
        session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unschedule_requires_a_verified_provider_video(monkeypatch):
    monkeypatch.setattr(
        local_youtube_uploads,
        "credential_for",
        AsyncMock(return_value=SimpleNamespace(channel_id="channel")),
    )
    session = SimpleNamespace(commit=AsyncMock())
    with pytest.raises(local_youtube_uploads.LocalUploadError, match="verified scheduled"):
        await local_youtube_uploads.unschedule(
            session, SimpleNamespace(remote_video_id=None, status="uploading")
        )
    session.commit.assert_not_awaited()
