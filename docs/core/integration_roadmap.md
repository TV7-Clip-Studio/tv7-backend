# Flutter ↔ FastAPI Integration Roadmap (Multipart Asset Upload)

This roadmap tracks the changes needed in the FastAPI backend and the Flutter client to align on the new hybrid model: Flutter handles heavy media work, uploads rendered assets via multipart, and the backend owns publishing.

## Backend (forgotten-app) changes
1) **Multipart asset upload**
   - Add `POST /uploads/assets` (multipart) with size/type validation.
   - Store under `MEDIA_STORAGE_DIR` (e.g., `/data/uploads/assets/{uuid}.mp4`).
   - Response: `asset_url`, `asset_checksum`, `asset_size_bytes`, `content_type`.
2) **Clip metadata update**
   - Add `PATCH /clips/{id}` (or similar) to accept `asset_url`, `asset_checksum`, `asset_size_bytes`, render metadata (width/height/frame_rate/file_size), captions, `ready_local_only`.
3) **Publish APIs (existing, finalize)**
   - `POST /clips/{id}/publish` + `GET /clips/{id}/publish` (jobs/status/logs) using stored asset fields; keep status enums and retries.
4) **Config endpoint**
   - `GET /config` includes feature flags/limits: `publishing_enabled`, `asset_upload_required`, `allowed_platforms`, `max_asset_size_bytes`.
5) **OpenAPI**
   - Regenerate `/openapi.json` after new endpoints; commit to `flutter-tv-7/forgotten_client/openapi/forgotten-app.json|yaml`; keep a make target for codegen.
6) **Admin/UI adjustments**
   - Keep ingest/publish endpoints, but hide or de-emphasize server-side ingest/render controls in the admin UI when Flutter is the primary client (e.g., feature flag to hide ingest forms/publish buttons).
7) **Workers**
   - Ensure publish worker consumes `PublishJob` rows, reading assets from local storage (`asset_url` or `local_path`); retries/backoff with response/error payload logging.

## Flutter client changes (flutter-tv-7)
1) **Use config**
   - Call `GET /config` to enable/disable publish UI and enforce size/format limits.
2) **Ingest/render locally**
   - Run yt-dlp/file import, ffmpeg normalize/render, optional local transcripts/highlights.
3) **Asset upload (multipart)**
   - Call `POST /uploads/assets` with rendered clip; read `asset_url/checksum/size` from response.
4) **Clip metadata push**
   - Call `PATCH /clips/{id}` (new endpoint) to store `asset_url/checksum/size`, render metadata, captions, `ready_local_only`.
5) **Publish trigger/status**
   - Call `POST /clips/{id}/publish` and `GET /clips/{id}/publish` to trigger/poll; display per-platform statuses/logs.
6) **OpenAPI client**
   - Regenerate Dart client from updated spec (`make gen-api`); wire auth + new endpoints.
7) **UI**
   - Hide backend-driven ingest controls; surface local render + upload + publish flow.

## Sequencing
1) Backend: add upload/clip-patch endpoints + config fields; regenerate OpenAPI; update admin UI to hide ingest/publish when flagged.
2) Flutter: regenerate client; implement multipart upload + clip patch + publish flow using new endpoints.
3) Backend: enable publish worker to consume jobs; finalize logging/retries.
