from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, YouTubeCredential
from app.deps.db import get_session
from app.deps.security import require_jwt_user
from app.services.youtube_oauth import (
    YouTubeOAuthError,
    complete_authorization,
    oauth_configured,
    start_authorization,
)

router = APIRouter()


@router.post("/connect")
async def connect_youtube(
    user: User = Depends(require_jwt_user), session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    try:
        return {"authorization_url": await start_authorization(session, user.id)}
    except YouTubeOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback")
async def youtube_callback(
    state: str = Query(min_length=32, max_length=256),
    code: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    try:
        credential = await complete_authorization(session, state, code)
    except YouTubeOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert credential.channel_id is not None
    return {"channel_id": credential.channel_id, "channel_title": credential.channel_title or ""}


@router.get("/connection")
async def youtube_connection(
    user: User = Depends(require_jwt_user), session: AsyncSession = Depends(get_session)
) -> dict[str, str | bool | None]:
    credential = (
        await session.execute(select(YouTubeCredential).where(YouTubeCredential.user_id == user.id))
    ).scalar_one_or_none()
    connected = bool(
        credential and credential.token_encryption_version == 1 and credential.channel_id
    )
    return {
        "oauth_configured": oauth_configured(),
        "connected": connected,
        "channel_id": credential.channel_id if connected and credential else None,
        "channel_title": credential.channel_title if connected and credential else None,
    }


@router.delete("/connection", status_code=204)
async def disconnect_youtube(
    user: User = Depends(require_jwt_user), session: AsyncSession = Depends(get_session)
) -> None:
    credential = (
        await session.execute(select(YouTubeCredential).where(YouTubeCredential.user_id == user.id))
    ).scalar_one_or_none()
    if credential:
        await session.delete(credential)
        await session.commit()
