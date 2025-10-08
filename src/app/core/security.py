from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from passlib.context import CryptContext
from starlette.middleware.base import BaseHTTPMiddleware

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain-text password using pbkdf2_sha256."""
    return str(_pwd_context.hash(password))


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a stored hash."""
    return bool(_pwd_context.verify(password, hashed_password))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response
