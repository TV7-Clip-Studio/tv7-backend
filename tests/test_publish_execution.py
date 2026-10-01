from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import Clip, PublishJob, PublishJobStatus, UploadedAsset, User, Video
from app.services.publish_adapters import configured_adapters
from app.services.publish_execution import (
    IndeterminatePublishError,
    ProviderReceipt,
    SafeRetryError,
    VerifiedTarget,
    claim_due,
    record_failure,
    recover_expired_leases,
    renew_lease,
    run_due_once,
)

pytestmark = pytest.mark.asyncio


async def make_due_job(session: AsyncSession, asset_path: Path) -> PublishJob:
    user = User(
        email=f"publisher-{uuid4().hex}@example.com",
        full_name="Publisher",
        password_hash="test",
    )
    video = Video(
        source_url=f"local://publisher-{uuid4().hex}",
        requested_by=user,
        status="ready",
        ingest_type="upload",
    )
    clip = Clip(video=video, start_sec=0, end_sec=8, status="ready")
    asset = UploadedAsset(
        user_id=0,
        storage_path=str(asset_path),
        checksum="abc",
        size_bytes=asset_path.stat().st_size,
        content_type="video/mp4",
    )
    session.add_all([user, video, clip])
    await session.flush()
    asset.user_id = user.id
    session.add(asset)
    await session.flush()
    job = PublishJob(
        clip_id=clip.id,
        user_id=user.id,
        asset_id=asset.id,
        platform="youtube_shorts",
        target_account_ref="connected-account",
        idempotency_key=f"publish-{uuid4().hex}",
        scheduled_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        status=PublishJobStatus.PENDING.value,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def test_claim_retry_and_reconcile_prevent_duplicate_attempts(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    asset_path = tmp_path / "rendered.mp4"
    asset_path.write_bytes(b"rendered")
    job = await make_due_job(db_session, asset_path)
    now = datetime.now(tz=UTC)
    assert await claim_due(db_session, set(), now=now) is None
    claim = await claim_due(db_session, {"youtube_shorts"}, now=now)
    assert claim is not None
    assert claim.id == job.id
    assert claim.status == PublishJobStatus.PUBLISHING.value
    assert claim.attempt_count == 1
    assert await claim_due(db_session, {"youtube_shorts"}, now=now) is None
    assert await renew_lease(db_session, claim.id, "wrong", now=now) is False
    assert claim.lease_token is not None
    assert await renew_lease(db_session, claim.id, claim.lease_token, now=now) is True

    assert (
        await record_failure(
            db_session,
            claim,
            claim.lease_token,
            SafeRetryError("PRE_REQUEST_NETWORK", "No provider request was sent"),
            now=now,
        )
        is True
    )
    await db_session.refresh(claim)
    assert claim.status == PublishJobStatus.PENDING.value
    assert claim.next_attempt_at is not None
    assert await claim_due(db_session, {"youtube_shorts"}, now=now) is None
    second = await claim_due(db_session, {"youtube_shorts"}, now=now + timedelta(minutes=2))
    assert second is not None
    assert second.attempt_count == 2
    assert second.lease_token is not None
    assert (
        await record_failure(
            db_session,
            second,
            second.lease_token,
            IndeterminatePublishError("REMOTE_TIMEOUT", "Remote outcome unknown"),
            now=now + timedelta(minutes=2),
        )
        is True
    )
    await db_session.refresh(second)
    assert second.status == PublishJobStatus.RECONCILE.value
    assert await claim_due(db_session, {"youtube_shorts"}, now=now + timedelta(days=1)) is None


async def test_expired_lease_requires_reconciliation(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    asset_path = tmp_path / "expired.mp4"
    asset_path.write_bytes(b"clip")
    job = await make_due_job(db_session, asset_path)
    now = datetime.now(tz=UTC)
    claim = await claim_due(db_session, {"youtube_shorts"}, now=now)
    assert claim is not None
    assert await recover_expired_leases(db_session, now=now + timedelta(minutes=6)) == 1
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.RECONCILE.value
    assert job.last_error_code == "LEASE_EXPIRED"
    assert await claim_due(db_session, {"youtube_shorts"}, now=now + timedelta(days=1)) is None


async def test_due_selection_and_safe_retry_are_bounded(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    asset_path = tmp_path / "bounded.mp4"
    asset_path.write_bytes(b"clip")
    job = await make_due_job(db_session, asset_path)
    now = datetime.now(tz=UTC)
    job.scheduled_at = now + timedelta(hours=1)
    await db_session.commit()
    assert await claim_due(db_session, {"youtube_shorts"}, now=now) is None
    job.scheduled_at = now - timedelta(minutes=1)
    await db_session.commit()
    for attempt in range(1, 4):
        timestamp = now + timedelta(minutes=10 * attempt)
        claim = await claim_due(db_session, {"youtube_shorts"}, now=timestamp)
        assert claim is not None
        assert claim.attempt_count == attempt
        assert claim.lease_token is not None
        assert (
            await record_failure(
                db_session,
                claim,
                claim.lease_token,
                SafeRetryError("PRE_REQUEST_NETWORK", "No provider request was sent"),
                now=timestamp,
            )
            is True
        )
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.FAILED.value
    assert job.attempt_count == 3
    assert await claim_due(db_session, {"youtube_shorts"}, now=now + timedelta(days=1)) is None


class ReceiptAdapter:
    guarantees_idempotent_publish = True

    def __init__(self) -> None:
        self.calls = 0

    async def resolve_target(self, user_id: int, account_ref: str) -> VerifiedTarget:
        return VerifiedTarget(user_id, "youtube_shorts", account_ref, "provider-channel-1")

    async def publish(
        self, job: PublishJob, asset_path: Path, target: VerifiedTarget, idempotency_key: str
    ) -> ProviderReceipt:
        self.calls += 1
        assert asset_path.read_bytes() == b"approved bytes"
        assert idempotency_key == job.idempotency_key
        return ProviderReceipt(
            platform=job.platform,
            provider_account_id=target.provider_account_id,
            remote_post_id="remote-post-123",
            published_at=datetime.now(tz=UTC),
            payload={"id": "remote-post-123"},
        )


async def test_worker_requires_registered_replay_safe_adapter_and_receipt(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path))
    asset_path = tmp_path / "approved.mp4"
    asset_path.write_bytes(b"approved bytes")
    job = await make_due_job(db_session, asset_path)
    assert configured_adapters() == {}
    assert await run_due_once(session_factory, {}) == 0
    await db_session.refresh(job)
    assert job.status == PublishJobStatus.PENDING.value
    adapter = ReceiptAdapter()
    adapter.guarantees_idempotent_publish = False
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 0
    assert adapter.calls == 0
    adapter.guarantees_idempotent_publish = True
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 1
    await db_session.refresh(job)
    assert adapter.calls == 1
    assert job.status == PublishJobStatus.COMPLETE.value
    assert job.remote_post_id == "remote-post-123"
    assert job.published_at is not None
    assert '"remote-post-123"' in (job.response_payload or "")
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 0
    assert adapter.calls == 1


async def test_worker_rejects_wrong_target_without_provider_call(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path))
    asset_path = tmp_path / "target.mp4"
    asset_path.write_bytes(b"approved bytes")
    job = await make_due_job(db_session, asset_path)

    class WrongTargetAdapter(ReceiptAdapter):
        async def resolve_target(self, user_id: int, account_ref: str) -> VerifiedTarget:
            return VerifiedTarget(user_id + 1, "youtube_shorts", account_ref, "wrong-account")

    adapter = WrongTargetAdapter()
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 1
    await db_session.refresh(job)
    assert adapter.calls == 0
    assert job.status == PublishJobStatus.FAILED.value
    assert job.last_error_code == "TARGET_MISMATCH"
    assert job.remote_post_id is None


async def test_receipt_without_remote_id_needs_reconciliation(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCHEDULED_ASSET_STORAGE_DIR", str(tmp_path))
    asset_path = tmp_path / "receipt.mp4"
    asset_path.write_bytes(b"approved bytes")
    job = await make_due_job(db_session, asset_path)

    class MissingReceiptAdapter(ReceiptAdapter):
        async def publish(
            self, job: PublishJob, _asset_path: Path, target: VerifiedTarget, _idempotency_key: str
        ) -> ProviderReceipt:
            self.calls += 1
            return ProviderReceipt(
                job.platform, target.provider_account_id, "", datetime.now(tz=UTC), {}
            )

    adapter = MissingReceiptAdapter()
    assert await run_due_once(session_factory, {"youtube_shorts": adapter}) == 1
    await db_session.refresh(job)
    assert adapter.calls == 1
    assert job.status == PublishJobStatus.RECONCILE.value
    assert job.last_error_code == "RECEIPT_MISMATCH"
    assert job.remote_post_id is None
