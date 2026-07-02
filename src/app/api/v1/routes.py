from fastapi import APIRouter, Depends

from app.deps.security import require_jwt_user

from . import auth, clips, cloud_ai, config, publish, uploads, users, videos

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_jwt_user)],
)
api_router.include_router(
    clips.router,
    prefix="/clips",
    tags=["clips"],
    dependencies=[Depends(require_jwt_user)],
)
api_router.include_router(
    videos.router,
    prefix="/videos",
    tags=["videos"],
    dependencies=[Depends(require_jwt_user)],
)
api_router.include_router(
    publish.router,
    tags=["publish"],
    prefix="",
)
api_router.include_router(
    config.router,
    tags=["config"],
    prefix="/config",
)
api_router.include_router(
    uploads.router,
    tags=["uploads"],
    prefix="/uploads",
)
api_router.include_router(
    cloud_ai.router,
    tags=["cloud-ai"],
    prefix="/cloud-ai",
)
