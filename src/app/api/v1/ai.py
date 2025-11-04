from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.models import User
from app.deps.rate_limit import check_rate
from app.deps.security import require_jwt_user
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


@router.post("/execute", response_model=AIResponse)
async def execute(
    payload: AIRequest,
    current_user: User = Depends(require_jwt_user),
) -> AIResponse:
    check_rate(current_user.email)
    result = execute_agent(
        agent_id=payload.agent_id,
        user_input=payload.input,
        session_id=payload.session_id,
        context=payload.context,
    )
    return AIResponse(output=result.output, meta=result.meta)
