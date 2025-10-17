# AI Actions Layer — System Architecture

## Overview
This document captures the present-tense architecture for a hosted AI actions runtime that targets agencies and small teams. The platform delivers callable, AI-backed functions (actions) with built-in authentication, rate limits, budgeting, scheduling, logging, and analytics. The service is implemented with FastAPI using a modular layout aligned to `app/main.py`, `app/api/v1/*`, `app/core/*`, `app/db/*`, and `app/deps/*`.

## Open Questions & Potential Gaps
- **Scheduler coordination:** The in-process scheduler works for a single Fly.io machine, but horizontal scaling would need leader election or a distributed job queue to avoid duplicate runs.
- **Trace retention & storage costs:** Traces store redacted payloads and usage data, yet no retention or archival strategy is defined; unbounded growth in Postgres could affect performance.
- **Multi-tenant isolation:** The data model notes per-user keys, but the cleanup/plans for tenant data partitioning (row-level policies, org boundaries) are unspecified.
- **Alerting mechanics:** Hard-stop alerts reference Slack/webhooks/email, but the pathway (outbox table, retry strategy) is not described.
- **Rate-limit storage:** Enforcement is said to occur pre-call, but the choice of storage (in-memory cache vs. Postgres counters) and latency trade-offs remain open.
- **Secrets management:** Provider keys are referenced yet the approach for encryption at rest or KMS-backed storage is not detailed.

## 1. Application Core
- Single FastAPI application mounts the `/api/v1` gateway.
- Middlewares include Trusted Hosts, CORS, and Prometheus instrumentation.
- Lifespan context initializes configuration, structured logging, and background services (scheduler, provider clients).
- Every route returns JSON with consistent error taxonomy and embeds a `trace_id`.

## 2. API Gateway (v1)
- Aggregates domain routers: Users, AI (low-level), Actions, Keys, Limits, Schedules, Metrics, Traces.
- Endpoints follow CRUD-style semantics with verbs for invoking actions, issuing/revoking keys, configuring budgets/limits, creating schedules, and reading metrics.
- OpenAPI documentation with typed schemas defines request/response contracts.

## 3. Actions Runtime
- Represents each Action with metadata: name, slug, description, input/output schema, provider configuration.
- Execution path validates input, resolves the active `ActionVersion` (supports A/B traffic split), enforces limits/budgets, routes provider call, records `Trace`, updates usage counters, and returns `{output, meta}` (latency, tokens, version).
- Supports invocation via HTTP and via scheduled jobs with shared enforcement and tracing.

## 4. Provider Router
- Adapter layer normalizes calls to AI providers (OpenAI first).
- Applies timeouts, retries with exponential backoff, and optional fallback models.
- Returns `{text | structured_output, tokens_in, tokens_out, model, provider}` and maps provider errors to platform error codes.

## 5. Versioning & Prompt Management
- `Action` stores one or more `ActionVersion` records with prompt/config deltas.
- Supports activating a version, rolling back, and splitting traffic across versions.
- Version metadata appears in Traces and Metrics for comparisons.

## 6. Keys, Tenancy & Auth
- Issues per-user API keys and optional per-client keys for agencies.
- Keys hold scope/quota metadata, are hashed at rest, and never logged in full.
- Endpoints accept Bearer tokens or `x-api-key`, resolving caller identity for enforcement and attribution.

## 7. Rate Limits & Budgets
- Enforces request rate limits (per key, per action) and token budgets (daily/monthly).
- Hard-stop toggle disables an action automatically when a budget is exhausted and triggers alerts.
- Limits execute prior to provider calls to prevent cost overruns.

## 8. Scheduling
- Background scheduler supports cron-like schedules bound to Actions (hourly, daily, weekly).
- Schedules track `last_run_at`, `next_run_at`, and last status.
- Runs are idempotent with unique IDs; retries use exponential backoff.

## 9. Observability & Tracing
- Prometheus metrics publish request counts, token usage, latency histograms, and error rates per action/version.
- Traces store redacted payloads, timing, token counts, status, error code, version, model, caller key ID.
- Each response includes a `trace_id` for support and replay.

## 10. Error Handling
- Central error layer maps exceptions to a stable JSON shape:
  ```json
  {"error":{"code":"BUDGET_EXCEEDED","message":"...","trace_id":"..."}}
  ```
- Provider errors normalize to `AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_RATE_LIMIT`, `AI_PROVIDER_INVALID_REQUEST`.
- Platform errors map to `RATE_LIMIT_EXCEEDED`, `VALIDATION_ERROR`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `INTERNAL_ERROR`.

## 11. Data Model
- **User:** identity, auth, timestamps.
- **Action:** owner, slug, name, description, input/output schema, provider config, enabled flag.
- **ActionVersion:** action reference, version label, prompt/config metadata (temperature, max tokens, router/fallback), timestamps.
- **Key:** owner, optional client ID, hashed key, scope/quota.
- **UsageCounter:** per day/action counters for requests, tokens_in, tokens_out.
- **Budget:** per action with period, max requests/tokens, hard-stop flag.
- **Schedule:** action binding, cron expression, active flag, last/next run timestamps.
- **Trace:** action/version/key references, redacted payloads, tokens, latency, status, error code, timestamps.

## 12. Configuration
- Central settings define allowed hosts, CORS, DB URL, provider API keys, default rate limits, token caps, timeouts, retry/backoff policy, feature flags.
- All “magic numbers” live in configuration and can be overridden via environment variables.

## 13. Security & Privacy Posture
- API keys hashed; secrets sourced from environment.
- PII redaction applies to marked fields before logging/tracing.
- CORS and Trusted Hosts restrict origins; WAF/CDN (e.g., Cloudflare) guards public endpoints.
- Uploads and large user payloads are size-limited; server timeouts prevent resource pinning.
- Only redacted payload previews appear in logs and traces.

## 14. Cost Controls & Safety
- Pre-call limits prevent runaway costs.
- Hard-stop disables actions on budget breach and emits alerts (Slack/webhook/email).
- Operational kill switch pauses all executions rapidly.
- Provider usage can leverage user-supplied keys to externalize inference costs.

## 15. Metrics & Analytics
- Metrics include `ai_requests_total{action,version,status}`, `ai_tokens_in_total`, `ai_tokens_out_total`, latency histograms, and error counters.
- Usage endpoints summarize per-client and per-action consumption for invoicing and planning.
- Analytics view surfaces p50/p95 latency, success rate, and top error codes.

## 16. Webhooks & Integrations
- Outbound webhooks notify on budget reached, action disabled, schedule run success/failure, new version activation.
- Optional inbound webhooks trigger actions from external systems.

## 17. Non-Functional Characteristics
- **Reliability:** idempotent scheduled runs, retries with capped backoff, bounded timeouts.
- **Performance:** minimal overhead on hot path; schema validation occurs once; provider calls are timed and trimmed.
- **Portability:** provider router abstracts vendor differences, enabling model/provider swaps without endpoint changes.
- **Extensibility:** new action types and providers plug into existing runtime contracts.
- **Operability:** consistent logging, clear error codes, and trace replay streamline support.

## 18. External Boundary
- Platform sits behind a CDN/WAF.
- Application runs on Fly.io with one or few machines in MVP mode; Prometheus metrics exposed for internal monitoring.
- Cron/scheduling uses an in-process scheduler with durable DB-backed state.

## 19. Product Contract (User Experience)
- Users create named Actions with schemas and provider config.
- Platform exposes stable HTTPS endpoints, API keys for access, quotas/budgets for safety, schedules for automation, and logs/metrics for visibility.
- Versioning and traffic split support rapid iteration with safe rollback.
- Agencies leverage per-client keys and usage exports for multi-tenant operations.
