from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Clip, User, Video

pytestmark = pytest.mark.asyncio


async def test_private_asset_and_schedule_draft_are_owner_scoped(  # noqa: PLR0913, PLR0915
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path / "private-assets"))
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    video = Video(
        source_url=f"local://draft-{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    clip = Clip(video=video, start_sec=0, end_sec=10, status="ready")
    db_session.add_all([video, clip])
    await db_session.commit()
    await db_session.refresh(clip)

    upload = await async_client.post(
        "/api/v1/uploads/assets",
        files={"file": ("approved.mp4", b"rendered bytes", "video/mp4")},
        headers=auth_headers,
    )
    assert upload.status_code == HTTPStatus.CREATED, upload.text
    asset = upload.json()
    assert asset["asset_url"] == f"/api/v1/uploads/assets/{asset['asset_id']}"
    assert (await async_client.get(asset["asset_url"])).status_code == HTTPStatus.UNAUTHORIZED
    own_asset = await async_client.get(asset["asset_url"], headers=auth_headers)
    assert own_asset.content == b"rendered bytes"
    assert (
        await async_client.get("/media/uploads/assets/approved.mp4")
    ).status_code == HTTPStatus.NOT_FOUND

    other_email = f"other-{uuid4().hex}@example.com"
    db_session.add(
        User(email=other_email, full_name="Other", password_hash=hash_password("other-pass"))
    )
    await db_session.commit()
    other_login = await async_client.post(
        "/api/v1/auth/login", json={"email": other_email, "password": "other-pass"}
    )
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert (
        await async_client.get(asset["asset_url"], headers=other_headers)
    ).status_code == HTTPStatus.NOT_FOUND
    assert (
        await async_client.patch(
            f"/api/v1/clips/{clip.id}", json={"caption_text": "intrusion"}, headers=other_headers
        )
    ).status_code == HTTPStatus.NOT_FOUND
    other_user = (
        await db_session.execute(select(User).where(User.email == other_email))
    ).scalar_one()
    other_video = Video(
        source_url=f"local://other-draft-{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=other_user.id,
    )
    other_clip = Clip(video=other_video, start_sec=0, end_sec=10, status="ready")
    db_session.add_all([other_video, other_clip])
    await db_session.commit()
    await db_session.refresh(other_clip)
    foreign_asset_update = await async_client.patch(
        f"/api/v1/clips/{other_clip.id}",
        json={"asset_url": asset["asset_url"]},
        headers=other_headers,
    )
    assert foreign_asset_update.status_code == HTTPStatus.NOT_FOUND

    clip_asset = await async_client.patch(
        f"/api/v1/clips/{clip.id}",
        json={"asset_url": asset["asset_url"], "asset_checksum": "wrong"},
        headers=auth_headers,
    )
    assert clip_asset.status_code == HTTPStatus.OK, clip_asset.text
    assert clip_asset.json()["asset_checksum"] == asset["asset_checksum"]

    scheduled_at = (datetime.now(tz=UTC) + timedelta(days=1)).isoformat()
    payload = {
        "platform": "youtube_shorts",
        "target_account_ref": "future-connected-channel",
        "scheduled_at": scheduled_at,
        "caption": "A clip ready for approval",
        "asset_id": asset["asset_id"],
        "idempotency_key": f"draft-{uuid4().hex}",
    }
    endpoint = f"/api/v1/clips/{clip.id}/schedule-drafts"
    denied = await async_client.post(endpoint, json=payload, headers=other_headers)
    assert denied.status_code == HTTPStatus.NOT_FOUND
    foreign_draft = await async_client.post(
        f"/api/v1/clips/{other_clip.id}/schedule-drafts", json=payload, headers=other_headers
    )
    assert foreign_draft.status_code == HTTPStatus.NOT_FOUND
    created = await async_client.post(endpoint, json=payload, headers=auth_headers)
    assert created.status_code == HTTPStatus.CREATED, created.text
    job = created.json()
    assert job["status"] == "pending"
    assert job["asset_id"] == asset["asset_id"]
    assert job["target_account_ref"] == payload["target_account_ref"]
    assert job["caption"] == payload["caption"]
    assert job["scheduled_at"] is not None
    assert (await async_client.post(endpoint, json=payload, headers=auth_headers)).json()[
        "id"
    ] == job["id"]

    changed = await async_client.post(
        endpoint, json={**payload, "caption": "different"}, headers=auth_headers
    )
    assert changed.status_code == HTTPStatus.CONFLICT
    own_list = await async_client.get(f"/api/v1/clips/{clip.id}/publish", headers=auth_headers)
    assert [item["id"] for item in own_list.json()] == [job["id"]]
    assert (
        await async_client.get(f"/api/v1/clips/{clip.id}/publish", headers=other_headers)
    ).status_code == HTTPStatus.NOT_FOUND
    unsupported = await async_client.post(
        f"/api/v1/clips/{clip.id}/publish",
        json={"platforms": ["youtube_shorts"], "asset_url": asset["asset_url"]},
        headers=auth_headers,
    )
    assert unsupported.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    config = await async_client.get("/api/v1/config", headers=auth_headers)
    assert config.json()["publishing_enabled"] is False
    assert config.json()["scheduling_enabled"] is False
    assert config.json()["allowed_platforms"] == []


async def test_schedule_draft_validates_time_and_asset_ownership(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    user = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    video = Video(
        source_url=f"local://draft-validation-{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=user.id,
    )
    clip = Clip(video=video, start_sec=0, end_sec=5, status="ready")
    db_session.add_all([video, clip])
    await db_session.commit()
    await db_session.refresh(clip)
    endpoint = f"/api/v1/clips/{clip.id}/schedule-drafts"
    base = {
        "platform": "instagram",
        "target_account_ref": "later-account",
        "asset_id": 999999,
        "idempotency_key": f"draft-{uuid4().hex}",
    }
    naive = await async_client.post(
        endpoint, json={**base, "scheduled_at": "2030-01-01T12:00:00"}, headers=auth_headers
    )
    assert naive.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    past = await async_client.post(
        endpoint, json={**base, "scheduled_at": "2020-01-01T12:00:00Z"}, headers=auth_headers
    )
    assert past.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    future = (datetime.now(tz=UTC) + timedelta(days=1)).isoformat()
    missing_asset = await async_client.post(
        endpoint, json={**base, "scheduled_at": future}, headers=auth_headers
    )
    assert missing_asset.status_code == HTTPStatus.NOT_FOUND
