# YouTube Shorts Factory Roadmap

> Living plan for evolving the FastAPI “forgotten-app” into a single-service YouTube → Shorts production line. Update this file whenever scope or priorities shift.

## Phase 0 — Platform Foundation (✅ Baseline, ⬜ To shore up)
- 0.1 ✅ Confirm FastAPI core application (`src/app/main.py`) with router aggregation, dependency wiring, and lifespan hooks is production-ready.
- 0.2 ✅ Maintain security middleware stack (Trusted Hosts, CORS, custom security headers) and API key gating via `require_beta_key` (`src/app/deps/security.py`).
- 0.3 ✅ Provide baseline persistence layer: SQLAlchemy `Base`, async session scope, `User` model, and Alembic scaffolding (`src/app/db/*`, `alembic/`).
- 0.4 ✅ Ship health/ready/version endpoints plus Prometheus instrumentation in `main.py` for liveness/observability.
- 0.5 ✅ Keep architecture and ops guides current (`docs/top_architecture.md`, `docs/agent_best_practices.md`, `docs/neon_postgres.md`) to explain present-tense system behavior.
- 0.6 ✅ Configure Fly.io deployment via `fly.toml`, with Makefile targets (`make smoke-fly`) supporting remote smoke checks.
- 0.7 ✅ Provide Docker + Compose setup (`docker/`, `docker-compose.yml`, `Makefile dev/up/down`) for local parity with production.
- 0.8 ✅ Enforce automated formatting/lint/type/security checks through `.pre-commit-config.yaml` (Black, Ruff, mypy, Bandit, pytest coverage hook).
- 0.9 ✅ Supply a `Makefile` that codifies dev ergonomics (`make fmt/lint/type/sec/testcov`) and is used by CI.
- 0.10 ✅ Maintain unit and integration test suites under `tests/` with coverage thresholds (`--cov-fail-under=85`).
- 0.11 ✅ Run GitHub Actions CI pipeline (`.github/workflows/ci.yml`) executing fmt, lint, type checks, security scan, and tests on every push/PR.
- 0.12 ✅ Introduce admin-route authentication scaffold (basic auth or shared secret) ready to wrap upcoming `/admin/*` endpoints.
- 0.13 ✅ Establish operator admin access: seed an initial admin user or configure an allowlist/env-backed credential for `/admin/*`, and document rotation steps.

## Phase 1 — Shorts MVP (🚧 Active)
- 1.1 ✅ Define `Video` and `Clip` ORM models with enums/status columns, transcript/file path fields, and generate Alembic migrations to create the backing tables.
- 1.2 ✅ Implement `POST /videos/ingest` inside `api/v1` that validates the YouTube URL, creates a `Video` record (`status=ingested`), and enqueues the processing workflow.
- 1.3 Build background execution infrastructure (Celery/RQ/Dramatiq or equivalent) plus a task orchestrator that runs the ingestion → highlight → clipping stages off-thread.
- 1.4 Write `services/youtube_downloader.py` to download the highest-quality stream, fetch captions/transcript (youtube-transcript-api + fallback), persist artifacts, and update the `Video`.
- 1.5 Implement `services/highlight_detector.py` that calls the LLM, parses 3–5 segments with `{start_sec, end_sec, hook}`, handles parsing errors, and creates `Clip` rows (`status=rendering`).
- 1.6 Build `services/clipper.py` that slices video segments with ffmpeg, converts to 9:16 framing, manages temp files, and hands off to the subtitle renderer.
- 1.7 Create `services/subtitle_styler.py` to extract transcript snippets, render social-style captions (font, outline, positioning), burn them into the clip, and update `Clip.local_path` + `status=ready`.
- 1.8 Expose `GET /status/{video_id}` (overall state + per-clip summaries) and `GET /videos/{video_id}/clips` (detailed clip metadata, previews, captions) for polling and UI consumption.
- 1.9 Deliver internal admin routes `/admin/videos` and `/admin/videos/{video_id}` with Jinja templates: list view, per-video clip gallery, preview players, and buttons wired to the publish endpoint stub.
- 1.10 Add admin-side ingestion workflow: `/admin/videos/new` (or inline modal) that lets operators paste a YouTube URL, submits to `POST /videos/ingest`, and shows immediate feedback/status polling.

## Phase 2 — Operational Polish (Queued)
- 2.1 Add `PublishJob` ORM model/migration covering platform enum, status, response payload, timestamps.
- 2.2 Implement `POST /clips/{clip_id}/publish` to create `PublishJob` rows for requested platforms, mark them `success` immediately (stub), and update the clip to `published_partial` or `published_all`.
- 2.3 Update the admin video detail page to call the publish endpoint, show platform selection, and surface job status inline for quick operator feedback.
- 2.4 Enhance subtitle styling presets (font files, outlines, drop shadows) and ensure the renderer is idempotent with deterministic outputs on re-runs.
- 2.5 Instrument each pipeline stage with structured logs, timing metrics, and error traces; expose aggregated stats via Prometheus and admin UI badges.
- 2.6 Harden storage handling: centralize media directory configuration, add cleanup routines for stale temp files, and document local vs. remote storage strategies.

## Phase 3 — Growth & Automation (Backlog)
- 3.1 Replace stubbed publishing with real platform integrations (YouTube Shorts, TikTok, Instagram Reels) including OAuth flows, upload APIs, retry handling, and response persistence.
- 3.2 Generate platform-specific CTA/caption variants via LLM and store them per `PublishJob` for reuse in multi-platform pushes.
- 3.3 Introduce branded overlays and templates (watermarks, animated captions, end cards) selectable per workspace or video.
- 3.4 Support scheduled publishing windows with delayed job execution, status tracking, and operator notifications prior to release.
- 3.5 Externalize finalized clips and source videos to object storage (S3/GCS) with signed URLs for previews and downloads; abstract local paths in the models.
- 3.6 Implement automated retries/backoff with alerting (Slack/email/webhook) for failures in download, LLM highlights, rendering, or publishing.
