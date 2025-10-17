# AgentForge Agent Best Practices

This guide codifies expectations for autonomous or semi-autonomous coding agents working on the AgentForge backend. The goal is to keep contributions predictable, reviewable, and production ready.

## Core Principles
- **Human-first readability:** Write code and documentation that a teammate can understand on first pass. Favour descriptive names, small functions, and sparse but meaningful comments.
- **Architecture alignment:** Reuse existing patterns, helpers, and module layouts instead of inventing new styles. Any deliberate deviation should be justified with an RFC-style note.
- **Security & cost awareness:** Enforce auth, rate limits, and budget checks on every new execution path. Never bypass guardrails in “temporary” code.
- **Observability everywhere:** Emit metrics/logs/traces for new features, keeping the `trace_id` contract intact.

## Development Workflow
1. **Plan before you code:** Write an implementation plan before doing big and medium tasks (for small tasks agents can apply changes directly)
2. **Sync with configuration:** Update env vars, Alembic migrations, and docs when schema or settings change. No hard-coded secrets.
3. **Tests are mandatory:** Extend the pytest suite (unit + integration). Keep SQLite fixtures for unit tests; use Testcontainers for DB-dependent integration.
4. **Local validation:** Run `make test` and relevant targeted commands (`make lint`, `make typecheck`, `make test-integration`) before submitting changes.
5. **Document risks:** Note any known gaps, TODOs, or deferred work in the PR description and, when long-lived, in the `docs/` knowledge base.

## Coding Standards
- **Python style:** Follow Ruff defaults and `pyproject.toml` settings. Avoid clever one-liners; prefer clarity over terseness.
- **Schema rigor:** Use Pydantic models for request/response validation. Ensure new endpoints have OpenAPI docstrings and typed responses.
- **Error handling:** Always map exceptions through the central error layer; return the canonical JSON error shape.
- **Database interactions:** Use SQLAlchemy 2.0 style (select/execute) with async session patterns. All migrations go through Alembic.
- **Concurrency:** Respect async/await boundaries. No blocking calls within async endpoints.

## Observability & Operations
- **Metrics:** Register Prometheus counters/histograms for new action types or background jobs.
- **Logging:** Use structured logs with log level context; include `trace_id`, action slug, and key ID where applicable.
- **Tracing:** Persist traces for all user-visible operations. Redact sensitive fields before storage.
- **Runbooks:** Update `README.md` or dedicated docs when new operational tasks are introduced (cron jobs, branches, retention scripts).

## Collaboration Etiquette
- Summaries should highlight intent, impact, and testing performed.
- Reference related documents or tickets. The `docs/` directory is the living source of truth—consult it before changes and update it when behaviour shifts.
- Flag TODOs explicitly with `TODO(name)` so ownership is clear.
- Keep PRs/commits scoped; large refactors require design approval.

## Appendix: Quick Checklist
- [ ] Plan written and linked.
- [ ] Code aligned with architecture/MVP docs.
- [ ] Auth, rate limit, and budget checks enforced.
- [ ] Metrics/logging/tracing updated.
- [ ] Tests added/updated; `make test` run.
- [ ] Docs updated (README, architecture, or MVP as needed).
- [ ] Risks and follow-ups documented.
