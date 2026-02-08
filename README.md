# TV7 FastAPI Backend

Control-plane service for authentication, user management, clip metadata, and publish scheduling. Media processing now lives in the desktop app + engine; this backend no longer downloads, transcribes, or renders videos.

## Shared Docs & Contracts
- Repo docs are centralized in core under `docs/core/repos/tv7-fastapi-backend/`.
- Canonical API contract is maintained at `docs/core/contracts/openapi/tv7-fastapi-backend/openapi.json`.

## Quickstart (Docker)
- Copy `.env.example` to `.env` and adjust database credentials if needed.
- Start API and Postgres: `make up`
- Check health: `curl http://localhost:8000/health`

## Requirements
- Docker + Compose, or Python 3.12 with access to Postgres.
- Sibling `../tv7-core` checkout is expected for shared docs/contracts symlinks (including `openapi.json`).
- No Redis/ffmpeg/node dependencies required after the cleanup.

## Admin UI
- Visit `/admin/login` and sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`.
- Dashboard: counts for users, videos, clips, and publish jobs.
- Schedule: view recent publish jobs and edit status/asset URL/response notes.
- Users: list users and view per-user metrics (videos, clips, publish jobs).

## Development Workflow
- Local hot-reload: `make dev` (starts Postgres via Compose, runs uvicorn locally)
- Compose stack: `make up` / `make down`
- Lint/format/type/test: `make fmt`, `make lint`, `make type`, `make test`, `make testcov`
- Migrations: `make revision m="message"` then `make upgrade`

## API Surface (post-cleanup)
- Auth: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`
- Users (JWT): `GET/POST /api/v1/users`
- Config (JWT): `GET /api/v1/config`
- Videos (JWT):
  - `GET /api/v1/videos` to list metadata + clips
  - `POST /api/v1/videos/local` to register a locally produced video and optional clips
  - `POST /api/v1/videos/{video_id}/clips` to append clip metadata
- Assets (JWT): `POST /api/v1/uploads/assets` to store rendered clip assets under `MEDIA_STORAGE_DIR`
- Publish (JWT): `POST /api/v1/clips/{clip_id}/publish` to queue publish jobs for supported platforms

## Media Cleanup
If media directories drift from database state (e.g., after manual deletes), run:
```
python scripts/cleanup_media.py           # list orphans
python scripts/cleanup_media.py --delete # remove them
```

## Testing
- Fast unit suite: `make test`
- Coverage gate: `make testcov`
- Integration containers (Postgres) are not required; tests run against in-memory SQLite.
