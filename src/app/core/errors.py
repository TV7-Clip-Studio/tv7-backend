from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.status_code, "message": exc.detail}},
            status_code=exc.status_code,
        )

    def _validation_response(exc: ValidationError | RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": 422, "message": "Validation error", "details": exc.errors()}},
            status_code=422,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exc_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _validation_response(exc)

    @app.exception_handler(ValidationError)
    async def validation_exc_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return _validation_response(exc)

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": 500, "message": "Internal server error"}},
            status_code=500,
        )
