# YouTube Authentication Guide

> **TL;DR**: YouTube OAuth (for uploading) and cookies (for downloading) are separate systems. You need both.

## Two Separate Authentication Systems

YouTube uses two completely different authentication mechanisms:

### 1. YouTube Data API (OAuth 2.0)

**Purpose**: API operations like uploading videos, managing playlists, reading channel data

**How it works**:
- Users click "Connect YouTube" in admin dashboard
- OAuth flow redirects to Google for permission
- App receives access token + refresh token
- Tokens stored in `youtube_credentials` table

**What you can do**:
- ✅ Upload generated clips to YouTube Shorts
- ✅ Manage your YouTube channel via API
- ✅ Read video metadata via API
- ❌ **Cannot** download videos with yt-dlp

**Setup**: See [youtube_oauth_connector.md](youtube_oauth_connector.md)

**Status**: ✅ Fully implemented (Phase 2.7)

---

### 2. YouTube Video Player (Browser Cookies)

**Purpose**: Watching and downloading videos (what yt-dlp needs)

**How it works**:
- Export cookies from authenticated browser session
- Upload cookies as base64-encoded secret
- yt-dlp uses cookies to bypass age restrictions and bot detection

**What you can do**:
- ✅ Download videos including age-restricted content
- ✅ Bypass "Sign in to confirm you're not a bot" errors
- ❌ **Cannot** use for API operations

**Setup**: See [youtube_cookies_setup.md](youtube_cookies_setup.md)

**Maintenance**: Refresh cookies every 6-12 months when they expire

---

## Why Can't OAuth Tokens Be Used for Downloads?

Google intentionally separates these systems for security and business reasons:

1. **OAuth tokens** grant API access (controlled, rate-limited, auditable)
2. **Browser cookies** grant player access (simulates logged-in user)

yt-dlp is a **video downloader**, not an API client. It needs to pretend to be a browser watching videos, which requires browser session cookies, not API tokens.

**Technical limitation**: yt-dlp doesn't support YouTube OAuth bearer tokens. Even if you pass an access token, YouTube's video player endpoint will reject it.

---

## Recommended Setup

### For Production (Fly.io)

1. **OAuth** (for future publishing features):
   ```bash
   fly secrets set \
     YOUTUBE_CLIENT_ID="your-client-id" \
     YOUTUBE_CLIENT_SECRET="your-secret" \
     YOUTUBE_REDIRECT_URI="https://your-app.fly.dev/admin/youtube/callback" \
     -a your-app
   ```

2. **Cookies** (for video downloads):
   ```bash
   # Export cookies from browser (see youtube_cookies_setup.md)
   base64 youtube_cookies.txt > youtube_cookies_b64.txt

   fly secrets set \
     YOUTUBE_COOKIES_B64="$(cat youtube_cookies_b64.txt)" \
     -a your-app
   ```

### For Local Development

1. **OAuth** (in `.env`):
   ```bash
   YOUTUBE_CLIENT_ID=your-client-id
   YOUTUBE_CLIENT_SECRET=your-secret
   YOUTUBE_REDIRECT_URI=http://127.0.0.1:8000/admin/youtube/callback
   ```

2. **Cookies** (in `.env`):
   ```bash
   YOUTUBE_COOKIES_FILE=/path/to/youtube_cookies.txt
   # OR use browser cookies directly:
   YOUTUBE_COOKIES_BROWSER=chrome
   ```

---

## When to Use Each Method

| Task | Auth Method | Notes |
|------|-------------|-------|
| Download source videos | **Cookies** | Required for yt-dlp |
| Upload generated clips | **OAuth** | Future feature (Phase 3) |
| Bypass age restrictions | **Cookies** | OAuth won't help |
| Avoid bot detection | **Cookies** | OAuth won't help |
| Manage YouTube channel | **OAuth** | API operations |

---

## Troubleshooting

### Error: "Sign in to confirm you're not a bot"

**Cause**: No cookies configured or cookies expired

**Solution**:
1. Export fresh cookies from browser (see [youtube_cookies_setup.md](youtube_cookies_setup.md))
2. Upload to `YOUTUBE_COOKIES_B64` secret
3. Redeploy app

**Note**: The OAuth connection shown in the admin UI is unrelated to this error

### OAuth Connected but Downloads Still Fail

**Explanation**: This is expected! OAuth is for API operations (future features), not downloads.

**Solution**: Configure cookies separately (see above)

### Cookies Expired After 6 Months

**Cause**: YouTube cookies have limited lifetime

**Solution**: Re-export cookies and update `YOUTUBE_COOKIES_B64` secret

This is normal maintenance for production yt-dlp deployments

---

## Future Improvements

### Option A: Auto-Cookie Extraction (Complex)

When users connect OAuth, we could:
1. Open headless browser (Playwright)
2. Use OAuth to sign in to YouTube
3. Extract cookies from browser session
4. Store for yt-dlp use

**Pros**: Automatic cookie refresh when users re-authenticate

**Cons**: Requires browser automation in Docker, complex setup

### Option B: Switch to YouTube Data API

Stop downloading videos entirely. Instead:
- Users upload videos directly to app
- Use YouTube Data API to fetch metadata
- Upload generated clips via OAuth

**Pros**: Fully OAuth-based, no cookies needed

**Cons**: Different workflow, can't process arbitrary YouTube URLs

---

## References

- [YouTube Data API](https://developers.google.com/youtube/v3)
- [yt-dlp Authentication](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
- [Exporting YouTube Cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
