from __future__ import annotations

import dramatiq
from dramatiq import Broker
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import (
    AgeLimit,
    Callbacks,
    Pipelines,
    Retries,
    ShutdownNotifications,
    TimeLimit,
)

from app.core.config import settings

_broker: Broker | None = None
_DEFAULT_MIDDLEWARE = [
    AgeLimit(),
    TimeLimit(),
    Callbacks(),
    ShutdownNotifications(),
    Pipelines(),
    Retries(),
]


def _build_broker() -> Broker:
    broker_type = settings.DRAMATIQ_BROKER.lower()
    middleware = list(_DEFAULT_MIDDLEWARE)

    if broker_type == "redis":
        return RedisBroker(url=settings.REDIS_URL, middleware=middleware)
    if broker_type == "stub":
        return StubBroker(middleware=middleware)

    msg = f"Unsupported DRAMATIQ_BROKER value: {settings.DRAMATIQ_BROKER}"
    raise ValueError(msg)


def get_broker() -> Broker:
    global _broker  # noqa: PLW0603
    if _broker is None:
        _broker = _build_broker()
        dramatiq.set_broker(_broker)
    return _broker


def ensure_broker() -> Broker:
    """Initialize the Dramatiq broker if it hasn't been set yet."""

    try:
        existing = dramatiq.get_broker()
    except RuntimeError:  # no broker configured
        existing = None

    return existing if existing is not None else get_broker()
