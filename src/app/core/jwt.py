from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


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


def create_token(*, subject: str, token_type: TokenType) -> str:
    if token_type is TokenType.ACCESS:
        expires = _build_expiration(settings.JWT_ACCESS_TOKEN_EXPIRES_MINUTES)
    else:
        expires = _build_expiration(settings.JWT_REFRESH_TOKEN_EXPIRES_MINUTES)

    payload = {
        "sub": subject,
        "type": token_type.value,
        "exp": expires,
        "iat": datetime.now(tz=UTC),
    }
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
