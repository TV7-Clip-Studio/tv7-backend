from fastapi import APIRouter, Depends

from app.deps.security import require_jwt_user

from . import ai, auth, users, videos

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_jwt_user)],
)
api_router.include_router(
    ai.router,
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(require_jwt_user)],
)
api_router.include_router(
    videos.router,
    prefix="/videos",
    tags=["videos"],
    dependencies=[Depends(require_jwt_user)],
)
