from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jwt import TokenType, decode_token
from app.core.security import hash_password
from app.db.models import Clip, User, Video
from app.repositories.videos import VideoRepository

pytestmark = pytest.mark.asyncio


async def test_register_local_video_with_clips(
    async_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "source_url": "local://video-123",
        "title": "Test Video",
        "duration_seconds": 120,
        "file_size_bytes": 1024,
        "clip_generation_mode": "replace",
        "clips": [
            {
                "start_sec": 0,
                "end_sec": 30,
                "asset_url": "/media/uploads/assets/clip1.mp4",
                "caption_text": "Hook 1",
            }
        ],
    }

    response = await async_client.post(
        "/api/v1/videos/local",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["source_url"] == payload["source_url"]
    assert body["ingest_type"] == "upload"
    assert body["status"] == "ready"
    assert body["source_media_url"] is None
    assert len(body["clips"]) == 1

    video_id = body["id"]
    fetched = await async_client.get(f"/api/v1/videos/{video_id}", headers=auth_headers)
    assert fetched.status_code == HTTPStatus.OK
    fetched_body = fetched.json()
    assert fetched_body["original_filename"] == payload["title"]
    assert fetched_body["clips"][0]["caption_text"] == "Hook 1"


async def test_create_additional_clip(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    login_credentials: tuple[str, str],
) -> None:
    repo = VideoRepository(db_session)
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    video = Video(
        source_url="local://existing",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    await repo.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    clip_payload = {"start_sec": 10, "end_sec": 20, "asset_url": "/media/clip2.mp4"}
    response = await async_client.post(
        f"/api/v1/videos/{video.id}/clips",
        json=clip_payload,
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    created = response.json()
    assert created["video_id"] == video.id
    assert created["asset_url"] == clip_payload["asset_url"]

    refreshed = await repo.get_with_clips(video.id)
    assert refreshed is not None
    assert any(
        isinstance(c, Clip) and c.asset_url == clip_payload["asset_url"] for c in refreshed.clips
    )


async def test_list_videos_returns_clips(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    login_credentials: tuple[str, str],
) -> None:
    repo = VideoRepository(db_session)
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    video = Video(
        source_url="local://listed",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    video.clips.append(Clip(start_sec=0, end_sec=15, asset_url="/media/clip3.mp4"))
    await repo.add(video)
    await db_session.commit()

    response = await async_client.get("/api/v1/videos", headers=auth_headers)
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert isinstance(body, list)
    assert any(v["source_url"] == "local://listed" and v["clips"] for v in body)


async def test_source_upload_is_private_and_account_scoped(  # noqa: PLR0915
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "SOURCE_MEDIA_STORAGE_DIR", str(tmp_path / "private"))
    created = await async_client.post(
        "/api/v1/videos/local",
        json={"source_url": "local://private-test", "title": "private.mp4"},
        headers=auth_headers,
    )
    assert created.status_code == HTTPStatus.CREATED
    video_id = created.json()["id"]
    duplicate = await async_client.post(
        "/api/v1/videos/local",
        json={"source_url": "local://private-test", "title": "private.mp4"},
        headers=auth_headers,
    )
    assert duplicate.json()["id"] == video_id

    uploaded = await async_client.post(
        f"/api/v1/videos/{video_id}/source",
        files={"file": ("private.mp4", b"video bytes", "video/mp4")},
        headers=auth_headers,
    )
    assert uploaded.status_code == HTTPStatus.OK, uploaded.text
    url = uploaded.json()["source_media_url"]
    assert url == f"/api/v1/videos/{video_id}/source"
    assert (await async_client.get(url)).status_code == HTTPStatus.UNAUTHORIZED
    own = await async_client.get(url, headers=auth_headers)
    assert own.status_code == HTTPStatus.OK
    assert own.content == b"video bytes"

    other_user = User(
        email="other-private@example.com",
        full_name="Other",
        password_hash=hash_password("other-pass"),
    )
    db_session.add(other_user)
    await db_session.commit()
    other_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": other_user.email, "password": "other-pass"},
    )
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert (await async_client.get(url, headers=other_headers)).status_code == HTTPStatus.NOT_FOUND
    forbidden_upload = await async_client.post(
        url,
        files={"file": ("stolen.mp4", b"other", "video/mp4")},
        headers=other_headers,
    )
    assert forbidden_upload.status_code == HTTPStatus.NOT_FOUND
    assert (
        await async_client.get(f"/api/v1/videos/{video_id}", headers=other_headers)
    ).status_code == HTTPStatus.NOT_FOUND
    assert (await async_client.get("/api/v1/videos", headers=other_headers)).json() == []

    rejected = await async_client.post(
        url,
        files={"file": ("bad.txt", b"not video", "text/plain")},
        headers=auth_headers,
    )
    assert rejected.status_code == HTTPStatus.BAD_REQUEST
    still_own = await async_client.get(url, headers=auth_headers)
    assert still_own.content == b"video bytes"

    empty = await async_client.post(
        url,
        files={"file": ("empty.mp4", b"", "video/mp4")},
        headers=auth_headers,
    )
    assert empty.status_code == HTTPStatus.BAD_REQUEST
    assert (await async_client.get(url, headers=auth_headers)).content == b"video bytes"

    missing = await async_client.get("/api/v1/videos/999999/source", headers=auth_headers)
    assert missing.status_code == HTTPStatus.NOT_FOUND
    no_source = await async_client.post(
        "/api/v1/videos/local",
        json={"source_url": "local://no-source", "title": "later.mp4"},
        headers=auth_headers,
    )
    assert no_source.status_code == HTTPStatus.CREATED
    no_source_id = no_source.json()["id"]
    assert (
        await async_client.get(f"/api/v1/videos/{no_source_id}/source", headers=auth_headers)
    ).status_code == HTTPStatus.NOT_FOUND

    monkeypatch.setattr(settings, "UPLOAD_MAX_FILE_SIZE_MB", 0)
    oversized = await async_client.post(
        url,
        files={"file": ("large.mp4", b"one byte", "video/mp4")},
        headers=auth_headers,
    )
    assert oversized.status_code == HTTPStatus.BAD_REQUEST
    assert (await async_client.get(url, headers=auth_headers)).content == b"video bytes"

    monkeypatch.setattr(settings, "UPLOAD_MAX_FILE_SIZE_MB", 4096)
    replaced = await async_client.post(
        url,
        files={"file": ("replacement.webm", b"new video", "video/webm")},
        headers=auth_headers,
    )
    assert replaced.status_code == HTTPStatus.OK
    assert replaced.json()["upload_file_size_bytes"] == len(b"new video")
    assert (await async_client.get(url, headers=auth_headers)).content == b"new video"
    assert not (tmp_path / "private" / str(video_id) / "source.mp4").exists()

    video = await db_session.get(Video, video_id)
    assert video is not None
    outside_path = tmp_path / "outside.mp4"
    outside_path.write_bytes(b"untouched")
    video.upload_original_path = str(outside_path)
    await db_session.commit()
    assert (await async_client.get(url, headers=auth_headers)).status_code == HTTPStatus.NOT_FOUND
    restored = await async_client.post(
        url,
        files={"file": ("restored.mp4", b"restored", "video/mp4")},
        headers=auth_headers,
    )
    assert restored.status_code == HTTPStatus.OK
    assert restored.json()["source_media_url"] == url
    assert restored.json()["upload_file_size_bytes"] == len(b"restored")
    assert restored.json()["upload_checksum"] is not None
    assert (await async_client.get(url, headers=auth_headers)).content == b"restored"
    assert outside_path.read_bytes() == b"untouched"
    library = await async_client.get("/api/v1/videos", headers=auth_headers)
    assert library.status_code == HTTPStatus.OK
    matching = [item for item in library.json() if item["id"] == video_id]
    assert len(matching) == 1
    assert matching[0]["source_media_url"] == url
    assert matching[0]["original_filename"] == "private.mp4"
    assert matching[0]["upload_file_size_bytes"] == len(b"restored")
    assert matching[0]["status"] == "ready"


async def test_source_ticket_is_video_scoped_expires_and_supports_range(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SOURCE_MEDIA_STORAGE_DIR", str(tmp_path / "private"))
    video_ids = []
    for suffix in ("one", "two"):
        created = await async_client.post(
            "/api/v1/videos/local",
            json={
                "source_url": f"local://ticket-{suffix}",
                "title": f"{suffix}.mp4",
                "duration_seconds": 3600,
            },
            headers=auth_headers,
        )
        assert created.status_code == HTTPStatus.CREATED
        video_ids.append(created.json()["id"])
        uploaded = await async_client.post(
            f"/api/v1/videos/{video_ids[-1]}/source",
            files={"file": (f"{suffix}.mp4", b"0123456789", "video/mp4")},
            headers=auth_headers,
        )
        assert uploaded.status_code == HTTPStatus.OK

    ticket_response = await async_client.post(
        f"/api/v1/videos/{video_ids[0]}/source-ticket", headers=auth_headers
    )
    assert ticket_response.status_code == HTTPStatus.OK
    assert ticket_response.json()["expires_in_seconds"] == 75 * 60
    ticket_url = ticket_response.json()["url"]
    ticket = parse_qs(urlsplit(ticket_url).query)["ticket"][0]
    assert decode_token(ticket, expected_type=TokenType.VIDEO_SOURCE)["scopes"] == [
        f"video:source:{video_ids[0]}"
    ]
    streamed = await async_client.get(ticket_url, headers={"Range": "bytes=2-5"})
    assert streamed.status_code == HTTPStatus.PARTIAL_CONTENT
    assert streamed.content == b"2345"

    unrelated_url = f"/api/v1/videos/{video_ids[1]}/source?ticket={ticket}"
    assert (await async_client.get(unrelated_url)).status_code == HTTPStatus.UNAUTHORIZED
    assert (
        await async_client.get("/api/v1/videos", headers={"Authorization": f"Bearer {ticket}"})
    ).status_code == HTTPStatus.UNAUTHORIZED

    expired_ticket = jwt.encode(
        {
            "sub": decode_token(ticket)["sub"],
            "type": TokenType.VIDEO_SOURCE.value,
            "scopes": [f"video:source:{video_ids[0]}"],
            "exp": datetime.now(tz=UTC) - timedelta(minutes=1),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert (
        await async_client.get(f"/api/v1/videos/{video_ids[0]}/source?ticket={expired_ticket}")
    ).status_code == HTTPStatus.UNAUTHORIZED
