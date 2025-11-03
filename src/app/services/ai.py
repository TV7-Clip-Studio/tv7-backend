from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AIExecutionResult:
    output: str
    meta: dict[str, Any] = field(default_factory=dict)


def execute_agent(
    *,
    agent_id: str,
    user_input: str,
    session_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> AIExecutionResult:
    _ = session_id
    _ = context
    # Stubbed echo agent until the roadmap replaces it with real LLM calls.
    return AIExecutionResult(output=f"ECHO: {user_input}", meta={"agent_id": agent_id})
