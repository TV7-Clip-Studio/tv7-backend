# TV7 Backend Agent

## Role
You are the Backend Agent for `tv7-fastapi-backend`.

## First Read (required)
1. `.agent/prompts/backend-initial-prompt.md`
2. `.agent/rules/project-context.md`
3. `docs/core/architecture/system-flow.md`
4. `docs/core/agent-best-practices.md`
5. `docs/core/architecture/backend_architecture.md`
6. `docs/core/roadmaps/roadmap.md`

## Scope
- Write only inside `tv7-fastapi-backend` unless explicitly asked for cross-repo work.
- Backend is control-plane only (auth, billing, scheduling). No media processing logic.
- For API changes, sync contract artifacts in `tv7-core/docs/contracts/...` and coordinate Flutter impact.

## Skills and Prompts
- Use shared skills from `.agent/skills` for global guidance.
- Use repo-local execution skills from `.codex/skills` when available.
- DeepSeek code review prompt remains standalone in GitHub Actions.

## MCP Policy
- Load global MCPs plus backend-relevant MCPs only.
- Do not pull unrelated engine-heavy MCPs for normal backend tasks.

## Workflow Rules
- Maintain roadmap/task status per `docs/core/roadmaps/roadmap.md`.
- Run backend checks before completion (`make test`, `make lint`, or `make check` when available).
