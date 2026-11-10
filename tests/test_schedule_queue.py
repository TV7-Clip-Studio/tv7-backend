from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Clip, PublishJob, PublishJobStatus, User, Video

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def queue_jobs(
    login_credentials: tuple[str, str], db_session: AsyncSession
) -> list[PublishJob]:
    owner = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    other = User(email=f"other-{uuid4().hex}@example.com", full_name="Other")
    db_session.add(other)
    await db_session.flush()
    jobs = []
    combinations = [
        (owner, "pending", "youtube_shorts", "main"),
        (owner, "pending", "youtube_shorts", "main"),
        (owner, "complete", "youtube_shorts", "main"),
        (owner, "pending", "instagram", "main"),
        (owner, "pending", "youtube_shorts", "secondary"),
        (other, "pending", "youtube_shorts", "main"),
    ]
    for index, (user, state, platform, profile) in enumerate(combinations):
        video = Video(
            source_url=f"local://{uuid4().hex}",
            status="ready",
            ingest_type="upload",
            requested_by_user_id=user.id,
        )
        clip = Clip(video=video, start_sec=0, end_sec=10, status="ready")
        db_session.add(clip)
        await db_session.flush()
        jobs.append(
            PublishJob(
                clip_id=clip.id,
                user_id=user.id,
                platform=platform,
                status=state,
                creator_profile_id=profile,
                caption=f"Scheduled clip {index}",
                scheduled_at=datetime.now(tz=UTC) + timedelta(days=index + 1),
            )
        )
    db_session.add_all(jobs)
    await db_session.commit()
    return jobs


@pytest.mark.parametrize("prefix", ["/api/v1", "/api/v1/publish"])
async def test_get_schedule_job_is_owner_scoped(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    queue_jobs: list[PublishJob],
    prefix: str,
) -> None:
    job = queue_jobs[0]
    response = await async_client.get(f"{prefix}/schedule-jobs/{job.id}", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["id"] == job.id
    assert result["clip_id"] == job.clip_id
    assert result["caption"] == job.caption
    assert result["creator_profile_id"] == "main"
    assert result["status"] == "pending"
    assert result["platform"] == "youtube_shorts"

    foreign = await async_client.get(
        f"{prefix}/schedule-jobs/{queue_jobs[-1].id}", headers=auth_headers
    )
    missing = await async_client.get(
        f"{prefix}/schedule-jobs/{queue_jobs[-1].id + 1}", headers=auth_headers
    )
    assert foreign.status_code == missing.status_code == 404
    assert (
        foreign.json()
        == missing.json()
        == {"error": {"code": 404, "message": "Schedule job not found"}}
    )


@pytest.mark.parametrize("prefix", ["/api/v1", "/api/v1/publish"])
@pytest.mark.parametrize(
    "case",
    [
        ({"status": "pending"}, [0, 1, 3, 4]),
        ({"platform": "youtube_shorts"}, [0, 1, 2, 4]),
        ({"status": "complete", "platform": "youtube_shorts"}, [2]),
        ({"status": "complete", "platform": "instagram"}, []),
        ({"platform": "unknown-platform"}, []),
        (
            {"status": "pending", "platform": "youtube_shorts", "creator_profile_id": "main"},
            [0, 1],
        ),
        (
            {
                "status": "pending",
                "platform": "youtube_shorts",
                "creator_profile_id": "main",
                "limit": "1",
                "offset": "1",
            },
            [1],
        ),
    ],
)
async def test_schedule_queue_filters_compose_with_owner_profile_and_pagination(
    *,
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    queue_jobs: list[PublishJob],
    prefix: str,
    case: tuple[dict[str, str], list[int]],
) -> None:
    params, expected = case
    response = await async_client.get(
        f"{prefix}/schedule-jobs", params=params, headers=auth_headers
    )
    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == [queue_jobs[index].id for index in expected]


@pytest.mark.parametrize("prefix", ["/api/v1", "/api/v1/publish"])
@pytest.mark.parametrize(
    "params", [{"status": "invalid"}, {"platform": ""}, {"platform": "x" * 41}]
)
async def test_schedule_queue_rejects_invalid_filters(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    prefix: str,
    params: dict[str, str],
) -> None:
    response = await async_client.get(
        f"{prefix}/schedule-jobs", params=params, headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/schedule-jobs",
        "/api/v1/schedule-jobs/1",
        "/api/v1/publish/schedule-jobs",
        "/api/v1/publish/schedule-jobs/1",
    ],
)
async def test_schedule_queue_reads_require_authentication(
    async_client: AsyncClient, path: str
) -> None:
    assert (await async_client.get(path)).status_code == 401


async def test_owner_queue_reschedule_cancel_and_idempotent_cancel(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    owner = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    other = User(
        email=f"other-{uuid4().hex}@example.com",
        full_name="Other",
        password_hash=hash_password("other-pass"),
    )
    db_session.add(other)
    await db_session.flush()
    owner_video = Video(
        source_url=f"local://{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=owner.id,
    )
    other_video = Video(
        source_url=f"local://{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=other.id,
    )
    owner_clip = Clip(video=owner_video, start_sec=0, end_sec=10, status="ready")
    other_clip = Clip(video=other_video, start_sec=0, end_sec=10, status="ready")
    db_session.add_all([owner_video, other_video, owner_clip, other_clip])
    await db_session.flush()
    first = PublishJob(
        clip_id=owner_clip.id,
        user_id=owner.id,
        platform="youtube_shorts",
        status=PublishJobStatus.PENDING.value,
        scheduled_at=datetime.now(tz=UTC) + timedelta(days=3),
        idempotency_key=f"draft-{uuid4().hex}",
    )
    second = PublishJob(
        clip_id=owner_clip.id,
        user_id=owner.id,
        platform="youtube_shorts",
        status=PublishJobStatus.PENDING.value,
        scheduled_at=datetime.now(tz=UTC) + timedelta(days=4),
        idempotency_key=f"draft-{uuid4().hex}",
    )
    foreign = PublishJob(
        clip_id=other_clip.id,
        user_id=other.id,
        platform="youtube_shorts",
        status=PublishJobStatus.PENDING.value,
        scheduled_at=datetime.now(tz=UTC) + timedelta(days=5),
        idempotency_key=f"draft-{uuid4().hex}",
    )
    db_session.add_all([first, second, foreign])
    await db_session.commit()

    queue = await async_client.get("/api/v1/schedule-jobs", headers=auth_headers)
    assert queue.status_code == 200
    assert [job["id"] for job in queue.json()] == [first.id, second.id]
    page = await async_client.get("/api/v1/schedule-jobs?limit=1&offset=1", headers=auth_headers)
    assert [job["id"] for job in page.json()] == [second.id]

    future = (datetime.now(tz=UTC) + timedelta(days=30)).isoformat()
    endpoint = f"/api/v1/schedule-jobs/{first.id}"
    changed = await async_client.patch(
        endpoint, json={"scheduled_at": future}, headers=auth_headers
    )
    assert changed.status_code == 200, changed.text
    assert datetime.fromisoformat(changed.json()["scheduled_at"]) == datetime.fromisoformat(future)
    assert (
        await async_client.patch(endpoint, json={"scheduled_at": future}, headers=auth_headers)
    ).status_code == 200
    assert (
        await async_client.patch(
            endpoint, json={"scheduled_at": "2020-01-01T00:00:00Z"}, headers=auth_headers
        )
    ).status_code == 422
    assert (
        await async_client.patch(
            endpoint, json={"scheduled_at": "2030-01-01T00:00:00"}, headers=auth_headers
        )
    ).status_code == 422

    cancel = await async_client.post(f"{endpoint}/cancel", headers=auth_headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert (await async_client.post(f"{endpoint}/cancel", headers=auth_headers)).status_code == 200
    assert (
        await async_client.patch(endpoint, json={"scheduled_at": future}, headers=auth_headers)
    ).status_code == 409

    other_login = await async_client.post(
        "/api/v1/auth/login", json={"email": other.email, "password": "other-pass"}
    )
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert (
        await async_client.patch(endpoint, json={"scheduled_at": future}, headers=other_headers)
    ).status_code == 404
    assert (await async_client.post(f"{endpoint}/cancel", headers=other_headers)).status_code == 404
    assert [
        job["id"]
        for job in (await async_client.get("/api/v1/schedule-jobs", headers=other_headers)).json()
    ] == [foreign.id]


async def test_claimed_or_attempted_job_cannot_be_managed(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    login_credentials: tuple[str, str],
    db_session: AsyncSession,
) -> None:
    owner = (
        await db_session.execute(select(User).where(User.email == login_credentials[0]))
    ).scalar_one()
    video = Video(
        source_url=f"local://{uuid4().hex}",
        status="ready",
        ingest_type="upload",
        requested_by_user_id=owner.id,
    )
    clip = Clip(video=video, start_sec=0, end_sec=10, status="ready")
    db_session.add_all([video, clip])
    await db_session.flush()
    jobs = [
        PublishJob(
            clip_id=clip.id,
            user_id=owner.id,
            platform="youtube_shorts",
            status=state,
            attempt_count=attempts,
            scheduled_at=datetime.now(tz=UTC) + timedelta(days=1),
        )
        for state, attempts in [("publishing", 1), ("pending", 1), ("complete", 1)]
    ]
    db_session.add_all(jobs)
    await db_session.commit()
    future = (datetime.now(tz=UTC) + timedelta(days=2)).isoformat()
    for job in jobs:
        endpoint = f"/api/v1/schedule-jobs/{job.id}"
        assert (
            await async_client.patch(endpoint, json={"scheduled_at": future}, headers=auth_headers)
        ).status_code == 409
        assert (
            await async_client.post(f"{endpoint}/cancel", headers=auth_headers)
        ).status_code == 409
