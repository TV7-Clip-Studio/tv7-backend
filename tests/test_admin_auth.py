from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient, BasicAuth
from pytest import MonkeyPatch

from app.core.config import settings
from app.deps.security import require_admin


def _build_admin_app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin/ping")
    async def admin_ping(_: str = Depends(require_admin)) -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_require_admin_success(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "secret")

    transport = ASGITransport(app=_build_admin_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/ping", auth=BasicAuth("admin", "secret"))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_require_admin_invalid_credentials(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "secret")

    transport = ASGITransport(app=_build_admin_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/ping", auth=BasicAuth("admin", "wrong"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Basic"
    assert response.json()["detail"] == "Admin authentication required"


@pytest.mark.asyncio
async def test_require_admin_missing_credentials(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", None)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    transport = ASGITransport(app=_build_admin_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/ping", auth=BasicAuth("any", "value"))

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Admin credentials are not configured"


@pytest.mark.asyncio
async def test_require_admin_missing_header(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "secret")

    transport = ASGITransport(app=_build_admin_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/ping")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Basic"
    assert response.json()["detail"] == "Not authenticated"
