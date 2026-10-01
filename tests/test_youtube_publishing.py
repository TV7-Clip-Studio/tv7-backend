from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import (
    Clip,
    PublishJob,
    PublishJobStatus,
    UploadedAsset,
    User,
    Video,
    YouTubeCredential,
)
from app.services import youtube_oauth, youtube_publish
from app.services.publish_adapters import youtube_publishing_ready
from app.services.publish_execution import PermanentPublishError, reconcile_due_once, run_due_once
from app.services.youtube_publish import YouTubePublishAdapter

pytestmark = pytest.mark.asyncio


async def test_youtube_oauth_and_worker_publish_with_verified_receipt(  # noqa: PLR0913, PLR0915
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "YOUTUBE_PUBLISH_ENABLED", True)
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path / "assets"))

    calls: list[str] = []

    def google(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/token":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "access_token": "google-access-token",
                    "refresh_token": "google-refresh-token",
                    "expires_in": 3600,
                    "scope": f"{youtube_oauth.UPLOAD_SCOPE} {youtube_oauth.READ_SCOPE}",
                },
            )
        if request.url.path == "/youtube/v3/channels":
            assert request.headers["authorization"] == "Bearer google-access-token"
            return httpx.Response(
                200, json={"items": [{"id": "UCowner", "snippet": {"title": "Owner channel"}}]}
            )
        if request.url.path == "/upload/youtube/v3/videos" and request.method == "POST":
            assert request.headers["authorization"] == "Bearer google-access-token"
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=one"
                },
            )
        if request.url.path == "/upload/youtube/v3/videos" and request.method == "PUT":
            assert request.headers["content-range"] == "bytes 0-7/8"
            return httpx.Response(201, json={"id": "YTvideo1"})
        if request.url.path == "/youtube/v3/videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "YTvideo1",
                            "snippet": {"channelId": "UCowner"},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def mock_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(google))

    monkeypatch.setattr(youtube_oauth, "_client", mock_client)
    monkeypatch.setattr(youtube_publish, "_client", mock_client)

    start = await async_client.post("/api/v1/youtube/connect", headers=auth_headers)
    assert start.status_code == 200, start.text
    authorization_url = start.json()["authorization_url"]
    query = parse_qs(urlsplit(authorization_url).query)
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]
    completed = await async_client.get(
        "/api/v1/youtube/callback", params={"state": state, "code": "grant"}
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["channel_id"] == "UCowner"
    replay = await async_client.get(
        "/api/v1/youtube/callback", params={"state": state, "code": "grant"}
    )
    assert replay.status_code == 400
    own_connection = await async_client.get("/api/v1/youtube/connection", headers=auth_headers)
    assert own_connection.json()["connected"] is True
    config = await async_client.get("/api/v1/config", headers=auth_headers)
    assert config.json()["allowed_platforms"] == ["youtube_shorts"]

    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    credential = (
        await db_session.execute(
            select(YouTubeCredential).where(YouTubeCredential.user_id == user.id)
        )
    ).scalar_one()
    assert credential.refresh_token != "google-refresh-token"
    assert youtube_oauth.decrypt_secret(credential.refresh_token) == "google-refresh-token"

    video = Video(
        source_url=f"local://youtube-{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    clip = Clip(video=video, start_sec=0, end_sec=8, status="ready")
    path = tmp_path / "assets" / str(user.id) / "approved.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"approved")
    asset = UploadedAsset(
        user_id=user.id,
        storage_backend="local",
        storage_path=str(path),
        checksum="test",
        size_bytes=8,
        content_type="video/mp4",
    )
    db_session.add_all([video, clip, asset])
    await db_session.flush()
    fractional = await async_client.post(
        f"/api/v1/videos/{video.id}/clips",
        headers=auth_headers,
        json={"start_sec": 0.1, "end_sec": 0.8, "status": "ready"},
    )
    assert fractional.status_code == 201, fractional.text
    assert fractional.json()["start_sec"] == 0.1
    assert fractional.json()["end_sec"] == 0.8
    job = PublishJob(
        clip=clip,
        user_id=user.id,
        asset_id=asset.id,
        platform="youtube_shorts",
        target_account_ref="youtube:UCowner",
        caption="My clip",
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        idempotency_key=f"youtube-{uuid4().hex}",
        asset_size_bytes=8,
        status=PublishJobStatus.PENDING.value,
    )
    db_session.add(job)
    await db_session.commit()
    assert (
        await run_due_once(
            session_factory, {"youtube_shorts": YouTubePublishAdapter(session_factory)}
        )
        == 1
    )
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.COMPLETE.value
    assert job.remote_post_id == "YTvideo1"
    assert job.provider_upload_uri_encrypted is None
    assert any(call.startswith("PUT /upload/youtube/v3/videos") for call in calls)
    with pytest.raises(PermanentPublishError, match="not connected"):
        await YouTubePublishAdapter(session_factory).resolve_target(user.id, "youtube:UCforeign")
    deleted = await async_client.delete("/api/v1/youtube/connection", headers=auth_headers)
    assert deleted.status_code == 204
    disconnected = await async_client.get("/api/v1/youtube/connection", headers=auth_headers)
    assert disconnected.json()["connected"] is False


async def test_uncertain_youtube_upload_reconciles_without_duplicate_post(  # noqa: PLR0913
    monkeypatch: pytest.MonkeyPatch,
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path / "assets"))
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    credential = YouTubeCredential(
        user_id=user.id,
        channel_id="UCreconcile",
        channel_title="Reconcile channel",
        access_token=youtube_oauth.encrypt_secret("access"),
        refresh_token=youtube_oauth.encrypt_secret("refresh"),
        token_encryption_version=1,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    db_session.add(credential)
    video = Video(
        source_url=f"local://reconcile-{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    clip = Clip(video=video, start_sec=0.0, end_sec=0.8, status="ready")
    path = tmp_path / "assets" / str(user.id) / "approved.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"approved")
    asset = UploadedAsset(
        user_id=user.id,
        storage_backend="local",
        storage_path=str(path),
        checksum="test",
        size_bytes=8,
        content_type="video/mp4",
    )
    db_session.add_all([video, clip, asset])
    await db_session.flush()
    job = PublishJob(
        clip=clip,
        user_id=user.id,
        asset_id=asset.id,
        platform="youtube_shorts",
        target_account_ref="youtube:UCreconcile",
        caption="Short",
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        idempotency_key=f"reconcile-{uuid4().hex}",
        asset_size_bytes=8,
        status=PublishJobStatus.PENDING.value,
    )
    db_session.add(job)
    await db_session.commit()
    upload_put_count = 0

    def google(request: httpx.Request) -> httpx.Response:
        nonlocal upload_put_count
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=uncertain"
                },
            )
        if request.url.path == "/upload/youtube/v3/videos":
            upload_put_count += 1
            if request.headers["content-range"] == "bytes 0-7/8":
                return httpx.Response(308, headers={"Range": "bytes=0-7"})
            assert request.headers["content-range"] == "bytes */8"
            return httpx.Response(200, json={"id": "YTresolved"})
        if request.url.path == "/youtube/v3/videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "YTresolved",
                            "snippet": {"channelId": "UCreconcile"},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    monkeypatch.setattr(
        youtube_publish, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(google))
    )
    adapter = YouTubePublishAdapter(session_factory)
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 1
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.RECONCILE.value
    assert job.provider_upload_uri_encrypted is not None
    assert "upload_id=uncertain" not in job.provider_upload_uri_encrypted
    assert upload_put_count == 1
    assert await reconcile_due_once(session_factory, {"youtube_shorts": adapter}) == 1
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.COMPLETE.value
    assert job.remote_post_id == "YTresolved"
    assert upload_put_count == 2  # second PUT probes the persisted session; no new POST


async def test_refresh_and_release_gates(
    monkeypatch: pytest.MonkeyPatch,
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "YOUTUBE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "YOUTUBE_PUBLISH_ENABLED", True)
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", True)
    assert youtube_publishing_ready() is False  # production OAuth callback must be HTTPS
    monkeypatch.setattr(
        settings, "YOUTUBE_REDIRECT_URI", "https://tv7.example.com/api/v1/youtube/callback"
    )
    assert youtube_publishing_ready() is True
    monkeypatch.setattr(settings, "YOUTUBE_API_AUDIT_APPROVED", False)
    assert youtube_publishing_ready() is False

    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    credential = YouTubeCredential(
        user_id=user.id,
        channel_id="UCrefresh",
        access_token=youtube_oauth.encrypt_secret("expired-access"),
        refresh_token=youtube_oauth.encrypt_secret("stable-refresh"),
        token_encryption_version=1,
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    db_session.add(credential)
    await db_session.commit()

    def token(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/token"
        assert b"stable-refresh" in request.content
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    monkeypatch.setattr(
        youtube_oauth, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(token))
    )
    assert await youtube_oauth.access_token_for(db_session, credential) == "new-access"
    assert credential.access_token != "new-access"
    assert youtube_oauth.decrypt_secret(credential.access_token) == "new-access"
    assert await youtube_oauth.access_token_for(db_session, credential) == "new-access"


async def test_youtube_crypto_and_session_reject_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", "bad-key")
    with pytest.raises(youtube_oauth.YouTubeOAuthError, match="encryption keys"):
        youtube_oauth.token_cipher()
    assert youtube_oauth.oauth_configured() is False
    monkeypatch.setattr(settings, "YOUTUBE_TOKEN_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    with pytest.raises(youtube_oauth.YouTubeOAuthError, match="cannot be decrypted"):
        youtube_oauth.decrypt_secret("not-a-token")
    assert (
        youtube_publish._valid_session_uri("http://www.googleapis.com/upload/youtube/v3/videos")
        is False
    )
    assert (
        youtube_publish._valid_session_uri("https://evil.example/upload/youtube/v3/videos") is False
    )
