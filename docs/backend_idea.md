# AgentForge: A Hosted AI Actions Runtime (Backend Overview)

## Purpose
AgentForge is a hosted runtime for AI actions—callable functions that package prompts, schemas, and provider configuration—and exposes them as stable HTTP endpoints with authentication, limits, scheduling, logging, and analytics. The backend delivers the operational layer teams typically avoid rebuilding: safe execution, observability, and cost control for AI workflows.

## Core Value (Backend Perspective)
- **Composure:** uniform contract to define and execute AI actions across providers.
- **Safety:** strict pre-call rate limits, token budgets, and hard stops eliminate runaway costs.
- **Visibility:** structured traces, metrics, and usage counters make behavior observable and debuggable.
- **Automation:** cron-style schedules run actions without external glue code.
- **Multi-tenancy:** per-user/per-client keys, quotas, and usage exports support agencies and small teams.

## System Boundary
- Sits behind a CDN/WAF (e.g., Cloudflare) and exposes a versioned REST API.
- Runs on Fly.io as a FastAPI application with Prometheus instrumentation.
- Uses Postgres (or configured SQL database) via SQLAlchemy and Alembic migrations.
- Calls external AI providers through a provider router with timeouts, retries, and fallbacks.
- Supports user-supplied provider keys to externalize inference spend.

## Responsibilities
- Manage the full action lifecycle: define, store, version, invoke.
- Execute the happy path: validate input → enforce limits/budgets → route provider call → capture trace → update usage → respond with output + meta.
- Access control: issue/revoke API keys, scope and quota by user/client.
- Scheduling: persist and run time-based jobs with idempotency and backoff.
- Observability: publish metrics; retain redacted request/response traces.
- Cost controls: pre-call guardrails, hard-stop on budget breach, operational kill switch.

## Non-Responsibilities
- Building a frontend UI beyond OpenAPI/Swagger docs.
- Running long batch pipelines that exceed provider/request timeouts.
- Training or fine-tuning models; focus remains on orchestration, not model hosting.

## High-Level Components
- **API Gateway (v1):** routers for Actions, Versions, Keys, Limits/Budgets, Schedules, Metrics, Traces, Users.
- **Actions Runtime:** executor that performs validation, guardrails, provider call, tracing, and counter updates.
- **Provider Router:** normalized interface to AI vendors (OpenAI first) with configurable fallback chains.
- **Scheduling Service:** cron-like engine backed by the database; tracks last/next run and status.
- **Security Layer:** token/key validation, host/CORS controls, PII redaction for logs/traces.
- **Observability Layer:** Prometheus metrics and structured logs tied to `trace_id`.

## Data Model Snapshot
- **User:** identity and ownership.
- **Action:** name, slug, input/output schema, provider config, flags.
- **ActionVersion:** prompt/config per version; active state and traffic-split metadata.
- **Key:** hashed API key, scopes, optional client ID, quotas.
- **Budget:** per-action caps (tokens/requests), period, hard-stop flag.
- **UsageCounter:** per day/action tallies of requests and tokens.
- **Schedule:** cron expression, active flag, last/next run timestamps.
- **Trace:** redacted payloads, tokens in/out, latency, status, error code, version/model, caller key.

## Execution Flow (Happy Path)
1. Request arrives with `x-api-key` or Bearer token to resolve caller and client.
2. Validation ensures input matches the declared schema.
3. Guardrails enforce rate limits, budgets, and hard-stop checks.
4. Provider router executes with timeouts, retries, and fallback logic.
5. Trace storage and counters update; metrics emit for Prometheus.
6. Response returns `{output, meta}` including `trace_id`, tokens, latency, version/model.

## Error Model
- JSON shape: `{"error": {"code": "...", "message": "...", "trace_id": "..."}}`.
- Provider errors map to `AI_PROVIDER_*` codes; platform errors include `RATE_LIMIT_EXCEEDED`, `BUDGET_EXCEEDED`, `VALIDATION_ERROR`, etc.

## Security & Privacy Posture
- API keys hashed at rest; secrets loaded via environment variables.
- Default PII redaction for trace storage/logging on sensitive fields.
- Strict CORS/Trusted Hosts, upload body-size limits, short timeouts on network calls.

## Cost & Risk Controls
- Pre-call rate/budget enforcement prevents overspend.
- Hard-stop disables actions once caps are hit and sends alerts (webhook/Slack/email).
- Operational kill switch scales the app to zero during emergencies.

## Operability
- Prometheus metrics track requests, tokens, latency, error rates per action/version.
- Structured logs include correlation/trace IDs.
- OpenAPI specification supports discoverability and client generation.

## Extensibility
- New models/providers plug in via the router without API surface changes.
- New action types follow the same contract (schema + config + version).
- Versioning supports rollbacks and traffic splits for safe experimentation.

## Deployment Posture (MVP)
- Single small Fly.io machine (no autoscale) for predictable cost.
- Database migrations via Alembic; health/readiness endpoints for probes.
- CDN/WAF fronting the API for rate limiting and basic DDoS protection.

## Product Contract (API Experience)
- Create actions with declarative schemas and prompts.
- Receive stable HTTPS endpoints to invoke actions immediately.
- Configure keys, quotas, budgets, and schedules without touching infrastructure.
- Inspect traces and metrics to debug or optimize.
- Iterate via versions with safe rollback and optional A/B split.

## Observations & Potential Gaps
- **Tenant boundaries:** Document how per-client data isolation is enforced (schema, RLS, or service layer constraints).
- **Trace retention:** Define retention windows or archival plans to control storage costs.
- **Alerting workflow:** Clarify delivery mechanism (queue/outbox, retries) for Slack/webhook/email alerts.
- **Scheduler scaling:** In-process scheduling suffices for single-machine MVP; outline path to distributed coordination when scaling horizontally.
- **Secrets storage:** Elaborate on encrypting provider credentials or integrating with a secret manager.
- **Analytics consumers:** Identify who consumes analytics (internal dashboards, customer exports) and how access is secured.

## One-Line Summary
AgentForge runs AI as safe, observable, budget-capped endpoints—turning prompts into production-grade actions with versioning, quotas, and automation, all from a compact FastAPI backend.
