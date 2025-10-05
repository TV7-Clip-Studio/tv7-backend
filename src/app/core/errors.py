from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": exc.status_code, "message": exc.detail}}, status_code=exc.status_code)

    @app.exception_handler(ValidationError)
    async def validation_exc_handler(request: Request, exc: ValidationError):
        return JSONResponse({"error": {"code": 422, "message": "Validation error", "details": exc.errors()}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request: Request, exc: Exception):
        return JSONResponse({"error": {"code": 500, "message": "Internal server error"}}, status_code=500)
