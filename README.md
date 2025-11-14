
## Quickstart (Docker-first)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start all services
make up             # runs docker compose up --build in the foreground

# 3. Verify API is running (in another terminal)
curl http://localhost:8000/health
```

`make up` launches the API, worker, Postgres, and Redis services and follows the logs so you can watch the pipeline in real time.

**Note:** The default port is `8000`. If you changed `API_PORT` in `.env`, use that port instead.

To stop everything, press `Ctrl+C` or run `make down`.

### Requirements

- **Docker workflow:** Docker + Compose install (Node.js is pre-installed in the image; no extra setup).
- **Local workflow (without Docker):** Python 3.12, Node.js 18+ (required by yt-dlp to execute YouTube’s player JavaScript and enumerate formats), Postgres 16, and Redis 7.

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

## Development Workflow

### Docker Development (Recommended)

The Docker setup includes **hot-reload** for the API service. Code changes in `src/`, `alembic/`, and templates automatically reload the server without rebuilding.

#### Start everything in background:
```bash
make up DETACH=1
# or: docker compose up -d
```

#### View logs:
```bash
docker compose logs -f api worker
# or: make logs (API + Postgres only)
```

#### When to restart vs rebuild:

**✅ Code changes** → Auto-reload (no action needed)
- Changes to Python files in `src/`
- Changes to Jinja templates
- Changes to Alembic migrations

**🔄 Environment changes** → Restart only
```bash
docker compose restart api worker
```

**🏗️ Dependency changes** → Rebuild
```bash
docker compose down
docker compose up --build -d
# or: make down && make up DETACH=1
```

**⚙️ Worker code changes** → Restart worker
```bash
docker compose restart worker
```

#### Run database migrations:
```bash
docker compose exec api alembic upgrade head
# or: docker compose exec api make upgrade
```

#### Stop everything:
```bash
make down
# or: docker compose down
```

### Local Development (Direct uvicorn)

For faster iteration without Docker (requires local Postgres and Redis):

#### First-time setup:
```bash
# Create virtualenv and install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env: set DATABASE_URL to localhost Postgres, REDIS_URL, etc.

# Start local Postgres (if needed)
docker compose up -d postgres redis
```

#### Run API with hot-reload:
```bash
# Option 1: Using uvicorn directly
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir src

# Option 2: Using make
make dev  # Starts Postgres in Docker, API locally with hot-reload
```

#### Run worker locally:
```bash
# With Redis broker (requires redis running)
DRAMATIQ_BROKER=redis make worker

# With stub broker (inline processing, no worker needed)
DRAMATIQ_BROKER=stub  # Set in .env, then start API only
```

#### VS Code debugging:
1. Select Python interpreter: `Cmd+Shift+P` → "Python: Select Interpreter" → `.venv/bin/python`
2. Set breakpoints in your code
3. Press `F5` → Select "uvicorn" or "pytest: Current file"
4. See [.vscode/launch.json](.vscode/launch.json) for available debug configurations

### Common Development Tasks

```bash
# Code quality checks (run before committing)
make fmt           # Format code with Black and Ruff
make lint          # Check linting rules
make type          # Run mypy type checking
make sec           # Security scan with Bandit

# Database migrations
make revision m="add new field"  # Create new migration
make upgrade                      # Apply pending migrations
make downgrade                    # Rollback last migration

# Create admin user
docker compose exec api scripts/create_admin_user.sh --email admin@test.com --full-name "Admin"

# View application logs
docker compose logs -f api         # API logs only
docker compose logs -f worker      # Worker logs only
docker compose logs -f api worker  # Both

# Access running container
docker compose exec api bash       # Shell into API container
docker compose exec api python     # Python REPL with app context

# Clean up Docker resources
docker compose down -v             # Stop and remove volumes (fresh DB)
docker system prune                # Clean up unused Docker resources
```

## Environment

- `BETA_API_KEY` enables the beta API guard (required for `/api/v1/ai` locally and in Fly secrets).
- Optional AgentKit integration uses `AGENTKIT_URL` and `AGENTKIT_API_KEY`.
- Dramatiq worker settings:
  - `REDIS_URL` (default `redis://localhost:6379/0` locally; `redis://redis:6379/0` in Docker).
  - `DRAMATIQ_BROKER` (`stub` for tests/standalone dev, `redis` when the queue is available). When `stub` is active the entire download + highlight pipeline runs inline inside the API process, so video status transitions (`INGESTED → PROCESSING → READY`) appear immediately for admin operators without running `make worker`.
  - `WORKER_CONCURRENCY` controls the worker pool size.
- API origin (used for OAuth redirects, UI tests, and Docker port binding):
  - `API_SCHEME` (defaults to `http`).
  - `API_HOST` (defaults to `127.0.0.1`).
  - `API_PORT` (defaults to `8000`).
  Set `API_PORT` per checkout when running multiple instances; Docker Compose inherits it automatically.
- YouTube download authentication:
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_PATH` configure Google OAuth. The full redirect URI is derived from `API_SCHEME`/`API_HOST`/`API_PORT`.
  - `YOUTUBE_OAUTH_SCOPES` controls requested scopes (defaults to `youtube.readonly`).
  - Optional `YOUTUBE_COOKIES_FILE` / `YOUTUBE_COOKIES_BROWSER` values fall back to cookie-based auth when OAuth is not configured.
- Host-port overrides for Docker Compose instances:
  - `POSTGRES_PORT` (defaults to `5432`).
  - `REDIS_PORT` (defaults to `6379`).
  Set them per shell invocation to run multiple stacks side-by-side.
- JWT auth settings:
  - `JWT_SECRET` and `JWT_ALGORITHM` sign API tokens (default `HS256`).
  - `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRES_MINUTES` control expiry windows.

### Authentication

#### Connecting a YouTube account (admin dashboard)

Age-restricted / “confirm you’re not a bot” videos require an authenticated YouTube session. Each operator can connect their account via OAuth:

1. Configure the environment:
  - `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` from the Google Cloud console.
  - `YOUTUBE_REDIRECT_PATH` (default `/admin/youtube/callback`). The full redirect URI automatically includes your current scheme/host/port, so in Google Cloud you’d register `http://127.0.0.1:8010/admin/youtube/callback` locally or `https://<your-domain>/admin/youtube/callback` on Fly.
2. Restart the API so the new settings load.
3. In the admin dashboard, click **Connect YouTube** (above the ingest form) and follow Google’s consent screen.
4. Once connected, downloads run “on behalf of” that user and tokens refresh automatically. Use **Disconnect** to revoke access.

When OAuth isn’t configured, the dashboard prompts operators to connect using cookies instead.

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

### Media cleanup

Delete stale media directories when records have been removed or the pipeline crashed mid-job:

```bash
python scripts/cleanup_media.py           # list orphans (videos + clips)
python scripts/cleanup_media.py --delete # remove them from disk
```
Set `--media-dir` if your media root isn’t the default `MEDIA_STORAGE_DIR`.

### Fly deployment checklist

1. **Set secrets** (replace values with your own; the Redis URL can come from Upstash, Fly Redis, etc.):
   ```bash
   fly secrets set \
     DATABASE_URL="postgresql+asyncpg://..." \
     DATABASE_ADMIN_URL="postgresql+psycopg://..." \
     REDIS_URL="redis://default:<password>@<host>:<port>/0" \
     DRAMATIQ_BROKER=redis \
     YOUTUBE_COOKIES_B64="$(base64 -w0 youtube_cookies.txt)" \
     YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt \
     -a forgotten-app
   ```

2. **Deploy and scale both processes** (API + worker):
   ```bash
   fly deploy -a forgotten-app
   fly scale count app=1 worker=1 -a forgotten-app
   ```

   The `app` process runs Uvicorn on `0.0.0.0:8000`; the `worker` process runs Dramatiq pointed at `REDIS_URL`. Scale them independently as load grows (`fly scale count app=2 worker=1`, etc.).

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

We host production/staging Postgres on Neon. The full setup guide—covering pooler vs. direct endpoints, environment variables, Fly secrets, and migration commands—lives in [docs/setup/neon_postgres.md](docs/setup/neon_postgres.md). Consult that document when provisioning or rotating credentials.

## Testing

### Quick Reference

```bash
# Run all unit tests (fast, SQLite-backed)
make test

# Run with coverage report
make testcov

# Run integration tests (requires Docker)
make test-integration

# Run entire suite sequentially (non-UI + UI)
make test-suite

# Run pipeline regression tests
make pipeline-smoke

# Run UI browser test (Playwright, honors PWHEADLESS/PWSLOWMO)
make test-ui
# Run full Playwright suite
make ui-smoke
```

### Test Types

**Unit Tests** (unmarked, fast)
```bash
make test
# or: pytest tests/ -v --no-cov
```
- SQLite-backed fixtures
- No external dependencies
- Covered by default in `make test`

**Integration Tests** (marked with `@pytest.mark.integration`)
```bash
make test-integration
# or: pytest -m integration tests/integration
```
- Requires Docker (spins up disposable Postgres via Testcontainers)
- Tests with real database
- Override with `TEST_DATABASE_URL` if Docker unavailable
- Override image with `TEST_POSTGRES_IMAGE`

**System Tests** (marked with `@pytest.mark.system`)
```bash
pytest -m system tests/system -v
```
- End-to-end FastAPI flows
- Uses test database fixtures
- Covered by default in `make test`

**Regression Tests** (marked with `@pytest.mark.regression`)
```bash
make pipeline-smoke
# or: pytest -m regression tests/regression
```
- Full pipeline validation with stubbed externals
- Ensures videos progress: `ingested → processing → ready`
- Validates transcript metadata and clip generation

**UI Tests** (marked with `@pytest.mark.ui`)
```bash
# Start the app first
make up DETACH=1
# Single interactive flow (default headless)
make test-ui
# Slow-mo run for debugging
make test-ui-visual
# Full Playwright suite
make ui-smoke
```
- Playwright browser automation
- Requires running API server
- Tests admin dashboard flows
- `PWHEADLESS` (default `true`) and `PWSLOWMO` (default `0`) control browser visibility/speed
- Set `DRAMATIQ_BROKER=stub` for instant status updates
- Uses the same `ADMIN_USERNAME`/`ADMIN_PASSWORD` credentials as the HTTP Basic gate, so ensure a matching user exists via `scripts/create_admin_user.sh`

**Entire suite (non-UI + UI)**
```bash
make test-suite
```
- Runs every non-UI test with verbose output via `pytest -v`
- Finishes with the interactive UI flow so regressions are easy to spot
- Use `make test-ui-visual` or override `PWHEADLESS=false PWSLOWMO=500` for watchable runs

### Running Specific Tests

```bash
# Single test file
pytest tests/test_tasks.py -v

# Single test function
pytest tests/test_tasks.py::test_process_video -v

# Pattern matching
pytest tests/ -k "youtube" -v

# With coverage for specific module
pytest tests/test_tasks.py --cov=app.services.tasks --cov-report=term-missing
```

### Debugging Tests in VS Code

1. Open the test file
2. Set breakpoints (click left of line number)
3. Press `F5` → Select "pytest: Current file"
4. Or use the Testing panel (flask icon) to run/debug individual tests

See [docs/guides/testing.md](docs/guides/testing.md) for an overview of test architecture and where to place new scenarios.
