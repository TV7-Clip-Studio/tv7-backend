"""Server-side YouTube OAuth with one-use state and encrypted credentials."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import YouTubeCredential, YouTubeOAuthState

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"


class YouTubeOAuthError(RuntimeError):
    pass


def oauth_configured() -> bool:
    if not all(
        (
            settings.YOUTUBE_CLIENT_ID,
            settings.YOUTUBE_CLIENT_SECRET,
            settings.YOUTUBE_REDIRECT_URI,
            settings.YOUTUBE_TOKEN_ENCRYPTION_KEYS,
        )
    ):
        return False
    parsed = urlsplit(settings.YOUTUBE_REDIRECT_URI or "")
    production = settings.APP_ENV.lower() in {"prod", "production", "release"}
    if not (parsed.netloc and parsed.scheme in ({"https"} if production else {"http", "https"})):
        return False
    try:
        token_cipher()
    except YouTubeOAuthError:
        return False
    return True


def token_cipher() -> MultiFernet:
    keys = (settings.YOUTUBE_TOKEN_ENCRYPTION_KEYS or "").split(",")
    try:
        return MultiFernet([Fernet(key.strip()) for key in keys if key.strip()])
    except (ValueError, TypeError) as exc:
        raise YouTubeOAuthError("YouTube token encryption keys are not configured") from exc


def encrypt_secret(value: str) -> str:
    return token_cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return token_cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise YouTubeOAuthError("YouTube credential cannot be decrypted") from exc


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


async def start_authorization(session: AsyncSession, user_id: int) -> str:
    if not oauth_configured():
        raise YouTubeOAuthError("YouTube OAuth is not configured")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    session.add(
        YouTubeOAuthState(
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            user_id=user_id,
            code_verifier_encrypted=encrypt_secret(verifier),
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
        )
    )
    await session.commit()
    query = urlencode(
        {
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "redirect_uri": settings.YOUTUBE_REDIRECT_URI,
            "response_type": "code",
            "scope": f"{UPLOAD_SCOPE} {READ_SCOPE}",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTH_URL}?{query}"


async def complete_authorization(session: AsyncSession, state: str, code: str) -> YouTubeCredential:
    if not oauth_configured():
        raise YouTubeOAuthError("YouTube OAuth is not configured")
    timestamp = datetime.now(tz=UTC)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    consumed = await session.execute(
        update(YouTubeOAuthState)
        .where(
            YouTubeOAuthState.state_hash == state_hash,
            YouTubeOAuthState.consumed_at.is_(None),
            YouTubeOAuthState.expires_at > timestamp,
        )
        .values(consumed_at=timestamp)
    )
    if int(getattr(consumed, "rowcount", 0)) != 1:
        await session.rollback()
        raise YouTubeOAuthError("OAuth state is invalid, expired, or already used")
    row = await session.get(YouTubeOAuthState, state_hash)
    assert row is not None
    verifier = decrypt_secret(row.code_verifier_encrypted)
    await session.commit()  # state stays consumed even if token exchange fails
    async with _client() as client:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.YOUTUBE_CLIENT_ID,
                "client_secret": settings.YOUTUBE_CLIENT_SECRET,
                "redirect_uri": settings.YOUTUBE_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if token_response.status_code != HTTPStatus.OK:
            raise YouTubeOAuthError("Google rejected the authorization code")
        token = token_response.json()
        granted = set(str(token.get("scope", "")).split())
        if not {UPLOAD_SCOPE, READ_SCOPE}.issubset(granted):
            raise YouTubeOAuthError("YouTube upload and channel read scopes were not granted")
        access_token = str(token.get("access_token", ""))
        if not access_token:
            raise YouTubeOAuthError("Google did not return an access token")
        channel_response = await client.get(
            CHANNEL_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if channel_response.status_code != HTTPStatus.OK:
            raise YouTubeOAuthError("YouTube channel ownership could not be verified")
        channels = channel_response.json().get("items", [])
        if len(channels) != 1 or not channels[0].get("id"):
            raise YouTubeOAuthError("Exactly one YouTube channel must be available to this grant")
    channel_id = str(channels[0]["id"])
    credential = (
        await session.execute(
            select(YouTubeCredential).where(YouTubeCredential.user_id == row.user_id)
        )
    ).scalar_one_or_none()
    if credential is None:
        credential = YouTubeCredential(
            user_id=row.user_id, access_token="", refresh_token="", expires_at=timestamp
        )
        session.add(credential)
    refresh = token.get("refresh_token")
    if (
        not refresh
        and credential.token_encryption_version == 1
        and credential.channel_id == channel_id
    ):
        refresh = decrypt_secret(credential.refresh_token)
    if not refresh:
        raise YouTubeOAuthError("Google did not provide offline access; reconnect with consent")
    credential.access_token = encrypt_secret(access_token)
    credential.refresh_token = encrypt_secret(str(refresh))
    credential.token_encryption_version = 1
    credential.channel_id = channel_id
    credential.channel_title = str(channels[0].get("snippet", {}).get("title", ""))[:255]
    credential.token_type = "Bearer"
    credential.scope = " ".join(sorted(granted))
    credential.expires_at = timestamp + timedelta(seconds=int(token.get("expires_in", 3600)))
    await session.commit()
    await session.refresh(credential)
    return credential


async def access_token_for(session: AsyncSession, credential: YouTubeCredential) -> str:
    if credential.token_encryption_version != 1:
        raise YouTubeOAuthError("Legacy YouTube credentials must be reconnected")
    now = datetime.now(tz=UTC)
    expiry = credential.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry > now + timedelta(minutes=2):
        return decrypt_secret(credential.access_token)
    async with _client() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.YOUTUBE_CLIENT_ID,
                "client_secret": settings.YOUTUBE_CLIENT_SECRET,
                "refresh_token": decrypt_secret(credential.refresh_token),
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != HTTPStatus.OK or not response.json().get("access_token"):
        raise YouTubeOAuthError("YouTube authorization expired; reconnect account")
    data = response.json()
    credential.access_token = encrypt_secret(str(data["access_token"]))
    credential.expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    if data.get("refresh_token"):
        credential.refresh_token = encrypt_secret(str(data["refresh_token"]))
    await session.commit()
    return str(data["access_token"])
