from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.jwt import JWTDecodeError, TokenType
from app.db.models import User
from app.deps.db import get_user_repository, get_video_repository
from app.repositories.users import UserRepository
from app.repositories.videos import VideoRepository
from app.services.auth import (
    InvalidCredentialsError,
    authenticate_user,
    issue_tokens_for_user,
    resolve_user_from_token,
)
from app.services.videos import InvalidYouTubeURL, get_video_detail, ingest_video, list_videos

SESSION_COOKIE_NAME = "admin_session"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


def _cookie_settings() -> dict[str, Any]:
    """Return cookie keyword arguments honoring environment defaults."""
    secure_default = not settings.DEBUG
    max_age = int(timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRES_MINUTES).total_seconds())
    return {
        "httponly": True,
        "secure": secure_default,
        "samesite": "lax",
        "max_age": max_age,
        "path": "/",
    }


async def _current_admin_user(
    request: Request,
    repo: UserRepository,
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        return await resolve_user_from_token(token, repo, expected_type=TokenType.ACCESS)
    except (HTTPException, JWTDecodeError):
        return None


@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, repo)
    if user:
        return RedirectResponse(url="/admin/videos", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "admin/login.html")


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    repo: UserRepository = Depends(get_user_repository),
) -> Response:
    try:
        user = await authenticate_user(email, password, repo)
    except InvalidCredentialsError:
        context = {
            "request": request,
            "error": "Invalid email or password.",
            "email": email,
        }
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            context,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    access_token, _ = issue_tokens_for_user(user, include_refresh=False)
    response = RedirectResponse(url="/admin/videos", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(SESSION_COOKIE_NAME, access_token, **_cookie_settings())
    return response


@router.post("/logout")
async def logout() -> Response:
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/videos", response_class=HTMLResponse)
async def videos_dashboard(
    request: Request,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    videos = await list_videos(video_repo)
    flash = request.query_params.get("flash")
    context = {
        "request": request,
        "user": user,
        "videos": videos,
        "flash": flash,
    }
    return templates.TemplateResponse(request, "admin/videos.html", context)


@router.get("/videos/{video_id}", response_class=HTMLResponse)
async def video_detail(
    request: Request,
    video_id: int,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    entry = await get_video_detail(video_repo, video_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    context = {
        "request": request,
        "user": user,
        "video": entry.video,
        "clip_summary": entry.clips,
    }
    return templates.TemplateResponse(request, "admin/video_detail.html", context)


@router.post("/videos/ingest")
async def ingest_from_dashboard(
    request: Request,
    youtube_url: str = Form(...),
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        await ingest_video(youtube_url, video_repo)
    except InvalidYouTubeURL as exc:
        videos = await list_videos(video_repo)
        context = {
            "request": request,
            "user": user,
            "videos": videos,
            "error": str(exc),
            "entered_url": youtube_url,
        }
        return templates.TemplateResponse(
            request,
            "admin/videos.html",
            context,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return RedirectResponse(
        url="/admin/videos?flash=Video queued for processing",
        status_code=status.HTTP_303_SEE_OTHER,
    )
