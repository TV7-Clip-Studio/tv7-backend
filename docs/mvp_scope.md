# AgentForge MVP Scope

This document formalizes the minimal viable product for the hosted AI actions runtime. It clarifies which capabilities ship in the first release, what is deferred, and which elements rely on mocks or simplified implementations.

## Guiding Principles
- Demonstrate the core value proposition—safe, observable AI actions—without over-optimizing for scale.
- Prefer real integrations for user-visible flows, but mock third-party features that can be swapped with minimal refactoring.
- Maintain parity with the architectural blueprint while constraining blast radius for the initial launch.

## MVP Feature Set

### Core Platform
- **FastAPI service** with versioned `/api/v1` gateway and health/readiness endpoints.
- **Authentication:** JWT-based beta guard plus hashed API keys for invocation endpoints.
- **Actions lifecycle:** CRUD for Actions and ActionVersions, including activation/rollback.
- **Action invocation:** HTTP POST to invoke actions, with schema validation and provider routing.
- **Rate limits & budgets:** Per-key request limits and daily token caps stored in Postgres.
- **Observability:** Prometheus metrics (requests, tokens, latency, errors) and structured logs with `trace_id`.
- **Tracing:** Store redacted traces (input meta, output meta, timing, tokens, status) in Postgres.
- **Usage counters:** Daily per-action tallies updated per invocation.
- **Scheduling:** In-process cron-style scheduler using APScheduler (single-instance support only).
- **Provider routing:** Real integration with OpenAI Chat Completions; fallback to second model via configurable chain.
- **Versioning:** Traffic splitting limited to simple A/B percentages specified per ActionVersion.
- **Admin endpoints:** Basic CRUD for API keys, budgets, schedules; usage summaries per key/action.

### Infrastructure & Tooling
- **Database:** Neon.tech hosted Postgres (async TLS connection) via SQLAlchemy 2.x and Alembic migrations.
- **Deployment:** Docker Compose for local dev; Fly.io single machine for hosted MVP.
- **CI/CD:** GitHub Actions running lint, type check, unit tests, and contract tests.
- **Testing:** Unit tests (pytest + SQLite), integration tests using Testcontainers Postgres, smoke script for production check.
- **Documentation:** OpenAPI spec, README, architecture docs, and this MVP outline.

## Mocked or Simplified Elements
- **Provider fallbacks beyond OpenAI:** Secondary providers (Anthropic, etc.) represented by stub classes returning canned responses to validate routing logic.
- **Alert delivery:** Webhook/Slack/email alerts enqueue to an in-memory outbox and log the payload (no external transport yet).
- **Usage analytics UI:** Export endpoints produce JSON/CSV feeds; no dedicated dashboard.
- **Multi-tenant isolation:** Service-layer enforcement using `owner_id/client_id`; no row-level security policies yet.
- **Kill switch:** Admin endpoint toggles a `system_paused` flag checked before execution (no infra-level autoscale to zero).
- **Budget notifications:** Stored in an “alerts” table; processed by periodic task logging to console.
- **Neon branch environments:** Manual branch creation for staging/review; no automated branch-per-PR workflow yet.

## Out of Scope for MVP
- Horizontal scaling for scheduler or API tier (single instance only).
- Real-time streaming responses or server-sent events.
- Web UI beyond Swagger/OpenAPI.
- Fine-grained RBAC (roles limited to admin/viewer).
- Provider auto-discovery or user-supplied custom providers.
- End-user billing/invoicing automation.
- Long-term trace retention/archival policies (manual DB management assumed).
- External secret storage (dotenv/environment variables only).
- Advanced analytics (only aggregate metrics & CSV export).

## Risk & Mitigation Notes
- **Scheduler duplication risk:** Document workaround—run one machine only; highlight future need for distributed scheduling before scale-out.
- **Alert delivery gaps:** Ensure runbooks specify that alerts are logged; manual monitoring required until transport integrates.
- **Trace growth:** Set manual guidance for DB vacuuming and optional retention script.
- **Kill switch reliance:** Mention that pause flag can leave in-flight requests running; future versions may use Fly scale-to-zero.

## Success Criteria
- Actions can be defined, versioned, invoked, and scheduled end-to-end using real OpenAI calls.
- Budgets and rate limits prevent overuse in automated smoke tests.
- Operators can inspect traces and metrics to diagnose a request.
- CI passes (lint, type check, tests) and deployment to Fly single machine is reproducible.
- Documentation enables new developers or agents to bootstrap quickly.
