
## Quickstart (Docker-first)

```bash
cp .env.example .env
make up             # runs docker compose up --build in the foreground
```

`make up` launches the API, worker, Postgres, and Redis services and follows the logs so you can watch the pipeline in real time. To stop everything, press `Ctrl+C` or run `make down`.

### Running multiple local instances

Compose projects are isolated by name and host ports. Override them per instance:

```bash
COMPOSE_PROJECT_NAME=tv7a \
  API_PORT=8010 \
  POSTGRES_PORT=5440 \
  REDIS_PORT=6380 \
  make up
```

Create admin user:
```bash
COMPOSE_PROJECT_NAME=tv7a docker compose exec api bash -lc "./scripts/create_admin_user.sh --email joaquinastelarra@gmail.com --full-name 'Operator'"
```


Launch a second copy from another checkout (or the same one) with different values to avoid port collisions. Each project gets its own container and volume namespace (`<project>_pgdata`), so data stays separate. Repeat the pattern for as many instances as you need, locally or on remote hosts.

Add the overrides to your `.env` (or a copy per checkout) so `make up` uses them automatically:

```
# Docker-only: keep these out of Fly secrets
COMPOSE_PROJECT_NAME=tv7a
API_PORT=8010
POSTGRES_PORT=5440
REDIS_PORT=6380
```

Replace the values per instance. These variables only affect local Docker Compose port bindings; they are not required in hosted environments such as Fly.

### Alternative: direct uvicorn

If you prefer to run without Docker (e.g., quick unit testing), you can still bootstrap a virtualenv and start Uvicorn manually:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src
```

## Environment

- `BETA_API_KEY` enables the beta API guard (required for `/api/v1/ai` locally and in Fly secrets).
- Optional AgentKit integration uses `AGENTKIT_URL` and `AGENTKIT_API_KEY`.
- Dramatiq worker settings:
  - `REDIS_URL` (default `redis://localhost:6379/0` locally; `redis://redis:6379/0` in Docker).
  - `DRAMATIQ_BROKER` (`stub` for tests/standalone dev, `redis` when the queue is available).
  - `WORKER_CONCURRENCY` controls the worker pool size.
- Host-port overrides for Docker Compose instances:
  - `API_PORT` (defaults to `8000`).
  - `POSTGRES_PORT` (defaults to `5432`).
  - `REDIS_PORT` (defaults to `6379`).
  Set them per shell invocation to run multiple stacks side-by-side.
- JWT auth settings:
  - `JWT_SECRET` and `JWT_ALGORITHM` sign API tokens (default `HS256`).
  - `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRES_MINUTES` control expiry windows.

### Authentication

Use `/api/v1/auth/login` to obtain an access token (`Authorization: Bearer <token>`). Protected routes (users, videos, ai) require this header. The Swagger UI persists the token via the standard “Authorize” dialog—paste the bearer token once and all subsequent calls are authenticated. Refresh tokens are issued alongside access tokens; exchange them via `/api/v1/auth/refresh` when needed.

- Seed or update an operator account via `scripts/create_admin_user.sh`:

  - **All-local Postgres:** ensure `DATABASE_URL` points at `localhost` and run the script directly.

  ```bash
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/appdb \
    scripts/create_admin_user.sh --email you@example.com --full-name "Operator"
  ```

- **Docker Compose Postgres:** execute the script inside the `api` container so the `postgres` hostname resolves.

  ```bash
  docker compose exec api \
    scripts/create_admin_user.sh --email you@example.com --full-name "Operator"
  ```

- **Fly.io:** let the script invoke the remote container by passing `--fly` (optionally `--fly-app <name>`).

  ```bash
  scripts/create_admin_user.sh --fly --email you@example.com --full-name "Operator"
  ```

  The script prompts for a password, hashes it, and upserts the user record.

## Admin dashboard credentials

- Generate or rotate the HTTP Basic credentials with `make admin-credentials`.
- The command writes `ADMIN_USERNAME`/`ADMIN_PASSWORD` to `.env`, syncs them to Fly via `fly secrets set` (requires `fly` CLI logged in), and prints the values for reference.
- If the Fly sync fails or you skipped the Make target, set secrets manually: `fly secrets set ADMIN_USERNAME=... ADMIN_PASSWORD=... -a $FLY_APP`.
- Redeploy after updating secrets so the FastAPI app picks up the new credentials.

### Background worker

Run the Dramatiq worker alongside Redis:

```bash
docker compose up redis worker  # launches queue + worker
# or, with a stub broker for quick smoke tests:
DRAMATIQ_BROKER=stub make worker
```

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

### Managed Postgres (Neon)

We host production/staging Postgres on Neon. The full setup guide—covering pooler vs. direct endpoints, environment variables, Fly secrets, and migration commands—lives in `docs/neon_postgres.md`. Consult that document when provisioning or rotating credentials.

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

See `docs/testing.md` for an overview of the unit, system, and integration layers plus guidance on where to place new scenarios.
