from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for UI smoke tests."""
    return os.getenv("UI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture(scope="session")
def ensure_server(base_url: str) -> None:
    """Skip UI tests if the server is unavailable."""
    health_url = f"{base_url}/health"
    try:
        response = httpx.get(health_url, timeout=5.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - runtime guardrail
        pytest.skip(f"UI smoke tests require a running app at {base_url} ({exc})")


@pytest.fixture(scope="session")
def seeded_user(ensure_server: None) -> Iterator[tuple[str, str]]:
    """Provide operator credentials for UI smoke tests."""
    _ = ensure_server
    email = os.getenv("UI_ADMIN_EMAIL") or os.getenv("ADMIN_USERNAME")
    password = os.getenv("UI_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
    if not email or not password:  # pragma: no cover - runtime guardrail
        pytest.skip(
            "UI smoke requires UI_ADMIN_EMAIL/ADMIN_USERNAME and UI_ADMIN_PASSWORD/ADMIN_PASSWORD"
        )
    assert email is not None
    assert password is not None
    credentials: tuple[str, str] = (email, password)
    yield credentials
