from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import install_exception_handlers

pytestmark = pytest.mark.asyncio


def _build_app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    return app


class _Payload(BaseModel):
    number: int


async def test_http_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[StarletteHTTPException]  # type: ignore[index]
    request = Request({"type": "http"})

    response = await handler(
        request, StarletteHTTPException(status_code=418, detail="short and stout")
    )

    assert response.status_code == 418
    assert json.loads(response.body.decode()) == {
        "error": {"code": 418, "message": "short and stout"}
    }


async def test_validation_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[ValidationError]  # type: ignore[index]
    request = Request({"type": "http"})

    with pytest.raises(ValidationError) as exc_info:
        _Payload(number="invalid")

    response = await handler(request, exc_info.value)
    payload = json.loads(response.body.decode())

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert payload["error"]["code"] == HTTPStatus.UNPROCESSABLE_ENTITY
    assert payload["error"]["message"] == "Validation error"
    assert payload["error"]["details"][0]["loc"] == ["number"]


async def test_generic_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[Exception]  # type: ignore[index]
    request = Request({"type": "http"})

    response = await handler(request, RuntimeError("boom"))

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert json.loads(response.body.decode()) == {
        "error": {
            "code": HTTPStatus.INTERNAL_SERVER_ERROR,
            "message": "Internal server error",
        }
    }
