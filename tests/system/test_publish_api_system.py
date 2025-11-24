from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db.models import PublishJobStatus


@pytest.mark.system
async def test_config_endpoint(system_client: AsyncClient) -> None:
    resp = await system_client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["publishing_enabled"] is True
    assert data["asset_upload_required"] is True
    assert "youtube_shorts" in data["allowed_platforms"]
    assert data["max_asset_size_bytes"] is not None


@pytest.mark.system
async def test_publish_endpoints(system_client: AsyncClient, seeded_video: dict) -> None:
    # seeded_video fixture should provide a video with at least one clip
    clip_id = seeded_video["clips"][0]["id"]

    # Trigger publish
    payload = {
        "platforms": ["youtube_shorts", "tiktok"],
        "asset_url": "https://example.com/clip.mp4",
        "asset_checksum": "abc123",
        "asset_size_bytes": 1234,
    }
    resp = await system_client.post(f"/api/v1/clips/{clip_id}/publish", json=payload)
    assert resp.status_code == 202
    jobs = resp.json()
    assert len(jobs) == 2
    for job in jobs:
        assert job["clip_id"] == clip_id
        assert job["status"] == PublishJobStatus.QUEUED.value
        assert job["asset_url"] == payload["asset_url"]

    # List publish jobs
    resp = await system_client.get(f"/api/v1/clips/{clip_id}/publish")
    assert resp.status_code == 200
    listed = resp.json()
    assert {j["platform"] for j in listed} == {"youtube_shorts", "tiktok"}


@pytest.mark.system
async def test_clip_update(system_client: AsyncClient, seeded_video: dict) -> None:
    clip_id = seeded_video["clips"][0]["id"]
    patch = {
        "asset_url": "https://example.com/asset.mp4",
        "asset_checksum": "deadbeef",
        "asset_size_bytes": 999,
        "render_width": 1080,
        "render_height": 1920,
        "frame_rate": 30.0,
        "file_size_bytes": 1024,
        "caption_text": "hello",
        "ready_local_only": True,
    }
    resp = await system_client.patch(f"/api/v1/clips/{clip_id}", json=patch)
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["asset_url"] == patch["asset_url"]
        assert data["render_width"] == patch["render_width"]
