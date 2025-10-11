from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, status


def _get_beta_key() -> str | None:
    # Read lazily so tests can mutate environment between runs.
    value = os.getenv("BETA_API_KEY")
    return value if value else None


async def require_beta_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None
) -> str:
    expected = _get_beta_key()
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key
