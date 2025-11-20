# TV7 Technology Stack

> Complete inventory of technologies, libraries, and tools used in TV7. This is a reference document for understanding dependencies and version requirements.

## Runtime Environment

**Python 3.12.12**
- Target version for all development and deployment
- Uses modern type hints (`|` unions, `from __future__ import annotations`)
- Required for async features and SQLAlchemy 2.0 compatibility

---

## Web Framework

### FastAPI 0.115+
- Async-first web framework for high-performance APIs
- Automatic OpenAPI/Swagger documentation at `/docs`
- Pydantic integration for request/response validation
- Dependency injection system for clean architecture

### Uvicorn 0.30+ (with standard extras)
- ASGI server for serving FastAPI applications
- `[standard]` includes websockets, watchfiles for auto-reload
- Used in development (`--reload`) and production

### Starlette 0.40-0.48
- ASGI toolkit underlying FastAPI
- Provides middleware, routing, and request/response primitives
- Version pinned to avoid breaking changes in newer releases

---

## Data Validation & Configuration

### Pydantic 2.11+ (with email extras)
- Data validation using Python type annotations
- Request/response schemas in FastAPI
- `[email]` extra enables `EmailStr` validation
- Settings management via `pydantic-settings`

### Pydantic Settings 2.4+
- Environment variable loading and validation
- Type-safe configuration in `app/core/config.py`
- Supports `.env` files via `python-dotenv`

### Python Dotenv 1.0+
- Loads `.env` files into environment variables
- Development configuration management
- Not required in production (use native env vars or secrets)

---

## Database Stack

### PostgreSQL (via Neon in production)
- Primary relational database
- Production hosted on Neon with auto-scaling compute
- Development via Docker Compose (`postgres:16`)

### SQLAlchemy 2.0+ (with asyncio extras)
- Async ORM for database operations
- Declarative models in `app/db/models.py`
- Session management via `AsyncSession`
- `[asyncio]` extra provides async drivers support

### Database Drivers

**asyncpg 0.29+**
- Async PostgreSQL driver for runtime queries
- Used in `DATABASE_URL` connection string (`postgresql+asyncpg://...`)
- High-performance binary protocol

**psycopg 3.2+ (with binary extras)**
- Sync PostgreSQL driver for migrations and admin scripts
- Used in `DATABASE_ADMIN_URL` (`postgresql+psycopg://...`)
- `[binary]` extra improves performance

**aiosqlite 0.19+**
- Async SQLite driver for testing
- Used in unit tests for fast in-memory databases
- No production usage

### Alembic 1.14+
- Database migration tool
- Manages schema changes in `alembic/versions/`
- Sync-only, uses `DATABASE_ADMIN_URL`

---

## Background Processing

### Dramatiq 1.16+ (with redis extras)
- Async task queue for background jobs
- Actors in `app/services/tasks.py`
- `[redis]` extra includes Redis broker support

### Redis 5.0+
- Message broker for Dramatiq
- Also used for rate limiting and caching (future)
- Docker Compose service or external (Upstash, etc.)

**Queue Architecture:**
- API enqueues tasks (video ingestion, processing)
- Separate worker process consumes tasks (`scripts/run_worker.py`)
- Configurable via `REDIS_URL`, `DRAMATIQ_BROKER`, `WORKER_CONCURRENCY`

---

## Authentication & Security

### python-jose 3.3+ (with cryptography extras)
- JWT encoding and decoding
- Used in `app/core/jwt.py`
- `[cryptography]` extra provides secure signing algorithms

### passlib 1.7+ (with bcrypt extras)
- Password hashing and verification
- Bcrypt algorithm for user passwords
- Constant-time comparison prevents timing attacks

**Auth Flow:**
- JWT access tokens (short-lived, bearer auth)
- JWT refresh tokens (long-lived, exchange for new access tokens)
- Cookie-based sessions for admin dashboard (uses same JWT)

---

## YouTube Integration

### yt-dlp 2024.0+
- YouTube video downloader (actively maintained youtube-dl fork)
- Downloads best available video stream
- Extracts metadata (duration, title, etc.)
- Used in `app/services/youtube_downloader.py`

### youtube-transcript-api 0.6.0+
- Fetches video transcripts/closed captions
- Tries manual captions first, falls back to auto-generated
- Critical for highlight detection pipeline

---

## AI & LLM

### OpenAI 1.0.0+
- Official OpenAI Python client
- Used for GPT-based highlight detection
- Configured via `OPENAI_API_KEY`
- Highlight detection in `app/services/highlight_detector.py`

**Usage:**
- Sends video transcripts to GPT models
- Receives structured JSON responses (segment timings + hooks)
- Validates outputs with Pydantic schemas

---

## Frontend & Templating

### Jinja2 3.1+
- Template engine for admin HTML pages
- Templates in `src/app/templates/admin/`
- Server-side rendering with dark theme styling

### python-multipart 0.0.9+
- Parses form data (multipart/form-data)
- Required for HTML form submissions in admin dashboard
- Used in login, ingestion, and user management forms

**Design Philosophy:**
- No frontend framework (React, Vue, etc.)
- Inline CSS for simplicity and zero build step
- Future may add HTMX for dynamic updates

---

## Observability & Monitoring

### JSON Logging (Python stdlib)
- Custom JSON formatter built on Python's `logging` module (`app/core/logging.py`)
- Includes timestamp, level, logger name, and any `extra={}` context (video IDs, clip IDs)
- Used by both API and worker processes; safe to stream via `docker compose logs -f`

### prometheus-fastapi-instrumentator 7.0+
- Automatic Prometheus metrics for FastAPI
- Exposes `/metrics` endpoint
- Tracks request counts, latencies, error rates
- Initialized in `app/main.py`

---

## Testing Stack

### pytest 8.0+
- Test runner and framework
- Async support via `pytest-asyncio`
- Markers: `@pytest.mark.system`, `@pytest.mark.integration`

### pytest-asyncio 0.23+
- Async test support
- `asyncio_mode = "auto"` in `pyproject.toml`
- Fixtures return awaitable objects

### pytest-cov 4.1+
- Code coverage reporting
- Configured for 85% minimum coverage (`--cov-fail-under=85`)
- Coverage reports in terminal and CI

### httpx 0.27+
- Async HTTP client for testing FastAPI
- Used with `AsyncClient` in system/integration tests
- Replaces `requests` for async compatibility

### asgi-lifespan 2.1+
- Manages FastAPI app lifecycle in tests
- Ensures startup/shutdown events fire correctly
- Used in system tests (`LifespanManager(app)`)

### testcontainers 4.8.2+ (with postgres extras)
- Spins up real PostgreSQL in Docker for integration tests
- `[postgres]` extra provides pre-configured Postgres container
- Skipped if `TEST_DATABASE_URL` is set

### trio 0.23+
- Async runtime alternative to asyncio
- Improves test isolation and debugging
- Optional dependency for pytest-asyncio

---

## Code Quality Tools

### black 24.0+
- Opinionated code formatter
- Line length: 100 characters
- Runs in pre-commit hook and CI

### ruff 0.5.0+
- Fast Python linter (replaces flake8, isort, pyupgrade)
- Selected rules: E, F, I, UP, B, C4, SIM, ARG, PL
- Auto-fixes imports and simple issues

### mypy 1.10+
- Static type checker
- Strict mode enabled (disallow_untyped_defs, etc.)
- Excludes `alembic/` directory

### bandit 1.7+
- Security linter
- Scans for common vulnerabilities (SQL injection, hardcoded secrets, etc.)
- Runs in pre-commit and CI

### pre-commit 3.7+
- Git hook framework
- Runs black, ruff, mypy, bandit, pytest before commits
- Configured in `.pre-commit-config.yaml`

---

## Infrastructure & Deployment

### Docker & Docker Compose
- Containerization for development and deployment
- `Dockerfile` for FastAPI app
- `docker-compose.yml` for local multi-service setup
- Services: API, worker, Postgres, Redis

### Fly.io
- Production hosting platform
- Configured via `fly.toml`
- Supports multiple machines and regions
- Auto-stop and scaling features enabled

### Neon
- Serverless Postgres provider
- Auto-scaling compute and storage
- Branching support for preview environments
- See `docs/neon_postgres.md` for setup details

---

## Version Matrix

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| Python | 3.12.12 | 3.12.12 | Strict requirement |
| FastAPI | 0.115 | Latest 0.x | Stable API |
| SQLAlchemy | 2.0 | 2.0+ | Async support required |
| PostgreSQL | 14 | 16 | Neon uses 16 |
| Redis | 5.0 | 7+ | Dramatiq compatible |
| Node.js | N/A | N/A | Not used (no build step) |

---

## Dependency Management

**Installation:**
```bash
pip install -e ".[dev]"  # Installs all dependencies including dev tools
```

**Lock files:** Not currently used (consider `uv` or `pip-tools` for future)

**Security updates:** Use `pip list --outdated` and review CVE databases regularly

---

## Future Considerations

**Potential additions:**
- **ffmpeg** - For video clipping and subtitle burning (Phase 1.8-1.9)
- **Pillow** - For thumbnail generation and image processing
- **HTMX** - For dynamic admin UI without JavaScript frameworks
- **Sentry** - For error tracking and performance monitoring
- **Upstash** - For serverless Redis alternative

**Deprecation candidates:**
- None currently; all dependencies are actively maintained
