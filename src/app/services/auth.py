from __future__ import annotations

from fastapi import HTTPException, status

from app.core.jwt import TokenType, create_token, decode_token
from app.core.security import verify_password
from app.db.models import User
from app.repositories.users import UserRepository


class InvalidCredentialsError(Exception):
    """Raised when login credentials are invalid."""


async def authenticate_user(email: str, password: str, repo: UserRepository) -> User:
    user = await repo.get_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password")
    return user


def issue_tokens_for_user(user: User, *, include_refresh: bool = True) -> tuple[str, str | None]:
    access_token = create_token(subject=user.email, token_type=TokenType.ACCESS)
    refresh_token: str | None = None
    if include_refresh:
        refresh_token = create_token(subject=user.email, token_type=TokenType.REFRESH)
    return access_token, refresh_token


async def resolve_user_from_token(
    token: str,
    repo: UserRepository,
    *,
    expected_type: TokenType = TokenType.ACCESS,
) -> User:
    payload = decode_token(token, expected_type=expected_type)
    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await repo.get_by_email(str(subject))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
