from __future__ import annotations

import logging
import signal
import sys
import time
from threading import Event

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
logger.info("Registered actors: %s", ", ".join(sorted(broker.actors.keys())))
logger.info("Declared queues: %s", ", ".join(sorted(broker.queues)) or "(none)")


def main() -> None:
    """Run the Dramatiq worker programmatically."""
    worker = Worker(broker, worker_threads=settings.WORKER_CONCURRENCY)
    stop_event = Event()

    def shutdown(signum: int, frame: object | None) -> None:  # noqa: ARG001
        if stop_event.is_set():
            return
        logger.info("Shutting down worker...", extra={"signal": signum})
        stop_event.set()
        worker.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    worker.start()
    logger.info(f"Worker started with {settings.WORKER_CONCURRENCY} threads")
    logger.info("Waiting for tasks...")

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(signal.SIGINT, None)
    finally:
        worker.join()
        logger.info("Worker stopped cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
