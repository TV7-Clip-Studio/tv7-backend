from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import Clip, PublishJob, PublishJobStatus, User, Video
from app.deps.db import get_session
from app.repositories.publish_jobs import PublishJobRepository
from app.repositories.users import UserRepository

SESSION_COOKIE = "admin_session"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


class ScheduleEntryUpdateForm(BaseModel):
    status_value: str
    asset_url: str | None = None
    response_payload: str | None = None
    error_message: str | None = None

    @classmethod
    def as_form(
        cls,
        status_value: str = Form(...),
        asset_url: str | None = Form(None),
        response_payload: str | None = Form(None),
        error_message: str | None = Form(None),
    ) -> ScheduleEntryUpdateForm:
        return cls(
            status_value=status_value,
            asset_url=asset_url,
            response_payload=response_payload,
            error_message=error_message,
        )


def _cookie_settings() -> dict[str, Any]:
    secure_default = not settings.DEBUG
    max_age = settings.JWT_ACCESS_TOKEN_EXPIRES_MINUTES * 60
    return {
        "httponly": True,
        "secure": secure_default,
        "samesite": "lax",
        "max_age": max_age,
        "path": "/",
    }


def _ensure_admin_credentials() -> tuple[str, str]:
    username = settings.ADMIN_USERNAME
    password = settings.ADMIN_PASSWORD
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin credentials are not configured",
        )
    return username, password


def _issue_admin_token(username: str) -> str:
    expires = datetime.now(tz=UTC) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRES_MINUTES)
    payload = {
        "sub": username,
        "role": "admin",
        "type": "admin_session",
        "exp": expires,
        "iat": datetime.now(tz=UTC),
    }
    try:
        return str(jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM))
    except JWTError as exc:  # pragma: no cover - jose error paths
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to issue token"
        ) from exc


def _validate_admin_token(token: str) -> str:
    expected_username, _ = _ensure_admin_credentials()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin session"
        ) from exc

    if payload.get("role") != "admin" or payload.get("sub") != expected_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin session"
        )
    return expected_username


def _require_admin(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _validate_admin_token(token)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    try:
        _require_admin(request)
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    except HTTPException:
        pass
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"request": request, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    expected_username, expected_password = _ensure_admin_credentials()
    if username != expected_username or password != expected_password:
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "request": request,
                "error": "Invalid credentials",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = _issue_admin_token(username)
    response = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(SESSION_COOKIE, token, **_cookie_settings())
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/", include_in_schema=False)
async def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    try:
        admin_user = _require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    counts = {}
    counts["users"] = await session.scalar(select(func.count()).select_from(User)) or 0
    counts["videos"] = await session.scalar(select(func.count()).select_from(Video)) or 0
    counts["clips"] = await session.scalar(select(func.count()).select_from(Clip)) or 0
    counts["publish_jobs"] = await session.scalar(select(func.count()).select_from(PublishJob)) or 0

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "request": request,
            "admin_user": admin_user,
            "counts": counts,
        },
    )


@router.get("/schedule", response_class=HTMLResponse)
async def view_schedule(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        admin_user = _require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    stmt = (
        select(PublishJob)
        .options(selectinload(PublishJob.clip).selectinload(Clip.video))
        .order_by(PublishJob.created_at.desc())
        .limit(100)
    )
    jobs = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request,
        "admin/schedule.html",
        {
            "request": request,
            "admin_user": admin_user,
            "jobs": jobs,
            "statuses": list(PublishJobStatus),
        },
    )


@router.post("/schedule/{job_id}", response_class=HTMLResponse)
async def update_schedule_entry(
    job_id: int,
    request: Request,
    form: ScheduleEntryUpdateForm = Depends(ScheduleEntryUpdateForm.as_form),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        _require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    repo = PublishJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        new_status = PublishJobStatus(form.status_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status"
        ) from None

    job.status = new_status.value
    job.asset_url = form.asset_url or job.asset_url
    job.response_payload = form.response_payload
    job.error_message = form.error_message
    await repo.commit()

    return RedirectResponse(url="/admin/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        admin_user = _require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user_repo = UserRepository(session)
    users = await user_repo.list_users()

    video_counts = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Video.requested_by_user_id, func.count())
                .where(Video.requested_by_user_id.isnot(None))
                .group_by(Video.requested_by_user_id)
            )
        ).all()
    }
    clip_counts = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Video.requested_by_user_id, func.count())
                .join(Clip, Clip.video_id == Video.id)
                .where(Video.requested_by_user_id.isnot(None))
                .group_by(Video.requested_by_user_id)
            )
        ).all()
    }
    publish_counts = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Video.requested_by_user_id, func.count())
                .join(Clip, Clip.video_id == Video.id)
                .join(PublishJob, PublishJob.clip_id == Clip.id)
                .where(Video.requested_by_user_id.isnot(None))
                .group_by(Video.requested_by_user_id)
            )
        ).all()
    }

    user_stats: list[dict[str, Any]] = []
    for user in users:
        user_stats.append(
            {
                "user": user,
                "videos": video_counts.get(user.id, 0),
                "clips": clip_counts.get(user.id, 0),
                "publish_jobs": publish_counts.get(user.id, 0),
            }
        )

    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "request": request,
            "admin_user": admin_user,
            "user_stats": user_stats,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        admin_user = _require_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    user_repo = UserRepository(session)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    videos_count = await session.scalar(
        select(func.count()).select_from(Video).where(Video.requested_by_user_id == user_id)
    )
    clips_count = await session.scalar(
        select(func.count())
        .select_from(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Video.requested_by_user_id == user_id)
    )
    publish_count = await session.scalar(
        select(func.count())
        .select_from(PublishJob)
        .join(Clip, PublishJob.clip_id == Clip.id)
        .join(Video, Clip.video_id == Video.id)
        .where(Video.requested_by_user_id == user_id)
    )

    stmt = (
        select(Video)
        .options(selectinload(Video.clips))
        .where(Video.requested_by_user_id == user_id)
        .order_by(Video.created_at.desc())
        .limit(10)
    )
    recent_videos = (await session.execute(stmt)).scalars().unique().all()

    return templates.TemplateResponse(
        request,
        "admin/user_detail.html",
        {
            "request": request,
            "admin_user": admin_user,
            "user": user,
            "stats": {
                "videos": videos_count or 0,
                "clips": clips_count or 0,
                "publish_jobs": publish_count or 0,
            },
            "videos": recent_videos,
        },
    )
