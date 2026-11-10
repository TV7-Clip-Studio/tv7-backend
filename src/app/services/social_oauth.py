"""Profile-bound social OAuth. Provider tokens never leave Backend."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SocialCredential, SocialOAuthState

SCOPES = {
    "instagram": {"instagram_business_basic", "instagram_business_content_publish"},
    "tiktok": {"user.info.basic", "video.publish"},
}


class SocialOAuthError(RuntimeError):
    pass


def cipher() -> MultiFernet:
    try:
        keys = settings.SOCIAL_TOKEN_ENCRYPTION_KEYS or settings.YOUTUBE_TOKEN_ENCRYPTION_KEYS or ""
        return MultiFernet([Fernet(key.strip()) for key in keys.split(",") if key.strip()])
    except (TypeError, ValueError) as exc:
        raise SocialOAuthError("Social token encryption is not configured") from exc


def provider_config(platform: str) -> tuple[str | None, str | None, str | None]:
    if platform == "instagram":
        return (
            settings.INSTAGRAM_CLIENT_ID,
            settings.INSTAGRAM_CLIENT_SECRET,
            settings.INSTAGRAM_REDIRECT_URI,
        )
    if platform == "tiktok":
        return (
            settings.TIKTOK_CLIENT_KEY,
            settings.TIKTOK_CLIENT_SECRET,
            settings.TIKTOK_REDIRECT_URI,
        )
    raise SocialOAuthError("Unsupported social platform")


def oauth_configured(platform: str) -> bool:
    client_id, secret, redirect = provider_config(platform)
    parsed = urlsplit(redirect or "")
    production = settings.APP_ENV.lower() in {"prod", "production", "release"}
    if not all((client_id, secret, redirect, parsed.netloc)) or parsed.scheme not in (
        {"https"} if production else {"http", "https"}
    ):
        return False
    try:
        cipher()
    except SocialOAuthError:
        return False
    return True


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30)


async def start_authorization(
    session: AsyncSession, user_id: int, platform: str, profile_id: str
) -> str:
    if not oauth_configured(platform):
        raise SocialOAuthError(f"{platform.title()} OAuth is not configured")
    client_id, _, redirect = provider_config(platform)
    state = secrets.token_urlsafe(32)
    session.add(
        SocialOAuthState(
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            user_id=user_id,
            platform=platform,
            creator_profile_id=profile_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await session.commit()
    query = {
        "redirect_uri": redirect,
        "response_type": "code",
        "state": state,
        "scope": ",".join(sorted(SCOPES[platform])),
    }
    if platform == "instagram":
        query.update({"client_id": client_id, "enable_fb_login": "0", "force_authentication": "1"})
        return "https://www.instagram.com/oauth/authorize?" + urlencode(query)
    query["client_key"] = client_id
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(query)


def _checked(response: httpx.Response, message: str) -> dict:
    if response.status_code != HTTPStatus.OK:
        raise SocialOAuthError(message)
    data = response.json()
    if not isinstance(data, dict):
        raise SocialOAuthError(message)
    error = data.get("error")
    if error and (not isinstance(error, dict) or error.get("code") != "ok"):
        raise SocialOAuthError(message)
    return data


async def _exchange(platform: str, code: str) -> tuple[dict, str, str]:
    client_id, secret, redirect = provider_config(platform)
    async with _client() as client:
        if platform == "tiktok":
            token = _checked(
                await client.post(
                    "https://open.tiktokapis.com/v2/oauth/token/",
                    data={
                        "client_key": client_id,
                        "client_secret": secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect,
                    },
                ),
                "TikTok rejected authorization",
            )
            if not SCOPES[platform].issubset(set(str(token.get("scope", "")).split(","))):
                raise SocialOAuthError(
                    "TikTok identity and publishing permissions were not granted"
                )
            identity = (
                _checked(
                    await client.get(
                        "https://open.tiktokapis.com/v2/user/info/",
                        params={"fields": "open_id,display_name"},
                        headers={"Authorization": f"Bearer {token.get('access_token', '')}"},
                    ),
                    "TikTok account identity could not be verified",
                )
                .get("data", {})
                .get("user", {})
            )
            account_id = str(identity.get("open_id", ""))
            if (
                not account_id
                or account_id != token.get("open_id")
                or not token.get("refresh_token")
            ):
                raise SocialOAuthError("TikTok account identity or offline access is missing")
            return token, account_id, str(identity.get("display_name") or account_id)
        short = _checked(
            await client.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect,
                },
            ),
            "Instagram rejected authorization",
        )
        if isinstance(short.get("data"), list):
            records = short["data"]
            if len(records) != 1 or not isinstance(records[0], dict):
                raise SocialOAuthError("Instagram returned an ambiguous authorization")
            short = records[0]
        # Instagram returns the granted permission names with the short-lived token.
        granted = short.get("permissions", [])
        if isinstance(granted, str):
            granted = granted.split(",")
        if not SCOPES[platform].issubset(set(granted)):
            raise SocialOAuthError("Instagram identity and publishing permissions were not granted")
        token = _checked(
            await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": secret,
                    "access_token": short.get("access_token", ""),
                },
            ),
            "Instagram offline token exchange failed",
        )
        identity = _checked(
            await client.get(
                f"https://graph.instagram.com/{settings.INSTAGRAM_API_VERSION}/me",
                params={
                    "fields": "user_id,username",
                    "access_token": token.get("access_token", ""),
                },
            ),
            "Instagram account identity could not be verified",
        )
        account_id = str(identity.get("user_id") or "")
        if not account_id or account_id != str(short.get("user_id", "")):
            raise SocialOAuthError("Instagram account identity mismatch")
        token["scope"] = ",".join(sorted(granted))
        return token, account_id, str(identity.get("username") or account_id)


async def complete_authorization(
    session: AsyncSession, platform: str, state: str, code: str
) -> SocialCredential:
    if not oauth_configured(platform):
        raise SocialOAuthError(f"{platform.title()} OAuth is not configured")
    now = datetime.now(UTC)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    consumed = await session.execute(
        update(SocialOAuthState)
        .where(
            SocialOAuthState.state_hash == state_hash,
            SocialOAuthState.platform == platform,
            SocialOAuthState.consumed_at.is_(None),
            SocialOAuthState.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if int(getattr(consumed, "rowcount", 0)) != 1:
        await session.rollback()
        raise SocialOAuthError("OAuth state is invalid, expired, or already used")
    row = await session.get(SocialOAuthState, state_hash)
    assert row is not None
    user_id, profile_id = row.user_id, row.creator_profile_id
    await session.commit()
    try:
        token, account_id, display_name = await _exchange(platform, code)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise SocialOAuthError("Social provider authorization failed; reconnect") from exc
    if not token.get("access_token"):
        raise SocialOAuthError("Provider did not return an access token")
    existing = (
        await session.execute(
            select(SocialCredential).where(
                SocialCredential.platform == platform,
                SocialCredential.provider_account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if existing and (existing.user_id != user_id or existing.creator_profile_id != profile_id):
        raise SocialOAuthError(
            "This social account is already linked to a different account or profile"
        )
    credential = existing or SocialCredential(
        user_id=user_id,
        platform=platform,
        provider_account_id=account_id,
        creator_profile_id=profile_id,
    )
    credential.updated_at = now
    credential.display_name = display_name[:255]
    credential.access_token_encrypted = (
        cipher().encrypt(str(token["access_token"]).encode()).decode()
    )
    credential.refresh_token_encrypted = (
        cipher().encrypt(str(token["refresh_token"]).encode()).decode()
        if token.get("refresh_token")
        else None
    )
    credential.scope = str(token["scope"])
    credential.expires_at = now + timedelta(seconds=int(token.get("expires_in", 3600)))
    credential.refresh_expires_at = (
        now + timedelta(seconds=int(token["refresh_expires_in"]))
        if token.get("refresh_expires_in")
        else None
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return credential


async def access_token_for(session: AsyncSession, credential: SocialCredential) -> str:
    """Refresh tokens on demand; publishing workers can use this server-side helper."""
    now = datetime.now(UTC)
    expiry = credential.expires_at
    expiry = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
    access = cipher().decrypt(credential.access_token_encrypted.encode()).decode()
    if expiry > now + timedelta(minutes=2):
        return access
    client_id, secret, _ = provider_config(credential.platform)
    async with _client() as client:
        if credential.platform == "tiktok" and credential.refresh_token_encrypted:
            refresh = cipher().decrypt(credential.refresh_token_encrypted.encode()).decode()
            token = _checked(
                await client.post(
                    "https://open.tiktokapis.com/v2/oauth/token/",
                    data={
                        "client_key": client_id,
                        "client_secret": secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                    },
                ),
                "TikTok authorization expired; reconnect",
            )
            if token.get("open_id") != credential.provider_account_id:
                raise SocialOAuthError(
                    "TikTok refreshed identity does not match the connected account"
                )
        elif credential.platform == "instagram":
            token = _checked(
                await client.get(
                    "https://graph.instagram.com/refresh_access_token",
                    params={"grant_type": "ig_refresh_token", "access_token": access},
                ),
                "Instagram authorization expired; reconnect",
            )
        else:
            raise SocialOAuthError("Social authorization expired; reconnect")
    if not token.get("access_token"):
        raise SocialOAuthError("Social authorization expired; reconnect")
    credential.access_token_encrypted = (
        cipher().encrypt(str(token["access_token"]).encode()).decode()
    )
    if token.get("refresh_token"):
        credential.refresh_token_encrypted = (
            cipher().encrypt(str(token["refresh_token"]).encode()).decode()
        )
    credential.expires_at = now + timedelta(seconds=int(token.get("expires_in", 3600)))
    if token.get("refresh_expires_in"):
        credential.refresh_expires_at = now + timedelta(seconds=int(token["refresh_expires_in"]))
    await session.commit()
    return str(token["access_token"])


async def cancel_authorization(session: AsyncSession, platform: str, state: str) -> None:
    await session.execute(
        update(SocialOAuthState)
        .where(
            SocialOAuthState.state_hash == hashlib.sha256(state.encode()).hexdigest(),
            SocialOAuthState.platform == platform,
            SocialOAuthState.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    await session.commit()
