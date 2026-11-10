from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SocialCredential, User, YouTubeCredential
from app.deps.db import get_session
from app.deps.security import require_jwt_user
from app.services import social_oauth, youtube_oauth
from app.services.publish_adapters import youtube_local_scheduling_ready

router = APIRouter()
Platform = Literal["youtube", "instagram", "tiktok"]


@router.get("/providers")
async def providers() -> list[dict]:
    result = []
    for platform in ("youtube", "instagram", "tiktok"):
        configured = (
            youtube_oauth.oauth_configured()
            if platform == "youtube"
            else social_oauth.oauth_configured(platform)
        )
        result.append(
            {
                "platform": platform,
                "oauth_configured": configured,
                "setup_message": (
                    ""
                    if configured
                    else f"Configure {platform.title()} developer app credentials, callback URL, and token encryption in Backend."
                ),
            }
        )
    return result


@router.get("/connections")
async def connections(
    creator_profile_id: str | None = Query(default=None, max_length=80),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    youtube = select(YouTubeCredential).where(YouTubeCredential.user_id == user.id)
    social = select(SocialCredential).where(SocialCredential.user_id == user.id)
    if creator_profile_id is not None:
        youtube = youtube.where(YouTubeCredential.creator_profile_id == creator_profile_id)
        social = social.where(SocialCredential.creator_profile_id == creator_profile_id)
    result = []
    for item in (await session.execute(youtube)).scalars():
        connected = item.token_encryption_version == 1 and bool(item.channel_id)
        result.append(
            {
                "id": f"youtube:{item.id}",
                "platform": "youtube",
                "account_ref": f"youtube:{item.channel_id}",
                "display_name": item.channel_title or item.channel_id or "YouTube channel",
                "creator_profile_id": item.creator_profile_id,
                "connected": connected,
                "publishing_ready": connected and youtube_local_scheduling_ready(),
                "updated_at": item.updated_at.isoformat(),
            }
        )
    for social_item in (await session.execute(social)).scalars():
        expiry = social_item.refresh_expires_at or social_item.expires_at
        expiry = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
        result.append(
            {
                "id": f"{social_item.platform}:{social_item.id}",
                "platform": social_item.platform,
                "account_ref": f"{social_item.platform}:{social_item.provider_account_id}",
                "display_name": social_item.display_name,
                "creator_profile_id": social_item.creator_profile_id,
                "connected": expiry > datetime.now(UTC),
                "publishing_ready": False,
                "updated_at": social_item.updated_at.isoformat(),
            }
        )
    return result


@router.post("/{platform}/connect")
async def connect(
    platform: Platform,
    creator_profile_id: str = Body(embed=True, min_length=1, max_length=80),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    try:
        url = (
            await youtube_oauth.start_authorization(session, user.id, creator_profile_id)
            if platform == "youtube"
            else await social_oauth.start_authorization(
                session, user.id, platform, creator_profile_id
            )
        )
        return {"authorization_url": url}
    except (social_oauth.SocialOAuthError, youtube_oauth.YouTubeOAuthError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def completion_html(platform: str, success: bool, message: str) -> HTMLResponse:
    title = f"{platform.title()} connected" if success else "Connection could not be completed"
    return HTMLResponse(
        f"<!doctype html><html><head><meta name='viewport' content='width=device-width'><title>TV7 connection</title></head><body style='background:#101519;color:#eee;font:18px system-ui;padding:48px'><h1>{escape(title)}</h1><p>{escape(message)}</p><p>Return to TV7 Studio and choose Refresh accounts.</p></body></html>",
        status_code=200 if success else 400,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@router.get("/{platform}/callback", response_model=None)
async def callback(  # noqa: PLR0913 -- provider callback query and FastAPI dependencies
    platform: Platform,
    request: Request,
    state: str = Query(min_length=32, max_length=256),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | dict[str, str | bool]:
    if error or not code:
        if platform != "youtube":
            await social_oauth.cancel_authorization(session, platform, state)
        return completion_html(
            platform, False, "Authorization was cancelled. Return to Studio to try again."
        )
    try:
        if platform == "youtube":
            credential = await youtube_oauth.complete_authorization(session, state, code)
            name = credential.channel_title or "YouTube channel"
        else:
            social_credential = await social_oauth.complete_authorization(
                session, platform, state, code
            )
            name = social_credential.display_name
    except (social_oauth.SocialOAuthError, youtube_oauth.YouTubeOAuthError) as exc:
        return completion_html(platform, False, str(exc))
    if "text/html" in request.headers.get("accept", ""):
        return completion_html(platform, True, f"{name} is now linked to your creator profile.")
    return {"platform": platform, "connected": True, "display_name": name}


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(
    connection_id: str,
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        platform, identifier = connection_id.split(":", 1)
        key = int(identifier)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Connection not found") from exc
    item: YouTubeCredential | SocialCredential | None
    if platform == "youtube":
        item = await session.get(YouTubeCredential, key)
    elif platform in {"instagram", "tiktok"}:
        item = await session.get(SocialCredential, key)
        if isinstance(item, SocialCredential) and item.platform != platform:
            item = None
    else:
        item = None
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    await session.delete(item)
    await session.commit()
