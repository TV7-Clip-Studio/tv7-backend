from __future__ import annotations

import io

import pytest
from httpx import AsyncClient


@pytest.mark.system
async def test_asset_upload(system_client: AsyncClient) -> None:
    payload = {"file": ("clip.mp4", io.BytesIO(b"fake-video-bytes"), "video/mp4")}
    resp = await system_client.post("/api/v1/uploads/assets", files=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_url"]
    assert data["asset_checksum"]
    assert data["asset_size_bytes"] == len(b"fake-video-bytes")
