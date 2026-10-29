# TV7 Backend

Control-plane service for authentication, user management, clip metadata, and publish scheduling. Media processing now lives in the desktop app + engine; this backend no longer downloads, transcribes, or renders videos.

## Shared Docs & Contracts
- Repo docs are centralized in core under `docs/core/repos/tv7-backend/`.
- Canonical API contract is maintained at `docs/core/contracts/openapi/tv7-backend/openapi.json`.

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
- Local hot-reload in Docker: `make dev` (runs API + Postgres in Compose)
- Local hot-reload on host Uvicorn: `make dev-local` (starts Postgres in Compose, runs API locally with localhost DB URL)
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
- Assets (JWT): `POST /api/v1/uploads/assets` stores a bounded, approved rendered clip in private storage and returns an opaque owner-scoped asset URL. `GET /api/v1/uploads/assets/{id}` serves that asset to its owner, including Range requests for S3 objects.
- Schedule drafts (JWT): `POST /api/v1/clips/{clip_id}/schedule-drafts` records a future UTC target and private asset. `POST /api/v1/clips/{clip_id}/publish` returns 503 until real connected-platform adapters exist; the worker never simulates a successful post.

## Private approved asset storage

Development defaults to `ASSET_STORAGE_BACKEND=local` and `SCHEDULED_ASSET_STORAGE_DIR=./private_media/assets`. In production, API and worker startup require `ASSET_STORAGE_BACKEND=s3`. They must share the same private S3-compatible bucket and credentials; no public bucket access or public asset URLs are needed. The API stores objects under `ASSET_S3_PREFIX/<owner-id>/<random-id>.<ext>` and exposes only its authenticated opaque `/api/v1/uploads/assets/{id}` route. The worker downloads an approved asset to a temporary file, checks size and SHA-256, and deletes that temporary file after the attempt.

Set `ASSET_S3_BUCKET`, `ASSET_S3_REGION`, `ASSET_S3_ACCESS_KEY_ID`, and `ASSET_S3_SECRET_ACCESS_KEY` as deployment secrets for both API and worker. Set `ASSET_S3_ENDPOINT_URL` for non-AWS S3-compatible services (HTTPS required in production); `ASSET_S3_SESSION_TOKEN` is optional. The credentials need private object put, get/head, and delete permissions for the configured prefix. Keep the bucket private, and configure lifecycle cleanup for abandoned objects. Existing local assets are not automatically migrated to S3 and cannot be scheduled in S3 mode until reuploaded.

Fly sets `APP_ENV=production` and `ASSET_STORAGE_BACKEND=s3` in `fly.toml`. Supply the S3 secrets before deploying; startup fails if required configuration is absent. Instagram and TikTok publishing require separate OAuth and platform adapters.

## YouTube connection and publishing

The authenticated creator calls `POST /api/v1/youtube/connect` and opens the returned Google authorization URL. Google returns to `/api/v1/youtube/callback`; a one-use state and PKCE verifier bind the grant to the creator account. `GET /api/v1/youtube/connection` returns the verified channel ID, which becomes `target_account_ref: "youtube:<channel-id>"` in a schedule draft. `DELETE /api/v1/youtube/connection` removes the stored credential. The scopes are `youtube.upload` and `youtube.readonly` (the latter verifies channel ownership and the uploaded video's final state). Access and refresh tokens are encrypted in the database using `YOUTUBE_TOKEN_ENCRYPTION_KEYS`; existing plaintext legacy rows are unusable and must reconnect.

Set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`, and `YOUTUBE_TOKEN_ENCRYPTION_KEYS` on the API and worker. The redirect URI must exactly match the Google OAuth web client and be HTTPS in production. Generate each Fernet key securely and set the same comma-separated key list on both processes; the first key encrypts new values and older keys may remain for rotation. Keep `YOUTUBE_PUBLISH_ENABLED=false` and `YOUTUBE_API_AUDIT_APPROVED=false` until the Google OAuth consent configuration, YouTube Data API project audit, scopes, quota, private/public upload behavior, and a real creator account have been validated. The API reports YouTube publishing and scheduling unavailable until both flags and credentials are present. [Google's videos.insert documentation](https://developers.google.com/youtube/v3/docs/videos/insert) says uploads from unverified API projects created after July 28, 2020 are restricted to private viewing. A successful upload alone therefore does not prove a public Short exists. YouTube itself decides whether an uploaded video qualifies as a Short.

When enabled, the separate worker uses YouTube's [resumable upload protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol), persists its encrypted session URL before sending media bytes, and verifies the returned video ID belongs to the connected channel and is public before recording a completed receipt. Unknown outcomes move to `reconcile`; the worker probes the persisted session or video ID without initiating another upload. Incomplete or unverifiable outcomes remain in `reconcile` for review. Google documents default upload quota and audit processes in its [quota and compliance guide](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits).

## Testing
- Fast unit suite: `make test`
- Coverage gate: `make testcov`
- Integration containers (Postgres) are not required; tests run against in-memory SQLite.

## License

TV7 source in this repository is available under the [MIT License](LICENSE). External dependencies and tools retain their respective licenses. See the [TV7 project overview](https://github.com/TV7-Clip-Studio/tv7-core/blob/main/PROJECT.md) for the repository map and current scope.
