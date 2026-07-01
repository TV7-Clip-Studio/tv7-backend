from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.jwt import TokenType
from app.db.models import User
from app.deps.db import get_cloud_ai_repository, get_user_repository
from app.deps.security import require_jwt_user
from app.repositories.cloud_ai import CloudAiRepository
from app.repositories.users import UserRepository
from app.schemas import LicenseReadinessResponse, LoginRequest, Token, TokenRefreshRequest
from app.services.auth import (
    InvalidCredentialsError,
    authenticate_user,
    issue_tokens_for_user,
    resolve_user_from_token,
)
from app.services.cloud_ai import get_cloud_ai_license_readiness

router = APIRouter()


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
async def login(
    payload: LoginRequest, repo: UserRepository = Depends(get_user_repository)
) -> Token:
    try:
        user = await authenticate_user(payload.email, payload.password, repo)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access_token, refresh_token = issue_tokens_for_user(user)
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    payload: TokenRefreshRequest,
    repo: UserRepository = Depends(get_user_repository),
) -> Token:
    user = await resolve_user_from_token(
        payload.refresh_token, repo, expected_type=TokenType.REFRESH
    )
    access_token, refresh_token = issue_tokens_for_user(user)
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.get("/license", response_model=LicenseReadinessResponse)
async def license_readiness(
    user: User = Depends(require_jwt_user),
    cloud_ai_repo: CloudAiRepository = Depends(get_cloud_ai_repository),
) -> LicenseReadinessResponse:
    return await get_cloud_ai_license_readiness(user, cloud_ai_repo)
