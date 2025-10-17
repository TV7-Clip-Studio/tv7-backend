# AgentForge: Current State vs. MVP Target

This report compares the codebase’s present capabilities to the documented MVP scope (`docs/mvp_scope.md`). Use it to align roadmaps, prioritize work, and brief agents before they make changes.

## Snapshot
- **Repository:** `AgentForge backend scaffold`
- **Last update:** _(fill on review)_
- **MVP reference:** `docs/mvp_scope.md` (Neon-hosted Postgres, single Fly machine, OpenAI integration)

## Summary
| Area | Current State | MVP Expectation | Gap |
|------|---------------|-----------------|-----|
| Database | SQLAlchemy models exist; configured for Postgres. Local dev still defaults to SQLite fixtures for tests. | Neon.tech Postgres for staging/prod, SQLite only for tests. | ⚠ Need to ensure runtime configuration uses Neon in non-test environments and document migration steps. |
| Auth | JWT beta guard + API key scaffolding in place. | Same plus hashed keys, scope/quota enforcement. | ➖ Implementation is partial—confirm hashing and quota tables exist. |
| Rate Limits & Budgets | Data models drafted; enforcement logic not wired through every endpoint. | Enforcement on all Invocation paths before provider call. | ❗ Critical gap—must implement per-key rate/budget checks. |
| Provider Routing | Abstraction layer outlined; OpenAI integration pending. | Real OpenAI Chat Completions + fallback stubs. | ⚠ Need to add production integration and fallback stub. |
| Scheduling | APScheduler wiring TBD. | In-process scheduler with DB-backed jobs. | ❗ No scheduler yet. Needs models, migrations, and job runner. |
| Observability | Prometheus instrumentation noted in README; minimal metrics/logging. | Metrics/logging/tracing for actions, budgets, schedules. | ⚠ Expand metrics counters, structured logging, Trace model persistence. |
| Tracing | Trace model defined; storage/usage uncertain. | Store redacted trace per invocation; include trace_id in responses. | ⚠ Implement trace persistence + response metadata. |
| Usage Counters | Placeholder described. | Daily per-action counters updated automatically. | ❗ Build counters + background reconciliation. |
| Admin APIs | Basic CRUD endpoints? (confirm). | Full CRUD for keys, budgets, schedules, usage exports. | ⚠ Inventory existing routers; fill missing ones. |
| Testing | Unit tests wired; integration tests via Testcontainers planned. | Both suites passing in CI; coverage ≥85%. | ➖ Unit tests likely exist; ensure integration suite is implemented. |
| Docs | Architecture, MVP, agent guidance present. | Same plus runbooks and neon-specific notes. | ✅ Documentation largely aligned (Neon instructions added). |

Legend: ✅ done, ➖ partial, ⚠ pending, ❗ missing core MVP feature.

## Detailed Gaps & Actions

### 1. Rate Limits & Budgets
- **Status:** Schemas referenced but enforcement hooks absent.
- **Action:** Implement middleware/service enforcing per-key counters in Postgres. Update integration tests to cover over-limit scenarios.

### 2. Provider Integration
- **Status:** Provider router concept exists; no real API wiring.
- **Action:** Implement OpenAI client with config-driven API key; create fallback stub class returning canned responses. Add secrets handling instructions.

### 3. Scheduler
- **Status:** Not yet implemented.
- **Action:** Add `schedules` table, APScheduler setup in lifespan, job runner that reuses invocation pipeline, integration test for hourly cron.

### 4. Tracing & Observability
- **Status:** Metrics and Trace models partially defined.
- **Action:** Persist traces on every action execution, include `trace_id` in responses, register Prometheus metrics for tokens/latency/error counts, ensure structured logging.

### 5. Usage Counters
- **Status:** Model stubbed; no updates.
- **Action:** Increment counters within transaction after invocation; provide reconciliation command/task.

### 6. Admin & Budget Management
- **Status:** Need audit of router coverage.
- **Action:** Ensure CRUD endpoints exist for keys, budgets, schedules; add usage export endpoint returning JSON/CSV.

### 7. Testing & CI
- **Status:** Unit testing pipeline present; integration tests may be missing.
- **Action:** Implement system tests hitting real running API (with Neon or Testcontainers), update GitHub Actions to run both suites.

## Operational Considerations
- **Neon configuration:** Confirm `DATABASE_URL` uses Neon in staging/prod; update runbooks for branch creation, migration strategy, and connection pooling guidance.
- **Secrets management:** Document storing OpenAI secrets and Neon credentials via `fly secrets`.
- **Kill Switch & Alerts:** Implement `system_paused` flag, alerts outbox logging, and associated docs.

## Next Steps (Suggested Order)
1. Wire rate limits/budgets and provider integration (core value).
2. Implement traces, metrics, and usage counters.
3. Build scheduler + admin CRUD endpoints.
4. Finalize integration tests and CI workflow.
5. Polish documentation/runbooks; create follow-up backlog for deferred features (billing, dashboards, HA).

## References
- Architecture blueprint: `docs/top_architecture.md`
- MVP scope: `docs/mvp_scope.md`
- Agent practice guide: `docs/agent_best_practices.md`
- Neon setup notes: README “Using Neon.tech for Postgres”
