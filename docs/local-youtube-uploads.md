# Local-to-YouTube pre-upload

Studio can send an existing local rendered clip directly from Engine to YouTube. Backend handles provider authorization and upload metadata only; it receives no video bytes and creates no UploadedAsset or PublishJob. The existing Backend asset scheduler is preserved for its existing workflow.

1. Engine reports the local render's byte length, SHA-256, and MIME type.
2. Authenticated Studio posts metadata to `POST /api/v1/youtube/local-uploads`: `creator_profile_id`, `target_account_ref` (`youtube:<verified channel ID>`), `local_clip_id`, stable `idempotency_key`, `title`, `description`, `size_bytes`, `checksum_sha256`, `content_type`, and optional timezone-aware `scheduled_at`.
3. Backend checks the connected credential's owner/profile and reconfirms the authenticated YouTube channel. It durably records the intent before initiating one resumable session. Every upload starts private. Optional future `publishAt` is only allowed when `YOUTUBE_API_AUDIT_APPROVED` is true; private testing requires configured OAuth but no public audit gate.
4. The response includes metadata and ephemeral `upload_url` / `upload_headers` (`Authorization` and `Content-Type`). Engine verifies the local file metadata and sends bytes to the fixed Google upload host. Google requires an access token on the media PUT, so the short-lived access token crosses to the trusted local Engine for this transfer. Refresh tokens stay in Backend. Never log or persist these capabilities in Studio/Engine, browser storage, workspace JSON, or telemetry. Responses use `Cache-Control: no-store`.
5. `POST /api/v1/youtube/local-uploads/{upload_id}/verify` with `{ "remote_video_id": "..." }` (optional) asks Backend to probe its saved resumable session, obtain the authoritative video ID, and verify the video's channel, private visibility, and requested provider publication time. Client receipt IDs alone never establish completion.

While YouTube transcodes the completed upload, verification returns `processing` and retains its remote video ID; call the same verify route later, without retransferring bytes. Successful processing verification returns `private_uploaded` or `scheduled`; neither status claims that a public post has appeared. `GET /api/v1/youtube/local-uploads?creator_profile_id=...` and `GET /.../{upload_id}` return metadata and errors only, never transfer tokens or session URLs. `POST /.../{upload_id}/transfer` returns the existing session and a refreshed access header for continuation; it creates no new session.

Reuse the same idempotency key for the same clip, destination, and metadata. Different metadata under that key returns 409. Timeouts persist `unknown` and cannot blindly initiate a new session. Incomplete uploads remain `uploading` and resume from YouTube's reported byte range in that same session. Provider-session expiry or a missing receipt needs operator reconciliation, not automatic reposting. Disconnecting or moving a credential to another creator profile blocks subsequent transfer/verification authorization.

This is YouTube's own future publication scheduling: once a verified pre-upload carries `publishAt`, the laptop does not need to remain online for that provider schedule. Provider account identity must be checked by the user before the first real upload, especially when source and destination channels differ.

Primary protocol reference: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
API scheduling reference: https://developers.google.com/youtube/v3/docs/videos#status.publishAt

## Update a release date

`PUT /api/v1/youtube/local-uploads/{upload_id}/schedule` accepts `{ "scheduled_at": "<future timezone-aware ISO timestamp>" }`. It validates the owner and profile, reads the existing private YouTube video, updates its status with `publishAt`, and saves the date only after YouTube confirms it. It never uploads the media again. Public scheduling requires the API audit approval flag; private uploads remain available independently.

### Identical-render retries

A different request key for identical media in the same TV7 account, creator profile and YouTube destination reuses the original receipt or resumable session. Checksum, byte size and MIME type must match. The returned title, description and release date remain the saved provider intent; changed local copy does not silently rewrite provider metadata. Date changes use the existing-video schedule endpoint. A unique database index prevents concurrent duplicate records. Migration fails on preexisting duplicate groups for explicit review, without deleting receipts.

## Profile schedule cancellation

`POST /api/v1/youtube/local-uploads/clear-schedule` accepts `creator_profile_id`. It is JWT owner scoped. It removes future publishAt values from verified private YouTube videos (scheduled or processing), preserving writable status preferences and confirming provider cancellation. It cancels unattempted, unleased pending Backend jobs atomically. Active/uncertain transfers or publishing jobs are returned in `errors`; callers must keep recovery metadata and never claim a full clear in that case. Published videos and historical uploads remain intact.

Direct upload scheduling readiness uses OAuth, encryption and API audit configuration; the separate cloud worker enable flag controls Backend publishing adapters, not direct provider scheduling.
