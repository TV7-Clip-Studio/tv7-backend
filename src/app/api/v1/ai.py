from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.deps.rate_limit import check_rate
from app.deps.security import require_beta_key
from app.services.ai import execute_agent

router = APIRouter()


class AIRequest(BaseModel):
    agent_id: str = Field(default="default")
    input: str
    session_id: str | None = None
    context: dict[str, Any] | None = None


class AIResponse(BaseModel):
    output: str
    meta: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/execute",
    response_model=AIResponse,
    dependencies=[Depends(require_beta_key)],
)
async def execute(
    payload: AIRequest,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AIResponse:
    check_rate(x_api_key or "anon")
    result = execute_agent(
        agent_id=payload.agent_id,
        user_input=payload.input,
        session_id=payload.session_id,
        context=payload.context,
    )
    return AIResponse(output=result.output, meta=result.meta)
