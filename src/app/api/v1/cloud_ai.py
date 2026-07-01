from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.models import User
from app.deps.db import get_cloud_ai_repository, get_user_repository
from app.deps.security import require_jwt_user
from app.repositories.cloud_ai import CloudAiRepository
from app.repositories.users import UserRepository
from app.schemas import (
    CloudAiExecuteRequest,
    CloudAiExecuteResponse,
    EngineCloudAiTokenResponse,
)
from app.services.cloud_ai import (
    CloudAiErrorCode,
    CloudAiHTTPException,
    execute_cloud_ai,
    issue_engine_cloud_ai_token,
    resolve_engine_cloud_ai_user,
)

router = APIRouter()
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_engine_cloud_ai_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    if credentials is None:
        raise CloudAiHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            CloudAiErrorCode.AUTH_REQUIRED,
            "A valid Engine cloud AI token is required.",
        )
    return await resolve_engine_cloud_ai_user(credentials.credentials, user_repo)


@router.post(
    "/engine-token",
    response_model=EngineCloudAiTokenResponse,
    status_code=status.HTTP_200_OK,
)
async def create_engine_cloud_ai_token(
    user: User = Depends(require_jwt_user),
    repo: CloudAiRepository = Depends(get_cloud_ai_repository),
) -> EngineCloudAiTokenResponse:
    return await issue_engine_cloud_ai_token(user, repo)


@router.post(
    "/engine/execute",
    response_model=CloudAiExecuteResponse,
    status_code=status.HTTP_200_OK,
)
async def execute_engine_cloud_ai(
    payload: CloudAiExecuteRequest,
    user: User = Depends(require_engine_cloud_ai_user),
    repo: CloudAiRepository = Depends(get_cloud_ai_repository),
) -> CloudAiExecuteResponse:
    return await execute_cloud_ai(user, payload, repo)
