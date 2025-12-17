from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.models import User
from app.deps.db import get_user_repository
from app.repositories.users import UserRepository
from app.services.auth import resolve_user_from_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_jwt_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)],
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials
    user = await resolve_user_from_token(token, repo)
    return user
