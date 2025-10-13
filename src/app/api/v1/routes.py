from fastapi import APIRouter, Depends

from app.deps.security import require_beta_key

from . import ai, users

api_router = APIRouter(dependencies=[Depends(require_beta_key)])

api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
