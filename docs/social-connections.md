# Social account connections

Studio connects destinations under its active creator profile. Backend holds encrypted provider credentials. Connection is distinct from publishing readiness: Instagram and TikTok OAuth are implemented, but their publishing executors are not yet implemented. They therefore return `publishing_ready: false` and cannot enter the current YouTube-only publish pipeline.

Configure the provider app in Backend `.env` before connecting:

- YouTube: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`, and `YOUTUBE_TOKEN_ENCRYPTION_KEYS`. New deployments should use `/api/v1/social/youtube/callback`. Existing `/api/v1/youtube/callback` and `/admin/youtube/callback` registered redirects use the same callback handler.
- Instagram: `INSTAGRAM_CLIENT_ID`, `INSTAGRAM_CLIENT_SECRET`, `INSTAGRAM_REDIRECT_URI`. Use Instagram API with Instagram Login for a professional account, with `instagram_business_basic` and `instagram_business_content_publish`. Callback: `/api/v1/social/instagram/callback`.
- TikTok: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`. Enable Login Kit with `user.info.basic` and Content Posting API with `video.publish`. Callback: `/api/v1/social/tiktok/callback`.
- Instagram/TikTok token storage uses `SOCIAL_TOKEN_ENCRYPTION_KEYS`, falling back to `YOUTUBE_TOKEN_ENCRYPTION_KEYS`. Supply a private stable Fernet key; rotation accepts comma-separated keys, newest first. Losing the key requires account reconnection. Back up the persistent database together with its encryption key securely.

Register the exact redirect URL in each provider console. Providers may require HTTPS or app approval even in development. Production configuration requires HTTPS. Never commit app secrets or token encryption keys. Use a persistent database before connecting real accounts.

`GET /api/v1/social/providers` returns configuration readiness and a non-secret setup message. Authenticated `GET /api/v1/social/connections?creator_profile_id=...` returns verified destination identities and readiness; it never returns tokens. `POST /api/v1/social/{platform}/connect` requires `{ "creator_profile_id": "..." }` and returns `authorization_url`. Callbacks consume hashed state once within ten minutes; its stored user and profile select the credential owner. Provider identity is verified before storing encrypted tokens. Existing Instagram/TikTok accounts cannot be silently moved to another account or profile by reconnecting.

`DELETE /api/v1/social/connections/{id}` removes credentials from TV7 for their owner. This is a local disconnect; provider permissions can additionally be revoked from the provider's account settings. It does not claim remote token revocation. Browser callback pages tell the user to return to Studio and check the connection.

Official references:
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
- https://developers.tiktok.com/docs/en/oauth-user-access-token-management
- https://developers.tiktok.com/docs/en/login-kit-web
