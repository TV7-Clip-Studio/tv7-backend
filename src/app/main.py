from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from contextlib import asynccontextmanager
import importlib.metadata as importlib_metadata

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.security import SecurityHeadersMiddleware
from app.core.errors import install_exception_handlers
from app.api.v1.routes import api_router
from app.db.base import get_engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    engine = get_engine()
    if settings.APP_ENV == "dev":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

install_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health(): return {"status": "ok"}

@app.get("/readyz")
async def readyz(): return {"status": "ready"}

@app.get("/version")
async def version():
    try:
        v = importlib_metadata.version("app")
    except importlib_metadata.PackageNotFoundError:
        v = settings.VERSION
    return {"version": v}
