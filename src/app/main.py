from __future__ import annotations

import importlib.metadata as importlib_metadata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.admin.routes import router as admin_router
from app.api.v1.routes import api_router
from app.core.config import settings
from app.core.errors import install_exception_handlers
from app.core.logging import setup_logging
from app.core.security import SecurityHeadersMiddleware
from app.db.base import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    # ---- Startup ----
    setup_logging()
    engine = get_engine()  # touch engine to validate URL early

    yield

    # ---- Shutdown ----
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)

# Security / Infra middleware
if getattr(settings, "TRUSTED_HOSTS", None):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings, "CORS_ORIGINS", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics
Instrumentator().instrument(app).expose(app)

# Exceptions
install_exception_handlers(app)

# API
app.include_router(api_router, prefix="/api/v1")
app.include_router(admin_router)


# Utility endpoints
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/version")
async def version() -> dict[str, str]:
    try:
        v = importlib_metadata.version("app")
    except importlib_metadata.PackageNotFoundError:
        v = settings.VERSION
    return {"version": v}
