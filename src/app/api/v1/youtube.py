from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.social import completion_html
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
    creator_profile_id: str | None = Body(default=None, embed=True, min_length=1, max_length=80),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if creator_profile_id is None and await _connections(session, user.id):
        raise HTTPException(
            status_code=422, detail="creator_profile_id is required for another YouTube connection"
        )
    try:
        return {
            "authorization_url": await start_authorization(session, user.id, creator_profile_id)
        }
    except YouTubeOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback", response_model=None)
async def youtube_callback(
    request: Request,
    state: str = Query(min_length=32, max_length=256),
    code: str | None = Query(default=None, min_length=1, max_length=4096),
    error: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | dict[str, str]:
    if error or not code:
        return completion_html(
            "youtube", False, "Authorization was cancelled. Return to Studio to try again."
        )
    try:
        credential = await complete_authorization(session, state, code)
    except YouTubeOAuthError as exc:
        if "text/html" in request.headers.get("accept", ""):
            return completion_html("youtube", False, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "text/html" in request.headers.get("accept", ""):
        return completion_html(
            "youtube",
            True,
            f"{credential.channel_title or 'YouTube channel'} is now linked to your creator profile.",
        )
    assert credential.channel_id is not None
    return {
        "channel_id": credential.channel_id,
        "channel_title": credential.channel_title or "",
        "creator_profile_id": credential.creator_profile_id or "",
    }


async def _connections(session: AsyncSession, user_id: int) -> list[YouTubeCredential]:
    return list(
        (
            await session.execute(
                select(YouTubeCredential)
                .where(YouTubeCredential.user_id == user_id)
                .order_by(YouTubeCredential.id)
            )
        )
        .scalars()
        .all()
    )


async def _selected_connection(
    session: AsyncSession, user_id: int, account_ref: str | None
) -> YouTubeCredential | None:
    connections = await _connections(session, user_id)
    if account_ref is not None:
        selected = next(
            (
                item
                for item in connections
                if item.channel_id and account_ref == f"youtube:{item.channel_id}"
            ),
            None,
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="YouTube account not connected")
        return selected
    if len(connections) > 1:
        raise HTTPException(status_code=409, detail="Select a YouTube account_ref")
    return connections[0] if connections else None


def _connection_read(credential: YouTubeCredential) -> dict[str, str | bool | None]:
    connected = bool(credential.token_encryption_version == 1 and credential.channel_id)
    return {
        "connected": connected,
        "channel_id": credential.channel_id if connected else None,
        "channel_title": credential.channel_title if connected else None,
        "creator_profile_id": credential.creator_profile_id if connected else None,
        "account_ref": f"youtube:{credential.channel_id}" if connected else None,
    }


@router.get("/connections")
async def youtube_connections(
    user: User = Depends(require_jwt_user), session: AsyncSession = Depends(get_session)
) -> list[dict[str, str | bool | None]]:
    return [_connection_read(item) for item in await _connections(session, user.id)]


@router.get("/connection")
async def youtube_connection(
    account_ref: str | None = Query(default=None),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str | bool | None]:
    credential = await _selected_connection(session, user.id, account_ref)
    return {
        "oauth_configured": oauth_configured(),
        **(
            _connection_read(credential)
            if credential
            else {
                "connected": False,
                "channel_id": None,
                "channel_title": None,
                "creator_profile_id": None,
                "account_ref": None,
            }
        ),
    }


@router.put("/connection/profile")
async def assign_youtube_profile(
    creator_profile_id: str = Body(embed=True, min_length=1, max_length=80),
    account_ref: str | None = Query(default=None),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    credential = await _selected_connection(session, user.id, account_ref)
    if credential is None or credential.token_encryption_version != 1 or not credential.channel_id:
        raise HTTPException(status_code=404, detail="YouTube account not connected")
    credential.creator_profile_id = creator_profile_id
    await session.commit()
    return {
        "creator_profile_id": creator_profile_id,
        "account_ref": f"youtube:{credential.channel_id}",
    }


@router.delete("/connection", status_code=204)
async def disconnect_youtube(
    account_ref: str | None = Query(default=None),
    user: User = Depends(require_jwt_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    credential = await _selected_connection(session, user.id, account_ref)
    if credential:
        await session.delete(credential)
        await session.commit()


# Keep existing registered Google redirect URIs usable during the connection UI migration.
legacy_callback_router = APIRouter()
legacy_callback_router.add_api_route(
    "/admin/youtube/callback",
    youtube_callback,
    methods=["GET"],
    response_model=None,
    include_in_schema=False,
)
