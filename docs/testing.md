# Testing Strategy

This project keeps separate test layers so contributors can run quick feedback loops locally while still exercising the full deployment shape in CI. Use the following guide when deciding where a new test belongs.

## Test Suite Overview

| Suite | Location | Runtime | What it covers |
| --- | --- | --- | --- |
| Unit / API | `tests/` | milliseconds–seconds | Pure functions, API routers with dependency overrides, schema serialization, error handling. |
| System | `tests/system/` | seconds | In-process FastAPI app running with real dependency wiring (lifespan, middleware, repositories) and stubbed external collaborators. Verifies end-to-end request/response behaviour plus database effects. |
| Integration | `tests/integration/` | seconds–minutes | Full environment using Testcontainers Postgres (or `TEST_DATABASE_URL`) with Alembic migrations. Ensures persistence and infrastructure wiring behave like production. |

Run the whole suite locally with `make test`. Run `make test-integration` when you need the container-backed checks.

## System Tests

System tests sit between the fast API tests and the heavier integration suite. They:

- Boot the real FastAPI application via `asgi-lifespan` so middleware, dependency overrides, and startup events execute.
- Override `app.deps.db.get_session` to reuse the async session factory from `tests/conftest.py` while keeping each request transactional.
- Stub external side effects (e.g., background queue dispatch) using `monkeypatch`/`AsyncMock` so we can assert scheduling while avoiding long-running jobs.

Add new system tests in `tests/system/` when you need to exercise:

- A full HTTP flow that depends on multiple layers (router → service → repository → DB).
- Error envelopes or auth middleware interactions.
- Behaviour that should remain stable across refactors but doesn’t require spinning up Postgres or other remote services.

Tag them with `@pytest.mark.system` (registered in `pyproject.toml`) so they can be filtered via `pytest -m system`.

## Integration Tests

Integration tests live under `tests/integration/` and run with either Testcontainers Postgres or an override URL. They reload the FastAPI app so settings and Alembic migrations match production. Use this suite when you need to validate SQL migrations, async drivers, or interactions that depend on a real database engine.

If Docker is unavailable locally, set `TEST_DATABASE_URL` to point at a Postgres instance; the fixtures will skip gracefully otherwise.

## Writing New Tests

1. Prefer the fastest layer that still exercises the behaviour you’re touching.
2. Use dependency overrides (`app.dependency_overrides[...]`) or fixtures to inject fake collaborators.
3. When tests mutate environment variables (like `BETA_API_KEY`), set them with `monkeypatch` to avoid cross-test leakage.
4. Keep assertions focused on externally observable behaviour—responses, DB state changes, queued jobs—rather than private implementation details.

Refer to `tests/system/test_videos_api_system.py` and `tests/integration/test_users_api_integration.py` as examples for new scenarios.

