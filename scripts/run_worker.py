from __future__ import annotations

import logging
import signal
import sys

# IMPORTANT: Configure broker BEFORE importing tasks
from app.core.config import settings
from app.services.queue import get_broker

# Set up broker first
broker = get_broker()
print(f"Broker configured: {broker}")
print(f"Redis URL: {settings.REDIS_URL}")

# Now import tasks (actors will register with the broker we just configured)
from dramatiq import Worker  # noqa: E402

from app.services import tasks  # noqa: F401, E402

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Dramatiq worker programmatically."""
    worker = Worker(broker, worker_threads=settings.WORKER_CONCURRENCY)
    worker.start()

    def shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
        logger.info("Shutting down worker...")
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(f"Worker started with {settings.WORKER_CONCURRENCY} threads")
    logger.info("Waiting for tasks...")

    # Keep the main thread alive
    try:
        worker.join()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        worker.stop()


if __name__ == "__main__":
    main()
