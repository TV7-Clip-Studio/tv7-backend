from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    ENGINE_CLOUD_AI = "engine_cloud_ai"
    VIDEO_SOURCE = "video_source"


class JWTGenerationError(RuntimeError):
    """Raised when token generation fails."""


class JWTDecodeError(RuntimeError):
    """Raised when token decoding fails."""


def _build_expiration(delta_minutes: int) -> datetime:
    return datetime.now(tz=UTC) + timedelta(minutes=delta_minutes)


def _encode(payload: dict[str, Any]) -> str:
    try:
        return str(jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM))
    except JWTError as exc:  # pragma: no cover - jose already unit tested
        raise JWTGenerationError("Failed to generate JWT") from exc


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    scopes: list[str] | None = None,
    expires_minutes: int | None = None,
) -> str:
    if token_type is TokenType.ACCESS:
        default_expires = settings.JWT_ACCESS_TOKEN_EXPIRES_MINUTES
    elif token_type is TokenType.REFRESH:
        default_expires = settings.JWT_REFRESH_TOKEN_EXPIRES_MINUTES
    else:
        default_expires = settings.ENGINE_CLOUD_AI_TOKEN_EXPIRES_MINUTES

    expires = _build_expiration(expires_minutes or default_expires)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "exp": expires,
        "iat": datetime.now(tz=UTC),
    }
    if scopes:
        payload["scopes"] = scopes
    return _encode(payload)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:  # pragma: no cover - jose handles specifics
        raise JWTDecodeError("Failed to decode JWT") from exc

    token_type_value = payload.get("type")
    if expected_type is not None and token_type_value != expected_type.value:
        raise JWTDecodeError("Unexpected token type")

    return payload
