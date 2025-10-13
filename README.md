# FastAPI Production Scaffold — Clean

Fixes included:
- Pydantic lists via JSON arrays in `.env`.
- `email-validator` included via `pydantic[email]`.
- Alembic uses psycopg v3 sync driver; guarded logging config.
- SQLAlchemy engine casts URL to `str()`.
- Prometheus instrumentator added outside lifespan.
- Docker Compose without `version`, and configurable port `${API_PORT:-8000}`.
- Makefile targets: `dev` (hybrid), `up`/`down`, `smoke`, `smoke-fly`.

## Quickstart (local app + Docker Postgres)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d postgres
alembic revision --autogenerate -m "init"
alembic upgrade head
uvicorn app.main:app --reload
```

## Environment

- `BETA_API_KEY` enables the beta API guard (required for `/api/v1/ai` locally and in Fly secrets).
- Optional AgentKit integration uses `AGENTKIT_URL` and `AGENTKIT_API_KEY`.

## Fly smoke test

Deploying to Fly? After `fly deploy`, run:

```bash
make smoke-fly            # hits https://forgotten-app.fly.dev/health
curl -s -X POST https://forgotten-app.fly.dev/api/v1/ai/execute \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $BETA_API_KEY" \
  -d '{"input":"hello"}'
```

## Fly "Safe Mode" (cap cost)

Keep the app on a single tiny Machine so spend never spikes:

```bash
# one-time setup
fly scale vm shared-cpu-1x -a forgotten-app
fly scale memory 256 -a forgotten-app
fly scale count 1 -a forgotten-app

# panic button / go offline instantly
fly scale count 0 -a forgotten-app
# bring it back later
fly scale count 1 -a forgotten-app
```

`fly.toml` already sets 10/20 connection limits and auto-stop, so the app parks itself when idle.

## Testing

- Unit & fast async tests (SQLite-backed fixtures):
  ```bash
  make test
  ```

- Full system tests with real Postgres (requires Docker; spins up a disposable container via Testcontainers):
  ```bash
  make test-integration
  # or: pytest --override-ini addopts= -p no:cov -m integration tests/integration
  ```

  By default the suite tries to start a disposable Postgres via Docker. If Docker isn't available, set
  `TEST_DATABASE_URL` to point at a reachable Postgres instance (e.g. `postgresql+asyncpg://user:pass@host:port/db`).
  You can also override the container image with `TEST_POSTGRES_IMAGE`.
