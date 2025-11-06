from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db.models import User
from app.deps.db import get_user_repository
from app.deps.security import require_jwt_user
from app.repositories.users import UserRepository
from app.schemas import UserCreate, UserRead, UserUpdate
from app.services.users import (
    EmailAlreadyTakenError,
    InvalidPasswordError,
    UserAlreadyExistsError,
    create_user,
    list_users,
    update_user_profile,
)

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


@router.get("/me", response_model=UserRead)
async def get_current_user(
    current_user: User = Depends(require_jwt_user),
) -> UserRead:
    """Get the authenticated user's profile."""
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead)
async def update_current_user(
    payload: UserUpdate,
    current_user: User = Depends(require_jwt_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UserRead:
    """Update the authenticated user's profile."""
    try:
        updated_user = await update_user_profile(current_user.id, payload, repo)
    except InvalidPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailAlreadyTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return UserRead.model_validate(updated_user)
