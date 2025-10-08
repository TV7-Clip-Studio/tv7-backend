from __future__ import annotations

import json
from collections.abc import Awaitable
from http import HTTPStatus
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request, Response
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


async def _resolve_response(result: Response | Awaitable[Response]) -> Response:
    if isinstance(result, Response):
        return result
    return await cast(Awaitable[Response], result)


async def test_http_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[StarletteHTTPException]  # type: ignore[index]
    request = Request({"type": "http"})

    raw_response = handler(
        request, StarletteHTTPException(status_code=418, detail="short and stout")
    )
    response = await _resolve_response(raw_response)

    assert response.status_code == 418
    assert json.loads(response.body.decode()) == {
        "error": {"code": 418, "message": "short and stout"}
    }


async def test_validation_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[ValidationError]  # type: ignore[index]
    request = Request({"type": "http"})

    with pytest.raises(ValidationError) as exc_info:
        _Payload(number=cast(Any, "invalid"))

    raw_response = handler(request, exc_info.value)
    response = await _resolve_response(raw_response)
    payload = json.loads(response.body.decode())

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert payload["error"]["code"] == HTTPStatus.UNPROCESSABLE_ENTITY
    assert payload["error"]["message"] == "Validation error"
    assert payload["error"]["details"][0]["loc"] == ["number"]


async def test_generic_exception_handler() -> None:
    app = _build_app()
    handler = app.exception_handlers[Exception]  # type: ignore[index]
    request = Request({"type": "http"})

    raw_response = handler(request, RuntimeError("boom"))
    response = await _resolve_response(raw_response)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert json.loads(response.body.decode()) == {
        "error": {
            "code": HTTPStatus.INTERNAL_SERVER_ERROR,
            "message": "Internal server error",
        }
    }
