# TV7 Agent Best Practices

This guide keeps autonomous or semi-autonomous contributors aligned while evolving the TV7 FastAPI YouTube → Shorts pipeline. Treat it as the contract for day-to-day execution.

## Agent Starter Prompt

**If you're an AI agent or autonomous contributor starting work on this project, use this prompt to initialize your context:**

```
I'm working on the TV7 project, a FastAPI service that converts YouTube videos into short-form vertical clips.

First, I'll read the documentation in this order:
1. docs/INDEX.md - Navigation hub to understand the documentation structure
2. docs/architecture.md - System design, domain model, and API layering
3. docs/tech_stack.md - Technologies, libraries, and dependencies
4. docs/roadmap.md - Current feature plan and completion status
5. docs/user_flows.md - How operators and API clients use the system
6. docs/testing.md - Test strategy and where to place new tests
7. docs/agent_best_practices.md - This file, for coding standards and workflow

I understand that:
- This is a monolithic FastAPI application (API + workers + admin UI)
- The architecture follows router → service → repository → ORM layering
- Background processing uses Dramatiq + Redis for async tasks
- Authentication uses JWT for API, cookies for admin dashboard
- All new features require tests with 85% coverage minimum
- Documentation must be updated alongside code changes

I will follow the established patterns in the codebase and ask for clarification before introducing new architectural approaches.
```

**Use this prompt when:**
- Starting a new session on the project
- Onboarding a new AI coding assistant
- Refreshing context after a long break

---

## Onboarding Checklist
1. **Read the docs first:** Start with `docs/INDEX.md` to navigate the documentation. Primary reading: `roadmap.md`, `architecture.md`, `tech_stack.md`, `testing.md`, and `roadmap_rationale.md`. These are your sources of truth—understand the current milestones, system shape, and technology choices before touching code.
2. **Review existing code paths:** Skim the service/repository layers in `src/app` and the accompanying tests to see how endpoints and background tasks are structured. Look for prior art before introducing new patterns.
3. **Align with the roadmap:** Confirm the task you’re tackling maps to a roadmap item (e.g., Phase 1.4.x). If you’re unsure where a change fits, document assumptions and seek clarification.
4. **Plan your approach:** Capture the intended changes (data shape, API behaviour, test impact) in notes or issue comments before implementing. Discuss deviations from established patterns up front.

## Core Principles
- **Operator-first clarity:** Code, docs, and admin views must be easy for a human operator to run and debug. Prefer explicit naming, small modules, and comments only when they add real insight.
- **Single-service mindset:** Build every feature (API, UI, workers) inside this FastAPI project unless the roadmap explicitly calls for a new service.
- **Secure by default:** Enforce auth, rate limits, and admin protections on new routes. Never introduce “temporary” unauthenticated paths.
- **Pipeline observability:** Every stage (download → highlights → render → publish) must log key events and be measurable.

## Development Workflow
1. **Plan before coding:** For medium/large tasks, outline the approach (data model changes, workers, APIs) before touching code. Keep plans alongside PRs/issues.
2. **Sync configuration:** When you add settings, migrations, or background workers, update `.env.example`, Alembic revisions, and docs. No hard-coded secrets or paths.
3. **Guard the request path:** Long-running or CPU-heavy work belongs in background tasks. If you must block, document why and add TODOs for follow-up.
4. **Test locally:** Run `make fmt`, `make lint`, `make type`, `make testcov`, and relevant targeted tests before opening a PR. Use `make worker` (once added) to exercise pipelines end-to-end.
5. **Update documentation:** Keep relevant docs current when behavior changes:
   - `docs/architecture.md` - System design changes
   - `docs/roadmap.md` + `docs/roadmap_rationale.md` - Feature completion and reasoning
   - `docs/tech_stack.md` - New dependencies or version updates
   - `docs/user_flows.md` - New workflows or flow changes
   - `docs/off_roadmap.md` + `docs/off_roadmap_rationale.md` - Features outside main roadmap
   - `README.md` - Setup or deployment impacts
   - Update `docs/INDEX.md` if adding new documentation files

## Coding Standards
- **FastAPI conventions:** Use Pydantic models for input/output. Add descriptive tags and summaries so `/docs` stays polished.
- **SQLAlchemy + Alembic:** Stick to SQLAlchemy 2.0 async patterns. Generate and commit migrations alongside model changes.
- **Services module layout:** Place pipeline logic under `src/app/services/` (downloader, highlight detector, clipper, subtitle styler, publisher). Keep functions composable and testable.
- **Error handling:** Route exceptions through `app.core.errors` helpers. Always return the canonical JSON error format for API responses.
- **Type safety:** Maintain typing discipline; rely on Ruff+MyPy defaults from `pyproject.toml`. Avoid `Any` unless absolutely necessary and justified in comments.

## Background Pipeline Guardrails
- **Idempotency:** Ensure tasks can be retried without corrupting state (e.g., safe updates, temp file cleanup).
- **Status transitions:** Update `Video.status`, `Clip.status`, and `PublishJob.status` atomically and document the life cycles in code comments/tests.
- **Resource hygiene:** Manage temp directories, large file downloads, and ffmpeg processes carefully. Add cleanup hooks when introducing new temp artifacts.
- **LLM usage:** Prompt for machine-readable output, validate responses strictly, and log raw results for debugging (redacting secrets).

## Operations & Observability
- **Metrics & logs:** Extend Prometheus counters/histograms and structured logging when building new stages. Include `video_id` / `clip_id` / `job_id` in log contexts.
- **Admin access:** Use the roadmap’s admin auth scaffolding (`require_admin` + `ADMIN_USERNAME`/`ADMIN_PASSWORD`). Rotate credentials with `make admin-credentials` (auto-syncs Fly secrets when logged in). Never deploy a dashboard without protection.
- **Deployment parity:** Verify local Docker/Compose and Fly.io configurations stay in sync. Update Makefile and docs when new processes (workers, cron) are introduced.
- **Runbooks:** Capture operational steps (rotating admin access, seeding models, troubleshooting workers) in `docs/` as you add features.

## Collaboration Etiquette
- Keep PRs focused and well-described (intent, impact, testing). Call out risks or follow-ups explicitly.
- Reference relevant roadmap/rationale items so reviewers can trace decisions.
- Use `TODO(name)` annotations to assign future work when you must defer.
- When in doubt, ask for clarification before re-architecting core pieces.

## Documentation Responsibilities

**When adding features:**
- Roadmap features → Update `roadmap.md` status, add notes to `roadmap_rationale.md`
- Off-roadmap features → Document in `off_roadmap.md` and `off_roadmap_rationale.md`
- New libraries → Update `tech_stack.md` with version and purpose
- User-facing changes → Update `user_flows.md` with new workflows
- API changes → Update `architecture.md` with endpoint details
- Always check `docs/INDEX.md` to ensure new docs are linked

**When making breaking changes:**
- Update affected documentation immediately in the same commit
- Add migration notes to relevant docs
- Update version matrix in `tech_stack.md` if dependencies change
- Document rollback procedures if critical

## Quick Checklist
- [ ] Implementation plan captured.
- [ ] Code follows FastAPI + service module patterns.
- [ ] Auth/rate limits/admin guardrails applied.
- [ ] Background work is non-blocking and idempotent.
- [ ] Metrics/logs/tests updated; `make testcov` passes.
- [ ] Docs and runbooks refreshed (check INDEX.md for what needs updating).
- [ ] Risks and follow-ups documented for operators.
- [ ] New dependencies added to `tech_stack.md`.
- [ ] User-facing changes reflected in `user_flows.md`.
