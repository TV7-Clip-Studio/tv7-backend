from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps.db import get_user_repository
from app.repositories.users import UserRepository
from app.schemas import UserCreate, UserRead
from app.services.users import UserAlreadyExistsError, create_user, list_users

router = APIRouter()


@router.get("/", response_model=list[UserRead])
async def list_users_endpoint(
    repo: UserRepository = Depends(get_user_repository),
) -> list[UserRead]:
    users = await list_users(repo)
    return [UserRead.model_validate(user) for user in users]


@router.post("/", response_model=UserRead, status_code=201)
async def create_user_endpoint(
    payload: UserCreate,
    repo: UserRepository = Depends(get_user_repository),
) -> UserRead:
    try:
        user = await create_user(payload, repo)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    validated_user: UserRead = UserRead.model_validate(user)
    return validated_user
