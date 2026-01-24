# Testing Strategy

This project keeps separate test layers so contributors can run quick feedback loops locally while still exercising the full deployment shape in CI. Use the following guide when deciding where a new test belongs.
> **Legacy notice:** Pipeline/system/UI sections reflect the pre-cleanup media workflow. The FastAPI backend now runs as a control plane without ingestion or Dramatiq; admin UI is minimal and currently untested by Playwright.

## Test Suite Overview

| Suite | Location | Runtime | What it covers |
| --- | --- | --- | --- |
| Unit / API | `tests/` | milliseconds–seconds | Pure functions, API routers with dependency overrides, schema serialization, error handling. |
| System (retired) | — | — | Legacy in-process coverage removed with the media pipeline cleanup. |
| Integration (retired) | — | — | Testcontainers-backed suite removed; reroute new coverage to fast unit/API tests. |
| Regression (retired) | — | — | Pipeline smoke tests removed alongside ingestion/rendering. |
| UI (retired) | — | — | Admin dashboard browser flows removed with the admin UI. |

Run the current suite with `make test` or `make testcov`. Integration/regression/UI targets were removed during the Phase 1 cleanup; add new coverage under `tests/` as the control-plane features evolve.

## System Tests

System tests sit between the fast API tests and the heavier integration suite. They:

- Boot the real FastAPI application via `asgi-lifespan` so middleware, dependency overrides, and startup events execute.
- Override `app.deps.db.get_session` to reuse the async session factory from `tests/conftest.py` while keeping each request transactional.
- Stub external side effects (e.g., background queue dispatch) using `monkeypatch`/`AsyncMock` so we can assert scheduling while avoiding long-running jobs.
- Authenticate through `/api/v1/auth/login`; fixtures such as `system_client` request a JWT and attach it to every call.

Add new system tests in `tests/system/` when you need to exercise:

- A full HTTP flow that depends on multiple layers (router → service → repository → DB).
- Error envelopes or auth middleware interactions.
- Behaviour that should remain stable across refactors but doesn’t require spinning up Postgres or other remote services.

Tag them with `@pytest.mark.system` (registered in `pyproject.toml`) so they can be filtered via `pytest -m system`.

## Integration Tests

Integration tests live under `tests/integration/` and validate behavior with real PostgreSQL instances.

**How they work:**
1. **CI (GitHub Actions)**: Use service container at `localhost:5432` (automatically configured)
2. **Local (testcontainers)**: Automatically spin up Postgres in Docker (default)
3. **Local (manual)**: Set `TEST_DATABASE_URL` to point to existing Postgres instance

Integration tests reload the FastAPI app so settings and Alembic migrations match production. Use this suite when you need to validate SQL migrations, async drivers, or interactions that depend on a real database engine.

**Running integration tests:**
```bash
# Run all tests including integration (what CI does)
make testcov

# Run ONLY integration tests
make test-integration
```

Integration tests:
- Run Alembic migrations against real Postgres
- Test async SQLAlchemy drivers (asyncpg)
- Validate database constraints and transactions
- Ensure schema matches ORM models

If Docker is unavailable locally, set `TEST_DATABASE_URL` to point at a Postgres instance; the fixtures will skip gracefully otherwise.

## CI Test Environment

GitHub Actions CI runs the complete test suite including all integration tests.

**Services available in CI:**
- PostgreSQL 16 (via service container at `localhost:5432`)
- Redis 7 (via service container at `localhost:6379`)
- ffmpeg/ffprobe (installed via apt)

**Environment configuration:**
- `DATABASE_URL`: Points to CI PostgreSQL instance
- `TEST_DATABASE_URL`: Same as DATABASE_URL for integration tests
- `DRAMATIQ_BROKER=stub`: Tests use stub broker, not real Redis
- 15-minute timeout for the entire test job

**Why run integration tests in CI?**
- Ensures database migrations work correctly
- Validates real PostgreSQL compatibility (SQLite differs in subtle ways)
- Catches driver-specific issues (asyncpg, psycopg)
- Maintains high quality bar for production deployments
- Prevents regressions in schema/model alignment

**Local vs CI:**
- **Local**: Integration tests use testcontainers (spins up disposable Postgres in Docker)
- **CI**: Integration tests use GitHub Actions service container (pre-started, shared across test run)
- Both approaches ensure isolation and reproducibility

## Writing New Tests

1. Prefer the fastest layer that still exercises the behaviour you're touching.
2. Use dependency overrides (`app.dependency_overrides[...]`) or fixtures to inject fake collaborators.
3. When a route requires authentication, hit `/api/v1/auth/login` (or use the provided fixtures) to obtain a bearer token instead of bypassing middleware.
4. When tests mutate environment variables, set them with `monkeypatch` to avoid cross-test leakage.
5. Keep assertions focused on externally observable behaviour—responses, DB state changes, queued jobs—rather than private implementation details.
6. Filesystem helpers that orchestrate media layout (e.g., `app.services.render_workspace`) should have direct unit coverage verifying directory creation, public URL generation, and cleanup. See `tests/test_render_workspace.py` for the pattern.
7. ffmpeg-dependent logic (`app.services.clipper`, render stages in `app.services.tasks`) is covered via unit/system tests that stub `subprocess.run`—never rely on real media downloads in CI. Use tiny fixture videos or write placeholder bytes when stubbing commands.

Refer to `tests/system/test_videos_api_system.py` and `tests/integration/test_users_api_integration.py` as examples for new scenarios.
