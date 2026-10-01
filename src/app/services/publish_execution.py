from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PublishJob, PublishJobStatus, UploadedAsset
from app.services.asset_storage import AssetNotFoundError, AssetStorageError, materialize_asset

logger = logging.getLogger(__name__)
LEASE_DURATION = timedelta(minutes=5)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class VerifiedTarget:
    user_id: int
    platform: str
    account_ref: str
    provider_account_id: str


@dataclass(frozen=True)
class ProviderReceipt:
    platform: str
    provider_account_id: str
    remote_post_id: str
    published_at: datetime
    payload: dict[str, object]


class PublishAdapter(Protocol):
    """A future real provider adapter must verify ownership and replay safety."""

    guarantees_idempotent_publish: bool
    supports_safe_initial_attempt: bool

    async def resolve_target(self, user_id: int, account_ref: str) -> VerifiedTarget: ...

    async def publish(
        self, job: PublishJob, asset_path: Path, target: VerifiedTarget, idempotency_key: str
    ) -> ProviderReceipt: ...


class PublishExecutionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SafeRetryError(PublishExecutionError):
    """Raised only before a remote publish request could have been accepted."""


class PermanentPublishError(PublishExecutionError):
    """A verified permanent failure, such as an unconnected account."""


class IndeterminatePublishError(PublishExecutionError):
    """The remote outcome is unknown; automatic retry could duplicate a post."""


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Worker timestamps must include a timezone")
    return value.astimezone(UTC)


def _affected(result: object) -> int:
    return int(getattr(result, "rowcount", 0))


async def claim_due(
    session: AsyncSession,
    enabled_platforms: set[str],
    *,
    now: datetime | None = None,
) -> PublishJob | None:
    """Atomically lease one due draft. An empty adapter set cannot claim anything."""

    if not enabled_platforms:
        return None
    timestamp = _as_utc(now or _utc_now())
    candidates = (
        (
            await session.execute(
                select(PublishJob.id)
                .where(
                    PublishJob.status == PublishJobStatus.PENDING.value,
                    PublishJob.scheduled_at.is_not(None),
                    PublishJob.scheduled_at <= timestamp,
                    or_(
                        PublishJob.next_attempt_at.is_(None),
                        PublishJob.next_attempt_at <= timestamp,
                    ),
                    PublishJob.attempt_count < MAX_ATTEMPTS,
                    PublishJob.platform.in_(enabled_platforms),
                    PublishJob.user_id.is_not(None),
                    PublishJob.asset_id.is_not(None),
                    PublishJob.target_account_ref.is_not(None),
                    PublishJob.idempotency_key.is_not(None),
                )
                .order_by(PublishJob.scheduled_at, PublishJob.id)
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    for job_id in candidates:
        lease_token = uuid4().hex
        claimed = await session.execute(
            update(PublishJob)
            .where(
                PublishJob.id == job_id,
                PublishJob.status == PublishJobStatus.PENDING.value,
                PublishJob.scheduled_at <= timestamp,
                or_(PublishJob.next_attempt_at.is_(None), PublishJob.next_attempt_at <= timestamp),
                PublishJob.attempt_count < MAX_ATTEMPTS,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=PublishJobStatus.PUBLISHING.value,
                lease_token=lease_token,
                lease_expires_at=timestamp + LEASE_DURATION,
                attempt_count=PublishJob.attempt_count + 1,
            )
        )
        await session.commit()
        if _affected(claimed) == 1:
            job = await session.get(PublishJob, job_id)
            assert job is not None
            await session.refresh(job)
            return job
    return None


async def renew_lease(
    session: AsyncSession,
    job_id: int,
    lease_token: str,
    *,
    now: datetime | None = None,
) -> bool:
    timestamp = _as_utc(now or _utc_now())
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job_id,
            PublishJob.status == PublishJobStatus.PUBLISHING.value,
            PublishJob.lease_token == lease_token,
        )
        .execution_options(synchronize_session=False)
        .values(lease_expires_at=timestamp + LEASE_DURATION)
    )
    await session.commit()
    return _affected(result) == 1


async def recover_expired_leases(session: AsyncSession, *, now: datetime | None = None) -> int:
    timestamp = _as_utc(now or _utc_now())
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.status == PublishJobStatus.PUBLISHING.value,
            PublishJob.lease_expires_at.is_not(None),
            PublishJob.lease_expires_at <= timestamp,
        )
        .execution_options(synchronize_session=False)
        .values(
            status=PublishJobStatus.RECONCILE.value,
            lease_token=None,
            lease_expires_at=None,
            last_error_code="LEASE_EXPIRED",
            error_message="Publish attempt outcome is unknown after lease expiration",
        )
    )
    await session.commit()
    return _affected(result)


async def record_receipt(
    session: AsyncSession,
    job: PublishJob,
    lease_token: str,
    target: VerifiedTarget,
    receipt: ProviderReceipt,
) -> bool:
    if (
        not receipt.remote_post_id.strip()
        or receipt.platform != job.platform
        or receipt.provider_account_id != target.provider_account_id
        or target.user_id != job.user_id
        or target.account_ref != job.target_account_ref
        or target.platform != job.platform
        or receipt.published_at.utcoffset() is None
    ):
        raise IndeterminatePublishError(
            "RECEIPT_MISMATCH", "Provider receipt does not match the claimed target"
        )
    response = json.dumps(receipt.payload, sort_keys=True, default=str)
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job.id,
            PublishJob.status == PublishJobStatus.PUBLISHING.value,
            PublishJob.lease_token == lease_token,
        )
        .execution_options(synchronize_session=False)
        .values(
            status=PublishJobStatus.COMPLETE.value,
            provider_upload_uri_encrypted=None,
            lease_token=None,
            lease_expires_at=None,
            remote_post_id=receipt.remote_post_id,
            published_at=receipt.published_at.astimezone(UTC),
            response_payload=response,
            error_message=None,
            last_error_code=None,
        )
    )
    await session.commit()
    return _affected(result) == 1


async def record_failure(
    session: AsyncSession,
    job: PublishJob,
    lease_token: str,
    error: PublishExecutionError,
    *,
    now: datetime | None = None,
) -> bool:
    timestamp = _as_utc(now or _utc_now())
    if isinstance(error, SafeRetryError) and job.attempt_count < MAX_ATTEMPTS:
        next_status = PublishJobStatus.PENDING.value
        delay_minutes = 2 ** (job.attempt_count - 1)
        next_attempt_at = timestamp + timedelta(minutes=delay_minutes)
    elif isinstance(error, IndeterminatePublishError):
        next_status = PublishJobStatus.RECONCILE.value
        next_attempt_at = None
    else:
        next_status = PublishJobStatus.FAILED.value
        next_attempt_at = None
    result = await session.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job.id,
            PublishJob.status == PublishJobStatus.PUBLISHING.value,
            PublishJob.lease_token == lease_token,
        )
        .execution_options(synchronize_session=False)
        .values(
            status=next_status,
            next_attempt_at=next_attempt_at,
            lease_token=None,
            lease_expires_at=None,
            last_error_code=error.code,
            error_message=str(error),
        )
    )
    await session.commit()
    return _affected(result) == 1


async def _heartbeat(
    session_factory: async_sessionmaker[AsyncSession], job_id: int, lease_token: str
) -> None:
    while True:
        await asyncio.sleep(60)
        async with session_factory() as heartbeat_session:
            if not await renew_lease(heartbeat_session, job_id, lease_token):
                return


async def run_due_once(
    session_factory: async_sessionmaker[AsyncSession], adapters: Mapping[str, PublishAdapter]
) -> int:
    """Run one due attempt; a worker may call this after Studio has closed."""

    eligible_adapters = {
        platform: adapter
        for platform, adapter in adapters.items()
        if adapter.guarantees_idempotent_publish
        or getattr(adapter, "supports_safe_initial_attempt", False)
    }
    async with session_factory() as session:
        await recover_expired_leases(session)
        job = await claim_due(session, set(eligible_adapters))
    if job is None:
        return 0
    assert job.user_id is not None
    assert job.asset_id is not None
    assert job.target_account_ref is not None
    assert job.idempotency_key is not None
    assert job.lease_token is not None
    lease_token = job.lease_token
    adapter = eligible_adapters[job.platform]
    heartbeat = asyncio.create_task(_heartbeat(session_factory, job.id, lease_token))
    try:
        async with session_factory() as session:
            asset = await session.get(UploadedAsset, job.asset_id)
        if asset is None or asset.user_id != job.user_id:
            raise PermanentPublishError(
                "ASSET_UNAVAILABLE", "Scheduled asset is not owned by this user"
            )
        try:
            async with materialize_asset(asset) as path:
                target = await adapter.resolve_target(job.user_id, job.target_account_ref)
                if (
                    target.user_id != job.user_id
                    or target.platform != job.platform
                    or target.account_ref != job.target_account_ref
                    or not target.provider_account_id
                ):
                    raise PermanentPublishError(
                        "TARGET_MISMATCH", "Connected target does not belong to this account"
                    )
                receipt = await adapter.publish(job, path, target, job.idempotency_key)
        except AssetNotFoundError as exc:
            raise PermanentPublishError("ASSET_UNAVAILABLE", str(exc)) from exc
        except AssetStorageError as exc:
            raise SafeRetryError("ASSET_STORAGE_UNAVAILABLE", str(exc)) from exc
        async with session_factory() as session:
            if not await record_receipt(session, job, lease_token, target, receipt):
                logger.error("Lost lease while recording provider receipt for job %s", job.id)
    except PublishExecutionError as exc:
        async with session_factory() as session:
            await record_failure(session, job, lease_token, exc)
    except Exception:
        logger.exception("Indeterminate publish attempt for job %s", job.id)
        async with session_factory() as session:
            await record_failure(
                session,
                job,
                lease_token,
                IndeterminatePublishError(
                    "UNKNOWN_OUTCOME", "Provider outcome requires reconciliation"
                ),
            )
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
    return 1


async def reconcile_due_once(
    session_factory: async_sessionmaker[AsyncSession], adapters: Mapping[str, PublishAdapter]
) -> int:
    """Probe one uncertain remote outcome without initiating another upload."""

    reconcilable = {
        name: adapter
        for name, adapter in adapters.items()
        if callable(getattr(adapter, "reconcile", None))
    }
    if not reconcilable:
        return 0
    now = _utc_now()
    async with session_factory() as session:
        candidates = (
            (
                await session.execute(
                    select(PublishJob.id)
                    .where(
                        PublishJob.status == PublishJobStatus.RECONCILE.value,
                        PublishJob.platform.in_(reconcilable),
                        PublishJob.user_id.is_not(None),
                        PublishJob.target_account_ref.is_not(None),
                        or_(
                            PublishJob.remote_post_id.is_not(None),
                            PublishJob.provider_upload_uri_encrypted.is_not(None),
                        ),
                        or_(
                            PublishJob.next_attempt_at.is_(None), PublishJob.next_attempt_at <= now
                        ),
                    )
                    .order_by(PublishJob.id)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        job = None
        for job_id in candidates:
            claimed = await session.execute(
                update(PublishJob)
                .where(
                    PublishJob.id == job_id,
                    PublishJob.status == PublishJobStatus.RECONCILE.value,
                    or_(PublishJob.next_attempt_at.is_(None), PublishJob.next_attempt_at <= now),
                )
                .values(next_attempt_at=now + timedelta(hours=1))
            )
            await session.commit()
            if _affected(claimed) == 1:
                job = await session.get(PublishJob, job_id)
                break
    if job is None:
        return 0
    assert job.user_id is not None and job.target_account_ref is not None
    adapter = reconcilable[job.platform]
    try:
        target = await adapter.resolve_target(job.user_id, job.target_account_ref)
        receipt = await adapter.reconcile(job, target)  # type: ignore[attr-defined]
    except Exception:
        logger.exception("Reconciliation probe failed for job %s", job.id)
        return 1
    if receipt is None:
        return 1
    if (
        receipt.platform != job.platform
        or receipt.provider_account_id != target.provider_account_id
        or not receipt.remote_post_id
        or target.user_id != job.user_id
        or target.account_ref != job.target_account_ref
    ):
        logger.error("Mismatched reconciliation receipt for job %s", job.id)
        return 1
    async with session_factory() as session:
        await session.execute(
            update(PublishJob)
            .where(PublishJob.id == job.id, PublishJob.status == PublishJobStatus.RECONCILE.value)
            .values(
                status=PublishJobStatus.COMPLETE.value,
                remote_post_id=receipt.remote_post_id,
                published_at=receipt.published_at,
                response_payload=json.dumps(receipt.payload, sort_keys=True, default=str),
                provider_upload_uri_encrypted=None,
                next_attempt_at=None,
                last_error_code=None,
                error_message=None,
            )
        )
        await session.commit()
    return 1
