# src/app/main.py
from __future__ import annotations

from contextlib import asynccontextmanager
import importlib.metadata as importlib_metadata
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.security import SecurityHeadersMiddleware
from app.core.errors import install_exception_handlers
from app.api.v1.routes import api_router
from app.db.base import get_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    setup_logging()

    # Touch the engine at startup to fail fast if DATABASE_URL is wrong.
    engine = get_engine()
    # NOTE: Do NOT create tables here; use Alembic migrations.
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)

    yield

    # ---- Shutdown ----
    await engine.dispose()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# ----- Security / Infra middleware -----
if getattr(settings, "TRUSTED_HOSTS", None):
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.TRUSTED_HOSTS,
    )

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings, "CORS_ORIGINS", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Metrics -----
# Exposes Prometheus metrics at /metrics
Instrumentator().instrument(app).expose(app)

# ----- Exceptions -----
install_exception_handlers(app)

# ----- API -----
app.include_router(api_router, prefix="/api/v1")

# ----- Utility endpoints -----
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/readyz")
async def readyz():
    return {"status": "ready"}

@app.get("/version")
async def version():
    try:
        v = importlib_metadata.version("app")
    except importlib_metadata.PackageNotFoundError:
        v = settings.VERSION
    return {"version": v}
