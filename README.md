# FastAPI Production Scaffold — Clean

Fixes included:
- Pydantic lists via JSON arrays in `.env`.
- `email-validator` included via `pydantic[email]`.
- Alembic uses psycopg v3 sync driver; guarded logging config.
- SQLAlchemy engine casts URL to `str()`.
- Prometheus instrumentator added outside lifespan.
- Docker Compose without `version`, and configurable port `${API_PORT:-8000}`.
- Makefile targets: `dev` (hybrid), `up`/`down`, `smoke`.

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
