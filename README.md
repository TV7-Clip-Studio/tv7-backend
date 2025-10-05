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
