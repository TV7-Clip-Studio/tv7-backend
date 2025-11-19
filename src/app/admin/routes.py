from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote_plus

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import settings
from app.core.jwt import JWTDecodeError, TokenType
from app.db.models import ClipGenerationMode, User
from app.deps.db import (
    get_user_repository,
    get_video_repository,
    get_youtube_credential_repository,
)
from app.repositories.users import UserRepository
from app.repositories.videos import VideoRepository
from app.repositories.youtube_credentials import (
    CredentialTokenData,
    YouTubeCredentialRepository,
)
from app.schemas import VideoRead
from app.services.auth import (
    InvalidCredentialsError,
    authenticate_user,
    issue_tokens_for_user,
    resolve_user_from_token,
)
from app.services.storage import delete_video_media
from app.services.upload_storage import (
    UploadError,
    UploadTooLargeError,
    persist_upload_temporarily,
)
from app.services.users import (
    CannotDeleteCurrentUserError,
    UserNotFoundError,
    delete_user,
    list_users,
    update_user_status,
)
from app.services.users import (
    get_user_detail as get_user_detail_service,
)
from app.services.videos import (
    InvalidYouTubeURL,
    UploadIngestError,
    get_video_detail,
    ingest_uploaded_video,
    ingest_video,
    list_videos,
)
from app.services.youtube_oauth import (
    build_authorization_url,
    build_state_token,
    exchange_code_for_tokens,
    parse_state_token,
)

SESSION_COOKIE_NAME = "admin_session"
YOUTUBE_STATE_COOKIE = "youtube_oauth_state"
REQUIRED_YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


class YouTubeCallbackParams(BaseModel):
    state: str | None = None
    code: str | None = None
    error: str | None = None


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


def _oauth_cookie_settings() -> dict[str, Any]:
    secure_default = not settings.DEBUG
    return {
        "httponly": True,
        "secure": secure_default,
        "samesite": "lax",
        "max_age": 600,
        "path": "/",
    }


def _youtube_oauth_configured() -> bool:
    return bool(settings.YOUTUBE_CLIENT_ID and settings.YOUTUBE_CLIENT_SECRET)


def _redirect_with_message(
    path: str, message: str | None = None, *, error: bool = False
) -> RedirectResponse:
    if message:
        key = "error" if error else "flash"
        path = f"{path}?{key}={quote_plus(message)}"
    return RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)


async def _build_dashboard_context(
    request: Request,
    user: User,
    video_repo: VideoRepository,
    credential_repo: YouTubeCredentialRepository,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    videos = await list_videos(video_repo)
    youtube_connected = False
    youtube_scope_missing = False
    if _youtube_oauth_configured():
        connected, scope_ok = await _youtube_connection_state(user.id, credential_repo)
        youtube_connected = connected and scope_ok
        youtube_scope_missing = connected and not scope_ok

    context = {
        "request": request,
        "user": user,
        "videos": videos,
        "youtube_connected": youtube_connected,
        "youtube_scope_missing": youtube_scope_missing,
        "youtube_oauth_configured": _youtube_oauth_configured(),
    }
    if extras:
        context.update(extras)
    return context


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


async def _youtube_connection_state(
    user_id: int, credential_repo: YouTubeCredentialRepository
) -> tuple[bool, bool]:
    credential = await credential_repo.get_by_user_id(user_id)
    if not credential:
        return False, False
    scope_ok = _credential_has_required_scope(credential.scope)
    return True, scope_ok


def _credential_has_required_scope(scope: str | None) -> bool:
    if not scope:
        return False
    granted = {value.strip() for value in scope.split() if value.strip()}
    return REQUIRED_YOUTUBE_SCOPE in granted


def _error_result(message: str) -> _CallbackResult:
    return _CallbackResult(message=message, error=True)


async def _process_youtube_callback(
    params: YouTubeCallbackParams,
    *,
    stored_state: str | None,
    user_repo: UserRepository,
    credential_repo: YouTubeCredentialRepository,
) -> _CallbackResult:
    try:
        if params.error:
            raise _CallbackError(f"YouTube authentication failed: {params.error}")
        if not params.state or not stored_state:
            raise _CallbackError("Missing OAuth state.")

        parsed = parse_state_token(params.state)
        if not parsed:
            raise _CallbackError("Invalid OAuth state.")

        user_id, provided_secret = parsed
        if provided_secret != stored_state:
            raise _CallbackError("OAuth state mismatch.")

        user = await user_repo.get_by_id(user_id)
        if not user:
            raise _CallbackError("User not found for OAuth callback.")

        if not params.code:
            raise _CallbackError("Authorization code missing.")

        tokens = await exchange_code_for_tokens(params.code)

        if not tokens.refresh_token:
            raise _CallbackError("Google did not provide a refresh token. Please try again.")

        expires_at = datetime.now(tz=UTC) + timedelta(seconds=tokens.expires_in)
        token_data = CredentialTokenData(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=expires_at,
            scope=tokens.scope,
            token_type=tokens.token_type,
        )
        await credential_repo.upsert(user_id=user.id, data=token_data)
        return _CallbackResult("YouTube account connected.")
    except _CallbackError as exc:
        return _error_result(exc.message)
    except Exception as exc:  # pragma: no cover - network errors
        return _error_result(f"Failed to exchange code: {exc}")


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


@router.get("/youtube/connect")
async def youtube_connect(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    if not _youtube_oauth_configured():
        return _redirect_with_message(
            "/admin/videos", "YouTube OAuth is not configured.", error=True
        )
    state, secret = build_state_token(user.id)
    auth_url = build_authorization_url(state)
    response = RedirectResponse(url=auth_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(YOUTUBE_STATE_COOKIE, secret, **_oauth_cookie_settings())
    return response


@router.get("/youtube/callback")
async def youtube_callback(
    request: Request,
    params: Annotated[YouTubeCallbackParams, Depends()],
    user_repo: UserRepository = Depends(get_user_repository),
    credential_repo: YouTubeCredentialRepository = Depends(get_youtube_credential_repository),
) -> Response:
    result = await _process_youtube_callback(
        params,
        stored_state=request.cookies.get(YOUTUBE_STATE_COOKIE),
        user_repo=user_repo,
        credential_repo=credential_repo,
    )
    response = _redirect_with_message("/admin/videos", result.message, error=result.error)
    response.delete_cookie(YOUTUBE_STATE_COOKIE, path="/")
    return response


@router.post("/youtube/disconnect")
async def youtube_disconnect(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    credential_repo: YouTubeCredentialRepository = Depends(get_youtube_credential_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    await credential_repo.delete_for_user(user.id)
    return _redirect_with_message("/admin/videos", "YouTube account disconnected.")


@router.get("/videos", response_class=HTMLResponse)
async def videos_dashboard(
    request: Request,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    credential_repo: YouTubeCredentialRepository = Depends(get_youtube_credential_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    flash = request.query_params.get("flash")
    error = request.query_params.get("error")
    ingest_mode = request.query_params.get("ingest_mode")
    extras = {
        key: value
        for key, value in {
            "flash": flash,
            "error": error,
            "ingest_mode": ingest_mode,
        }.items()
        if value
    }
    context = await _build_dashboard_context(
        request,
        user,
        video_repo,
        credential_repo,
        extras=extras or None,
    )
    return templates.TemplateResponse(request, "admin/videos.html", context)


@router.get("/videos/{video_id}", response_class=HTMLResponse)
async def video_detail(
    request: Request,
    video_id: int,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    credential_repo: YouTubeCredentialRepository = Depends(get_youtube_credential_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    entry = await get_video_detail(video_repo, video_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    youtube_connected = False
    youtube_scope_missing = False
    if _youtube_oauth_configured():
        connected, scope_ok = await _youtube_connection_state(user.id, credential_repo)
        youtube_connected = connected and scope_ok
        youtube_scope_missing = connected and not scope_ok
    context = {
        "request": request,
        "user": user,
        "video": entry.video,
        "clip_summary": entry.clips,
        "youtube_connected": youtube_connected,
        "youtube_scope_missing": youtube_scope_missing,
        "youtube_oauth_configured": _youtube_oauth_configured(),
    }
    return templates.TemplateResponse(request, "admin/video_detail.html", context)


@router.get("/videos/{video_id}/status")
async def video_status_json(
    request: Request,
    video_id: int,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> JSONResponse:
    user = await _current_admin_user(request, user_repo)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    video = await video_repo.get_with_clips(video_id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    payload = VideoRead.model_validate(video, from_attributes=True)
    return JSONResponse(payload.model_dump(mode="json"))


@router.post("/videos/ingest")
async def ingest_from_dashboard(
    request: Request,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    credential_repo: YouTubeCredentialRepository = Depends(get_youtube_credential_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    ingest_mode = str(form.get("ingest_mode") or "youtube").lower()

    async def _ingest_error(message: str, *, mode: str, entered_url: str | None = None) -> Response:
        extras = {"error": message, "ingest_mode": mode}
        if entered_url:
            extras["entered_url"] = entered_url
        context = await _build_dashboard_context(
            request,
            user,
            video_repo,
            credential_repo,
            extras=extras,
        )
        return templates.TemplateResponse(
            request,
            "admin/videos.html",
            context,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    response: Response
    if ingest_mode == "upload":
        upload_file = form.get("upload_file")
        if not isinstance(upload_file, StarletteUploadFile) or not upload_file.filename:
            return await _ingest_error("Select a video file to upload.", mode="upload")
        try:
            stored = await persist_upload_temporarily(upload_file)
            await ingest_uploaded_video(
                stored,
                video_repo,
                requested_by_user_id=user.id,
            )
        except UploadTooLargeError as exc:
            response = await _ingest_error(str(exc), mode="upload")
        except (UploadError, UploadIngestError) as exc:
            response = await _ingest_error(str(exc), mode="upload")
        else:
            response = _redirect_with_message("/admin/videos", "Upload queued for processing")
    else:
        youtube_url = str(form.get("youtube_url") or "").strip()
        if not youtube_url:
            return await _ingest_error("Enter a YouTube URL.", mode="youtube")
        try:
            await ingest_video(youtube_url, video_repo, requested_by_user_id=user.id)
        except InvalidYouTubeURL as exc:
            response = await _ingest_error(str(exc), mode="youtube", entered_url=youtube_url)
        else:
            response = _redirect_with_message("/admin/videos", "Video queued for processing")

    return response


@router.post("/videos/{video_id}/delete")
async def delete_video(
    request: Request,
    video_id: int,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    video = await video_repo.get_with_clips(video_id)
    if not video:
        return RedirectResponse(
            url="/admin/videos?error=Video%20not%20found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    clip_ids = [clip.id for clip in video.clips]

    await video_repo.delete(video_id)
    await _delete_video_media_async(video_id, clip_ids)

    return RedirectResponse(
        url="/admin/videos?flash=Video%20deleted%20successfully",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _delete_video_media_async(video_id: int, clip_ids: list[int]) -> None:
    await anyio.to_thread.run_sync(
        delete_video_media,
        video_id,
        clip_ids,
        cancellable=False,
    )


@router.post("/videos/{video_id}/more-highlights")
async def request_more_highlights(
    request: Request,
    video_id: int,
    video_repo: VideoRepository = Depends(get_video_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    video = await video_repo.get(video_id)
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    await ingest_video(
        video.source_url,
        video_repo,
        requested_by_user_id=user.id,
        clip_mode=ClipGenerationMode.APPEND,
    )
    return _redirect_with_message(
        f"/admin/videos/{video_id}", "Requested additional highlights. Queueing now."
    )


@router.get("/users", response_class=HTMLResponse)
async def users_dashboard(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    users = await list_users(user_repo)
    flash = request.query_params.get("flash")
    context = {
        "request": request,
        "user": user,
        "users": users,
        "flash": flash,
    }
    return templates.TemplateResponse(request, "admin/users.html", context)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail_page(
    request: Request,
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    current_user = await _current_admin_user(request, user_repo)
    if not current_user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        detail_user = await get_user_detail_service(user_repo, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    context = {
        "request": request,
        "user": current_user,
        "detail_user": detail_user,
        "is_current_user": current_user.id == detail_user.id,
    }
    return templates.TemplateResponse(request, "admin/user_detail.html", context)


@router.post("/users/{user_id}/toggle-status")
async def toggle_user_status(
    request: Request,
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    user = await _current_admin_user(request, user_repo)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        detail_user = await get_user_detail_service(user_repo, user_id)
        # Toggle the status
        new_status = not detail_user.is_active
        await update_user_status(user_id, new_status, user_repo)
        status_text = "activated" if new_status else "deactivated"
        return RedirectResponse(
            url=f"/admin/users/{user_id}?flash=User {status_text} successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@router.post("/users/{user_id}/delete")
async def delete_user_endpoint(
    request: Request,
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository),
) -> Response:
    current_user = await _current_admin_user(request, user_repo)
    if not current_user:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        await delete_user(user_id, user_repo, current_user_id=current_user.id)
        return RedirectResponse(
            url="/admin/users?flash=User deleted successfully",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except CannotDeleteCurrentUserError as exc:
        return RedirectResponse(
            url=f"/admin/users/{user_id}?error={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@dataclass(slots=True)
class _CallbackResult:
    message: str
    error: bool = False


class _CallbackError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
