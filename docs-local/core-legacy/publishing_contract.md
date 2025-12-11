# Publishing Contract (Flutter client ↔ FastAPI backend)

## Goal
Define clear ownership for publishing clips to social platforms (YouTube Shorts, TikTok, Instagram Reels) with cloud-owned execution and client as trigger/telemetry.

## Ownership
- Backend (FastAPI + worker): owns platform OAuth/credentials, signed URL issuance, asset handling, publish job orchestration, retries/backoff, logging/auditing.
- Client (Flutter): renders locally, uploads assets when required, sends metadata, triggers publish jobs, displays status/logs, retries/cancels via API.
- Platforms: receive uploads only from backend workers; client never holds platform tokens/SDKs.

## Required backend capabilities
- Auth/JWT and user scoping (already present).
- Feature/config endpoint: flags like `publishing_enabled`, `asset_upload_required`, allowed platforms per environment.
- Asset intake:
  - Option A: direct upload endpoint (multi-part) to backend storage.
  - Option B: signed URL issuance for object storage (client uploads directly to storage, then posts the resulting `asset_url` + checksum).
- Publish job API:
  - `POST /clips/{id}/publish` with requested platforms.
  - Status enums: `pending`, `queued`, `publishing`, `partial`, `complete`, `failed`.
  - Job metadata: `asset_url`, `asset_checksum/size`, response payloads, error logs, timestamps.
  - Worker/cron executes publish; updates status and platform-specific results.
- Webhook/notification (optional): push status to clients; otherwise clients poll.

## Client responsibilities
- Render clip locally; compute checksum/size; maintain local path.
- If `asset_upload_required=true`, upload asset (direct or signed URL path) and post `asset_url` + metadata to the backend.
- Send clip metadata: timings, captions, transcript refs, status, `asset_url` (if uploaded), checksum/size.
- Trigger publish via API; show status and logs returned by backend; allow retry/cancel only through backend endpoints.
- Never store or transmit platform OAuth tokens; use backend-issued short-lived tokens only if proxying OpenAI or similar.

## Flows
1) Asset upload (when required)
   - Client requests signed URL or uploads to backend endpoint.
   - Client sends `asset_url`, checksum, size, and clip metadata to backend.
2) Publish trigger
   - `POST /clips/{id}/publish` with platform list.
   - Backend enqueues PublishJobs; returns initial status.
3) Status updates
   - Client polls `GET /clips/{id}/publish` (or job list) or subscribes to notifications.
   - Backend returns per-platform status, logs, and final URLs/IDs.
4) Failure/retry
   - Backend handles retries/backoff; exposes last error and next retry time.
   - Client may request a manual retry via API; backend enforces limits.

## Metadata-only mode
- If no `asset_url` is provided, mark clip as `ready_local_only` (or similar) and disable publish endpoints; client reflects this state and skips publish UI.

## Deliverables to unblock integration
- Publish/OpenAPI spec including publish endpoints, status enums, asset fields, config/feature flags.
- Signed URL or upload endpoint contract documented (fields, auth, size limits).
- Config endpoint added to backend; Dart client generated from spec.
- Backend workers enabled to execute publish jobs; client uses publish APIs to trigger/poll.
