from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.db.models import Clip, ClipStatus, User, Video, VideoIngestType, VideoStatus
from app.deps import db as db_deps
from app.main import app


@pytest.fixture
async def system_login_credentials(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[str, str]]:
    email = f"system-{uuid4().hex}@example.com"
    password = "system-password"
    async with session_factory() as session:
        user = User(email=email, full_name="System Tester", password_hash=hash_password(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
    yield email, password


@pytest.fixture
async def system_client(
    session_factory: async_sessionmaker[AsyncSession],
    system_login_credentials: tuple[str, str],
) -> AsyncIterator[AsyncClient]:
    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_deps.get_session] = _session_override

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            email, password = system_login_credentials
            login_response = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            login_response.raise_for_status()
            token = login_response.json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})
            yield client

    app.dependency_overrides.pop(db_deps.get_session, None)


@pytest.fixture
async def seeded_video(
    system_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, object]:
    """Create a video with one clip for publish system tests."""

    _ = system_client  # ensure auth/session fixture is initialized

    async with session_factory() as session:
        video = Video(
            source_url="upload://fixture",
            status=VideoStatus.READY.value,
            ingest_type=VideoIngestType.UPLOAD.value,
        )
        session.add(video)
        await session.flush()
        clip = Clip(
            video_id=video.id,
            start_sec=0,
            end_sec=10,
            status=ClipStatus.READY.value,
            local_path="/media/clips/dummy.mp4",
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)
        return {
            "id": video.id,
            "clips": [{"id": clip.id}],
        }


@pytest.fixture
async def app_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_deps.get_session] = _session_override

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client

    app.dependency_overrides.pop(db_deps.get_session, None)
