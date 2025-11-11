from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

_RESERVED_LOG_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


def _extract_extra(record: logging.LogRecord) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_ATTRS:
            continue
        extra[key] = value
    return extra


class AppLogFormatter(logging.Formatter):
    def __init__(self, mode: str = "medium") -> None:
        super().__init__()
        self.mode = (mode or "medium").strip().lower()

    def _timestamp(self) -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        message = record.getMessage()
        extra = _extract_extra(record)
        extra.setdefault("logger", record.name)
        extra_json = json.dumps(extra, default=str, ensure_ascii=False) if extra else ""

        if self.mode == "minimal":
            return message

        if self.mode == "full":
            event = {
                "timestamp": self._timestamp(),
                "level": record.levelname.lower(),
                "event": message,
                **extra,
            }
            if record.exc_info:
                event["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(event, default=str, ensure_ascii=False)

        # medium (default)
        level = record.levelname.upper()
        suffix = f" {extra_json}" if extra_json else ""
        return f"{level}: {message} >> {suffix}"


def _resolve_mode(mode: str | None) -> str:
    candidate = (mode or getattr(settings, "LOG_OUTPUT_MODE", "medium") or "medium").strip()
    return candidate.lower() or "medium"


def setup_logging(level: int = logging.INFO, *, mode: str | None = None) -> None:
    resolved_mode = _resolve_mode(mode)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(AppLogFormatter(mode=resolved_mode))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
