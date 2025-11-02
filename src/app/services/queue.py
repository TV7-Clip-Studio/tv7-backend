from __future__ import annotations

from functools import lru_cache

import dramatiq
from dramatiq import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from app.core.config import settings


@lru_cache
def get_broker() -> Broker:
    broker_type = settings.DRAMATIQ_BROKER.lower()
    if broker_type == "redis":
        broker: Broker = RedisBroker(url=settings.REDIS_URL)
    elif broker_type == "stub":
        broker = StubBroker()
    else:
        msg = f"Unsupported DRAMATIQ_BROKER value: {settings.DRAMATIQ_BROKER}"
        raise ValueError(msg)

    dramatiq.set_broker(broker)
    return broker


def ensure_broker() -> Broker:
    """Initialize the Dramatiq broker if it hasn't been set yet."""

    try:
        existing = dramatiq.get_broker()
    except RuntimeError:  # no broker configured
        existing = None

    return existing if existing is not None else get_broker()
