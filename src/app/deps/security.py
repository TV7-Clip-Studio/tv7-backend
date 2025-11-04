from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)

from app.core.config import settings
from app.db.models import User
from app.deps.db import get_user_repository
from app.repositories.users import UserRepository
from app.services.auth import resolve_user_from_token


def _get_beta_key() -> str | None:
    # Read lazily so tests can mutate environment between runs.
    value = os.getenv("BETA_API_KEY")
    return value if value else None


async def require_beta_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    expected = _get_beta_key()
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key


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


_admin_security = HTTPBasic()


async def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(_admin_security)],
) -> str:
    username = settings.ADMIN_USERNAME
    password = settings.ADMIN_PASSWORD

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin credentials are not configured",
        )

    if not (
        secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    return str(credentials.username)
