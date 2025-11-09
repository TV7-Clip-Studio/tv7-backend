from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest

from app.core.config import settings


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    """Configure Playwright browser launch arguments for UI tests."""
    return {
        **browser_type_launch_args,
        "headless": os.getenv("PWHEADLESS", "true").lower() != "false",
        "slow_mo": int(os.getenv("PWSLOWMO", "0")),
    }


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for UI smoke tests - derives from Settings.API_PORT."""
    return settings.ui_base_url.rstrip("/")


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
    admin_username = settings.ADMIN_USERNAME
    admin_password = settings.ADMIN_PASSWORD
    email = settings.UI_ADMIN_EMAIL or admin_username
    password = settings.UI_ADMIN_PASSWORD or admin_password
    if not email or not password:  # pragma: no cover - runtime guardrail
        pytest.skip(
            "UI smoke requires operator credentials via UI_ADMIN_* or ADMIN_USERNAME/ADMIN_PASSWORD"
        )
    assert email is not None
    assert password is not None
    credentials: tuple[str, str] = (email, password)
    yield credentials


@pytest.fixture(autouse=True)
def configure_app_database() -> Iterator[None]:
    """Override the project-wide DB fixture for UI tests (no async loop)."""
    yield
