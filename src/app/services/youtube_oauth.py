from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.repositories.youtube_credentials import (
    CredentialTokenUpdate,
    YouTubeCredentialRepository,
)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"  # nosec B105
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # nosec B105
REFRESH_THRESHOLD = timedelta(seconds=60)


@dataclass(slots=True)
class OAuthTokens:
    access_token: str
    expires_in: int
    refresh_token: str | None
    token_type: str | None
    scope: str | None


def build_state_token(user_id: int) -> tuple[str, str]:
    state_secret = secrets.token_urlsafe(32)
    state = f"{user_id}:{state_secret}"
    return state, state_secret


def parse_state_token(state: str) -> tuple[int, str] | None:
    if not state or ":" not in state:
        return None
    user_part, secret = state.split(":", 1)
    try:
        user_id = int(user_part)
    except ValueError:
        return None
    return user_id, secret


def build_authorization_url(state: str) -> str:
    if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_REDIRECT_URI:
        raise RuntimeError("YouTube OAuth is not configured")

    params = {
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "redirect_uri": settings.YOUTUBE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.YOUTUBE_OAUTH_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_expires_in(value: object | None, default: int = 3600) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


async def _request_tokens(data: dict[str, str]) -> OAuthTokens:  # pragma: no cover - network
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
        response.raise_for_status()
    payload: dict[str, object] = response.json()
    return OAuthTokens(
        access_token=str(payload["access_token"]),
        expires_in=_coerce_expires_in(payload.get("expires_in")),
        refresh_token=_optional_str(payload.get("refresh_token")),
        token_type=_optional_str(payload.get("token_type")),
        scope=_optional_str(payload.get("scope")),
    )


async def exchange_code_for_tokens(code: str) -> OAuthTokens:  # pragma: no cover - network
    if (
        not settings.YOUTUBE_CLIENT_ID
        or not settings.YOUTUBE_CLIENT_SECRET
        or not settings.YOUTUBE_REDIRECT_URI
    ):
        raise RuntimeError("YouTube OAuth is not configured")

    data = {
        "code": code,
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "client_secret": settings.YOUTUBE_CLIENT_SECRET,
        "redirect_uri": settings.YOUTUBE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    return await _request_tokens(data)


async def refresh_access_token(refresh_token: str) -> OAuthTokens:  # pragma: no cover - network
    if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
        raise RuntimeError("YouTube OAuth is not configured")

    data = {
        "refresh_token": refresh_token,
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "client_secret": settings.YOUTUBE_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    return await _request_tokens(data)


async def get_valid_access_token(  # pragma: no cover - network dependent
    user_id: int,
    repo: YouTubeCredentialRepository,
) -> str | None:
    credential = await repo.get_by_user_id(user_id)
    if credential is None:
        return None

    now = datetime.now(tz=UTC)
    if credential.expires_at - now > REFRESH_THRESHOLD:
        return str(credential.access_token)

    refreshed = await refresh_access_token(credential.refresh_token)
    expires_at = now + timedelta(seconds=refreshed.expires_in)
    update_data = CredentialTokenUpdate(
        access_token=refreshed.access_token,
        expires_at=expires_at,
        refresh_token=refreshed.refresh_token,
        scope=refreshed.scope,
        token_type=refreshed.token_type,
    )
    updated = await repo.update_tokens(credential, update_data)
    return str(updated.access_token)
