# Roadmap Rationale

> Companion narrative for `docs/roadmap.md`. Each entry clarifies intent, implementation pointers, and notable dependencies so future maintainers can execute without guesswork.

## Phase 0 — Platform Foundation

### 0.1 — Confirm FastAPI core application ✅
- **Why:** Ensure the monolithic service has a production-grade entrypoint before layering new domains on top.
- **Implementation notes:** `src/app/main.py` wires routers, lifespan hooks, CORS, Prometheus instrumentation, and security middleware. Keep the surface minimal and make new modules route through `app/api/v1/routes.py`.
- **Important:** Continue smoke testing `make smoke` and `make dev` flows after any refactor to catch regressions early.

### 0.2 — Maintain security middleware + API key gating ✅
- **Why:** Protect the service even while it stays private; the upcoming admin UI and endpoints reuse these primitives.
- **Implementation notes:** `SecurityHeadersMiddleware` and `require_beta_key` live in `src/app/core/security.py` and `src/app/deps/security.py`. Any new router should opt in to `Depends(require_beta_key)` unless explicitly public (e.g., health checks).
- **Important:** Document secrets in `.env.example` when new keys are introduced. Keep rate limiting consistent with `app.deps.rate_limit.check_rate`.

### 0.3 — Persistence layer scaffold ✅
- **Why:** Shorts processing hinges on relational state machines; getting SQLAlchemy + Alembic right upfront avoids data churn later.
- **Implementation notes:** `src/app/db/base.py` centralizes Base + session management. Extend `app/db/models.py` with new tables and generate migrations via `make revision m="..."`.
- **Important:** Commit migrations alongside model changes and run `make upgrade` in CI or pre-deploy to ensure compatibility.

### 0.4 — Health and metrics ✅
- **Why:** Background processing will introduce moving parts; basic probes and metrics catch failures quickly.
- **Implementation notes:** `/health`, `/readyz`, `/version`, and Prometheus metrics expose minimal telemetry already. Add custom counters in future pipeline steps if needed.
- **Important:** Keep these endpoints lightweight—no DB calls—to remain dependable during outages.

### 0.5 — Architecture & ops documentation ✅
- **Why:** Hiring managers and collaborators reference `docs/*.md`; keeping legacy context avoid confusion during the transition to Shorts.
- **Implementation notes:** `docs/top_architecture.md`, `docs/agent_best_practices.md`, and `docs/neon_postgres.md` outline current ops runbooks. Update them when removing legacy functionality to prevent drift.
- **Important:** Link new docs (architecture, roadmap, rationale) from the README once the Shorts features ship to guide readers toward the latest vision.

### 0.6 — Fly.io deployment ✅
- **Why:** Production deploy confidence. The future pipeline must run where the app is already live.
- **Implementation notes:** `fly.toml` defines app metadata; `make smoke-fly` hits `/health` remotely. Update secrets using `fly secrets set` when new environment variables (e.g., OPENAI keys, storage buckets) are introduced.
- **Important:** Plan worker processes (Phase 1.3) within Fly’s process groups or separate apps; document the approach here once selected.

### 0.7 — Docker & Compose ✅
- **Why:** Contributors need reproducible local environments to test ffmpeg, LLM stubs, and DB interactions.
- **Implementation notes:** `docker-compose.yml` spins up Postgres and the API. Extend services carefully (e.g., add a worker container) to mirror production architecture.
- **Important:** Document any host dependencies (ffmpeg binaries, GPU access) in README + Compose comments once added.

### 0.8 — Pre-commit automation ✅
- **Why:** Keeps code style and static analysis consistent without manual steps.
- **Implementation notes:** `.pre-commit-config.yaml` runs Black, Ruff, mypy, Bandit, and pytest with coverage. Update `additional_dependencies` when new typing stubs or plugins are required.
- **Important:** Encourage devs to install pre-commit (`make deps`) after cloning; enforce via CI to avoid bypass.

### 0.9 — Makefile ergonomics ✅
- **Why:** One command path ensures local and CI parity, especially for formatters and tests.
- **Implementation notes:** `make fmt/lint/type/sec/testcov` orchestrate the same commands as CI. Add new targets (e.g., `make worker`) when Phase 1 introduces background processing.
- **Important:** Keep targets idempotent. If commands require env vars, provide sensible defaults or `.env` docs.

### 0.10 — Tests (unit + integration) ✅
- **Why:** The Shorts pipeline will introduce async/background complexity; a solid test culture must precede it.
- **Implementation notes:** Current tests cover auth, health, errors, and integrations with the API. Extend fixtures for video ingestion mocks and ffmpeg stubs as modules arrive.
- **Important:** Maintain the `--cov-fail-under=85` threshold; raise it as the codebase grows to retain quality.

### 0.11 — GitHub Actions CI ✅
- **Why:** Guarantees every PR respects formatting, linting, typing, security, and test gates.
- **Implementation notes:** `.github/workflows/ci.yml` installs dev deps and executes `make fmt && make lint && make type && make sec && make testcov`. Mirror any Makefile changes here.
- **Important:** Introduce matrix builds (e.g., Python versions) or additional jobs (Docker build, Fly deploy) once Shorts features are production-ready.

### 0.12 — Admin-route authentication scaffold ✅
- **Why:** The admin UI will expose clips and publish actions; even in MVP form it must be access-controlled.
- **Implementation overview:** Dependency `require_admin` wraps `fastapi.security.HTTPBasic` and validates credentials sourced from `ADMIN_USERNAME`/`ADMIN_PASSWORD` environment variables. Apply `Depends(require_admin)` to every `/admin/*` route to enforce the challenge-response flow.
- **Important:** Rotate credentials by updating environment variables and restarting the process. Missing configuration raises a 500 to surface deployment misconfigurations immediately.

### 0.13 — Operator admin access ✅
- **Why:** Authentication alone isn’t enough; we need a predictable way to bootstrap trusted operators.
- **Implementation overview:** `scripts/admin_credentials.py` (surfaced via `make admin-credentials`) generates a secure password, updates `.env`, and, by default, runs `fly secrets set` for the configured app. Under the hood it relies on `app.admin.credentials` helpers to update .env files safely.
- **Important:** Rotation is a single command locally; ensure operators have the Fly CLI logged in so the auto-sync succeeds. If it fails, fallback instructions appear in the README.

## Phase 1 — Shorts MVP

### 1.1 — `Video` & `Clip` ORM models ✅
- **Why:** These tables capture the lifecycle and metadata for ingestion and clip generation.
- **Implementation overview:** Added `Video`/`Clip` SQLAlchemy models with string-backed status enums (`VideoStatus`, `ClipStatus`), transcript and file-path fields, cascade relationships, and timestamp columns. Alembic revision `1c6c4f5cb4d1` creates `videos` and `clips` tables plus indexes on `videos.status`, `clips.status`, and `clips.video_id`. Pydantic `VideoRead`/`ClipRead` schemas mirror the models for upcoming API work.
- **Important:** The models default `Video.status` to `ingested` and `Clip.status` to `rendering`; downstream services should rely on these constants. Cascade delete removes clips when a video is removed, so be careful when implementing archival flows.

### 1.2 — `POST /videos/ingest` ✅
- **Why:** Entry point for the entire pipeline; must validate inputs and return quickly.
- **Implementation overview:** Added `/api/v1/videos/ingest` (protected by the beta key) that accepts a YouTube URL, validates the domain, upserts a `Video` row with `status=ingested`, and hands off to `services.ingest.enqueue_video` (placeholder until Phase 1.3). Responses include the Pydantic `VideoRead` payload plus `created/queued` flags.
- **Important:** Duplicate submissions re-queue existing videos without creating new rows. Validation rejects non-YouTube URLs with 422. The enqueue function currently logs; replace with real queue dispatch during Phase 1.3.

### 1.3 — Background execution infrastructure (Dramatiq + Redis) ✅
- **Why:** Downloading and rendering videos is CPU-bound; requests must not block. We need durable background processing with retries and observability.
- **Implementation overview:** Introduced Dramatiq with Redis broker (`REDIS_URL`, `DRAMATIQ_BROKER`, `WORKER_CONCURRENCY`), added `scripts/run_worker.py`, and wired Docker Compose/Fly to run a dedicated worker alongside Redis. `app/services/tasks.py` defines actors (`process_video`, `download_video`, `detect_highlights`, `finalize_video`) that currently stub downstream work but drive the state machine (`ingested` → `processing` → `ready`). `services/ingest.enqueue_video` now enqueues the orchestrator actor. Tests cover status transitions and enqueue behavior.
- **Important:** Placeholder actors log and update database state; modules 1.5–1.8 will replace the stubs with real implementations. Operators should launch Redis + worker locally via `docker compose up redis worker` or `make worker` (stub broker). Fly deployment now includes a worker process group; ensure Redis credentials are configured in secrets.

### 1.4.0 — API layering + authentication foundations ✅
- **Why:** Keeping FastAPI routers thin improves readability, reuse, and testability, while preparing for stronger authentication than a shared beta key.
- **Implementation overview:** Added `app/deps/db.get_session` plus repository constructors, migrated database access into `app/repositories/*`, introduced `app/services/*` for orchestration, and updated routers to validate requests and serialize ORM entities to schemas. Bootstrapped a `tests/system/` suite to exercise HTTP flows end-to-end. Documentation now captures the layering and testing strategy, and the roadmap stakes out the upcoming JWT migration.
- **Important:** Follow this pattern for new endpoints; target services/repositories in unit tests and rely on system/integration suites for end-to-end behaviour. The beta key remains temporary—Phase 1.4 lays the groundwork for the JWT rollout in subsequent milestones.

### 1.4.1 — JWT configuration & auth services ✅
- **Why:** Token settings and helpers must exist before the API can issue signed credentials.
- **Implementation overview:** Added JWT config to settings/environment, created encode/decode helpers in `app/core/jwt.py`, and built `app/services/auth.py` to authenticate users and mint access/refresh tokens.
- **Important:** Secrets live in environment variables; adjust expirations as needed per environment.

### 1.4.2 — Secure routes with JWT bearer tokens ✅
- **Why:** Replace the beta key with per-user authentication and authorization.
- **Implementation overview:** Added `/api/v1/auth/login` and `/api/v1/auth/refresh`, introduced `require_jwt_user`, updated v1 routers to depend on bearer auth, and configured Swagger to persist the token.
- **Important:** Health/ready/version endpoints remain public; admin basic-auth guard still layers on top of JWT where required.

### 1.4.3 — Testing & documentation updates ✅
- **Why:** All suites and docs must reflect the new auth flow to avoid regressions and onboarding friction.
- **Implementation overview:** Updated fixtures to create/login users automatically (unit, system, integration), reworked tests to send bearer tokens, and refreshed docs/README/testing guides with the JWT flow.
- **Important:** Consumers should use the login endpoint rather than the legacy beta key, which is now documented as transitional only.

### 1.5 — Authenticated operator dashboard
- **Why:** Operators need a secure web surface to review pipeline output, trigger ingestion, and manage publishing without reaching for API tooling.
- **Implementation overview:** Serve `/admin` pages via Jinja templates backed by JWT cookies. Provide login/logout views, list videos with clip rollups and status badges, embed ingestion and publish controls, and wire async fetches to existing API endpoints.
- **Important:** Cookies must be HTTP-only and respect environment-driven security flags. Reuse the FastAPI authentication stack so API tokens and dashboard sessions stay aligned.

### 1.6 — `services/youtube_downloader.py`
- **Why:** Provides deterministic retrieval of source media and transcripts.
- **Implementation overview:** Use pytube/yt-dlp for video download and `youtube-transcript-api` for captions. Normalize outputs to configured storage directory, persist file sizes, handle missing captions (fallback to Whisper if needed).
- **Important:** Respect rate limits; store transcripts in UTF-8; guard against large file sizes by choosing appropriate stream quality (720p baseline).

### 1.7 — `services/highlight_detector.py`
- **Why:** Converts transcripts into candidate shorts via LLM heuristics.
- **Implementation overview:** Prompt engineering with system instructions to produce JSON segments. Parse responses with pydantic models, validate durations, and create `Clip` rows with `status=rendering`.
- **Important:** Handle LLM failures gracefully (retry, fallback heuristics). Store raw LLM output for debugging in the database or logs.

### 1.8 — `services/clipper.py`
- **Why:** Efficiently slices source video into vertical shorts.
- **Implementation overview:** Wrap ffmpeg CLI or python-ffmpeg bindings to extract subclips, rescale/crop to 9:16, and output high-bitrate MP4. Manage temp directories and ensure deterministic filenames.
- **Important:** Validate clip durations (< 60s). Handle edge cases where requested timestamps exceed video length by clamping values.

### 1.9 — `services/subtitle_styler.py`
- **Why:** On-brand subtitles increase engagement; aligning text with audio is part of MVP.
- **Implementation overview:** Derive transcript segment per clip, generate SRT or ASS overlays, and burn into the video via ffmpeg `subtitles` or `drawtext`. Apply consistent styling (font path, color, outline).
- **Important:** Support fallback when transcripts missing—allow manual caption text or degrade gracefully. Cache fonts in repo or document installation.

### 1.10 — `GET /status/{video_id}` & `GET /videos/{video_id}/clips`
- **Why:** Enables polling and UI state management.
- **Implementation overview:** Create new router entries returning Pydantic schemas (VideoRead, ClipRead). Include statuses, timestamps, local/preview URLs. Consider caching to reduce DB load on frequent polling.
- **Important:** Secure endpoints via API key auth; handle 404/410 when video deleted.

### 1.11 — Admin HTML routes
- **Why:** Provide human validation loop before publishing.
- **Implementation overview:** Use Jinja2 templates with Bootstrap/Tailwind-lite styling. `/admin/videos` lists videos with status badges; `/admin/videos/{video_id}` renders clip cards, preview players (HTML5 video), caption text, and publish buttons hitting API endpoints.
- **Important:** Reuse the authentication scaffold (0.12). Keep templates responsive and degrade gracefully if media unavailable.

### 1.12 — Admin ingestion workflow
- **Why:** Operators need a single dashboard to start processing without touching API clients.
- **Implementation overview:** Add `/admin/videos/new` view or inline form on `/admin/videos` that accepts a YouTube URL, posts to `POST /videos/ingest`, and displays success/error messaging. Trigger status polling so the page reflects progression without manual refresh.
- **Important:** Validate inputs client-side and server-side. Surface existing video conflicts with actionable guidance (link to current record, option to reprocess).

## Phase 2 — Operational Polish

### 2.1 — `PublishJob` model/migration
- **Why:** Record publishing attempts for auditing and retries.
- **Implementation overview:** Define model with enums for platform/status, JSON field for response payload, and relationships to `Clip`. Migration must add indexes for `clip_id` + `status`.
- **Important:** Extend Pydantic schemas and admin views to surface job history.

### 2.2 — `POST /clips/{clip_id}/publish`
- **Why:** Initiates stubbed publishing now; future real integrations reuse the contract.
- **Implementation overview:** Accept list of platforms, create pending `PublishJob` rows, simulate success (set timestamp/response), update `Clip.status` to partial/all depending on coverage. Return structured response listing outcomes.
- **Important:** Validate duplicates (avoid double publishing), respect idempotency, and plan for async execution later.

### 2.3 — Admin publish UX
- **Why:** Operators should trigger publishing without Postman.
- **Implementation overview:** Add platform checkboxes/dropdowns in templates, POST via fetch or HTML forms, update UI with success toasts or inline status badges. Surface job history per clip.
- **Important:** Handle errors gracefully; keep CSRF protection in mind if moving beyond single-operator setup.

### 2.4 — Subtitle styling presets
- **Why:** Visual consistency plus maintainability.
- **Implementation overview:** Centralize style config (JSON/YAML or Python constants). Add tests to confirm generated commands include expected fonts/outline settings.
- **Important:** Store font files in repo or document licensing. Provide fallback for missing fonts on different environments.

### 2.5 — Pipeline observability
- **Why:** Operators need visibility into processing bottlenecks and errors.
- **Implementation overview:** Emit structured logs (stage, duration, success/failure) and Prometheus metrics (processing_time_seconds, clip_generation_failures_total). Optionally expose admin dashboard summarizing pipeline health.
- **Important:** Ensure logs include `video_id`/`clip_id` for traceability. Consider OpenTelemetry integration if future needs arise.

### 2.6 — Storage hygiene
- **Why:** Media files are large; unmanaged disk growth is a risk.
- **Implementation overview:** Centralize base directories in settings, add cleanup cron for temp dirs, document retention policy (delete intermediate files once clips ready). Evaluate checksum validations to avoid re-downloads.
- **Important:** Plan for future migration to S3/GCS (Phase 3.5) by abstracting storage interactions early (e.g., `StorageService` interface).

### 2.7 — YouTube OAuth connector ⬜
- **Why:** Cookie-based authentication is fragile and requires manual refreshing every 1-2 weeks. OAuth provides a sustainable, officially-supported solution that auto-refreshes tokens and scales across multiple operators.
- **Implementation overview:** Add `youtube_credentials` table with user_id (FK to users), access_token, refresh_token, token_type, scope, and expires_at. Build OAuth 2.0 flow with Google consent screen (`/admin/youtube/connect` initiates flow, `/admin/youtube/callback` stores tokens). Implement token refresh strategy (check expiry before downloads, refresh if needed). Update `youtube_downloader.py` to use OAuth tokens instead of cookies when available. Add admin UI controls ("Connect YouTube" / "Disconnect" buttons). See [docs/setup/youtube_oauth_connector.md](../setup/youtube_oauth_connector.md) for detailed implementation plan (database schema, security considerations, migration path).
- **Important:** Requires Google Cloud project with YouTube Data API enabled and OAuth credentials configured. Store client_id/client_secret in environment variables (`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`). Tokens are sensitive—encrypt at rest or rely on database-level encryption. Provide graceful fallback to cookie-based auth when OAuth is not configured. Document cookie-to-OAuth migration path for existing deployments.

## Phase 3 — Growth & Automation

### 3.1 — Real publishing integrations
- **Why:** Delivers end-to-end automation and true value to creators/teams.
- **Implementation overview:** Implement OAuth flows and upload APIs for YouTube Shorts, TikTok, Instagram. Store tokens securely, handle refresh logic, and map responses into `PublishJob.response_data`.
- **Important:** Each platform has different media specs; validate clip encoding ahead of upload. Maintain per-platform retries and failure states.

### 3.2 — Platform-specific CTA generation
- **Why:** Tailored captions increase engagement across channels.
- **Implementation overview:** Extend highlight detector or new service to generate per-platform copy via LLM. Store on `PublishJob` or derivative table. Provide UI to edit before publishing.
- **Important:** Respect token budgets; cache results to avoid rerunning prompts unnecessarily.

### 3.3 — Branded overlays & templates
- **Why:** Agencies/brands need consistent look-and-feel.
- **Implementation overview:** Add templating system (e.g., ffmpeg filters or After Effects-like layers) with per-account configuration. Version templates to allow AB testing.
- **Important:** Provide preview pipeline in admin UI before rendering final assets.

### 3.4 — Scheduled publishing
- **Why:** Enables optimal timing without manual intervention.
- **Implementation overview:** Add scheduling table or reuse queue with delay support. Provide UI to pick publish time, background worker to execute at schedule, notifications pre/post publish.
- **Important:** Account for timezone handling, daylight saving, and operator overrides/cancellations.

### 3.5 — Object storage integration
- **Why:** Local disk does not scale. External storage unlocks CDN-backed previews.
- **Implementation overview:** Introduce storage abstraction; push files to S3/GCS, store signed URLs in `Clip.local_path` (rename field or add `preview_url`). Update admin and API to consume signed links.
- **Important:** Implement lifecycle policies (automatic expiration) and handle private vs. public assets carefully.

### 3.6 — Automated retries & alerting
- **Why:** Background failures must not go unnoticed.
- **Implementation overview:** Add retry queues with exponential backoff, track attempt counts, and integrate with alerting (Slack via webhook, email, PagerDuty). Store failure reasons on `Video`/`Clip` for UI display.
- **Important:** Ensure alerts de-duplicate; include runbook links in messages. Provide manual retry buttons in admin UI.
