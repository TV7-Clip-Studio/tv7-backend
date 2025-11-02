# Shorts Factory Agent Best Practices

This guide keeps autonomous or semi-autonomous contributors aligned while evolving the FastAPI YouTube → Shorts pipeline. Treat it as the contract for day-to-day execution.

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
5. **Update documentation:** Keep `docs/architecture.md`, `docs/roadmap.md`, and `docs/roadmap_rationale.md` current when behavior changes. Mention operational impacts in `README.md`.

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

## Quick Checklist
- [ ] Implementation plan captured.
- [ ] Code follows FastAPI + service module patterns.
- [ ] Auth/rate limits/admin guardrails applied.
- [ ] Background work is non-blocking and idempotent.
- [ ] Metrics/logs/tests updated; `make testcov` passes.
- [ ] Docs and runbooks refreshed.
- [ ] Risks and follow-ups documented for operators.
