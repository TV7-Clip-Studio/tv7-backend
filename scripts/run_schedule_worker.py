from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from app.db.base import get_engine, get_sessionmaker
from app.services.publish_adapters import configured_adapters
from app.services.publish_execution import reconcile_due_once, run_due_once
from app.services.asset_storage import validate_storage_configuration

logger = logging.getLogger(__name__)
POLL_SECONDS = 30


async def run_worker() -> None:
    validate_storage_configuration()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    logger.info("Schedule worker started; provider adapters: %s", sorted(configured_adapters()))
    try:
        while not stop.is_set():
            try:
                adapters = configured_adapters()
                await reconcile_due_once(get_sessionmaker(), adapters)
                await run_due_once(get_sessionmaker(), adapters)
            except Exception:
                logger.exception("Schedule worker iteration failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
