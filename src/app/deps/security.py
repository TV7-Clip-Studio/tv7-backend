from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings


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
