# YouTube OAuth Connector (Future Enhancement)

## Problem

Cookie-based authentication is fragile:
- Cookies expire every 1-2 weeks
- Cloud IPs (Fly.io) get blocked more aggressively
- Manual cookie export is tedious
- Not scalable for multiple users/operators

## Better Solution: OAuth Connector

Allow operators to authenticate directly with their YouTube account, then download videos "on their behalf." The same OAuth connection now powers transcript downloads through the YouTube Data API (`youtube.force-ssl` scope) so captions remain available even when cookie scraping fails.

## How It Would Work

### User Flow

1. Operator clicks "Connect YouTube Account" in admin dashboard
2. Redirected to Google OAuth consent screen
3. Grants permission to download videos
4. Redirected back to dashboard
5. Downloads now use their authenticated session

### Technical Architecture

```
┌─────────────┐
│   Admin     │
│  Dashboard  │
└──────┬──────┘
       │ 1. Click "Connect YouTube"
       │
       ▼
┌─────────────┐
│   OAuth     │
│   Flow      │──────────► Google OAuth
└──────┬──────┘            Consent Screen
       │
       │ 2. User grants permission
       │
       ▼
┌─────────────┐
│   Store     │
│   Tokens    │ ◄────────  Access Token
└──────┬──────┘            Refresh Token
       │
       │ 3. Use token for downloads
       │
       ▼
┌─────────────┐
│  yt-dlp +   │
│  OAuth      │──────────► YouTube (authenticated)
└─────────────┘
```

### Implementation Steps

#### 1. Google Cloud Setup

```bash
# Create project in Google Cloud Console
# Enable YouTube Data API v3
# Create OAuth 2.0 credentials (Web application)
# Add redirect URI: https://your-app.com/auth/youtube/callback
```

#### 2. Database Schema

```python
# Add to models.py
class YouTubeConnection(Base):
    __tablename__ = "youtube_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # OAuth tokens
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)

    # YouTube account info
    youtube_channel_id = Column(String)
    youtube_channel_name = Column(String)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
```

#### 3. OAuth Flow

```python
# routes/auth/youtube.py
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.force-ssl'
    }
)

@router.get("/auth/youtube/login")
async def youtube_login(request: Request):
    redirect_uri = request.url_for('youtube_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/youtube/callback")
async def youtube_callback(
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_jwt_user)
):
    token = await oauth.google.authorize_access_token(request)

    # Store tokens in database
    connection = YouTubeConnection(
        user_id=current_user.id,
        access_token=token['access_token'],
        refresh_token=token['refresh_token'],
        token_expires_at=datetime.utcnow() + timedelta(seconds=token['expires_in'])
    )
    db.add(connection)
    await db.commit()

    return RedirectResponse("/admin/settings?youtube_connected=true")
```

#### 4. Token Refresh

```python
# services/youtube_oauth.py
async def get_valid_token(user_id: int) -> str:
    """Get a valid access token, refreshing if necessary."""
    connection = await get_youtube_connection(user_id)

    if not connection:
        raise ValueError("No YouTube connection found")

    # Check if token is expired
    if datetime.utcnow() >= connection.token_expires_at:
        # Refresh token
        new_token = await refresh_youtube_token(connection.refresh_token)
        connection.access_token = new_token['access_token']
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=new_token['expires_in'])
        await db.commit()

    return connection.access_token
```

#### 5. Use with yt-dlp

```python
# services/youtube_downloader.py
async def download_with_oauth(video_id: int, source_url: str, user_id: int):
    # Get valid OAuth token
    access_token = await get_valid_token(user_id)

    # Configure yt-dlp with OAuth
    ydl_opts = {
        "format": "bestvideo[height<=720]+bestaudio/best",
        # ... other options ...
        "http_headers": {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Mozilla/5.0 (compatible; YourApp/1.0)"
        }
    }

    # Or use cookies generated from OAuth session
    # (more complex but may work better)
```

#### 6. Admin UI

Add to admin dashboard:

```html
<!-- In admin/settings.html -->
<div class="youtube-connection">
  {% if youtube_connected %}
    <p>✓ YouTube account connected: {{ youtube_channel_name }}</p>
    <button onclick="disconnectYouTube()">Disconnect</button>
  {% else %}
    <a href="/auth/youtube/login" class="btn">Connect YouTube Account</a>
  {% endif %}
</div>
```

## Pros & Cons

### Pros
✅ Tokens refresh automatically (no manual cookie export)
✅ Uses official OAuth flow (more reliable)
✅ Multi-user support (each operator has their own connection)
✅ Revocable (users can disconnect anytime)
✅ Better UX (one-click setup)

### Cons
❌ More complex implementation
❌ Requires Google Cloud project setup
❌ Subject to YouTube API quotas
❌ May still face rate limits if downloading many videos

## Alternative: Hybrid Approach

Combine OAuth + cookies.txt as fallback:

```python
# Priority order:
1. Try OAuth token (if user connected)
2. Fall back to cookies file (if configured)
3. Fall back to no auth (will fail on most videos)
```

This gives flexibility while working toward the better solution.

## Estimated Effort

- **Simple cookie file**: ✅ Already done (1-2 hours)
- **OAuth connector**: 🔧 Medium complexity (8-16 hours)
  - OAuth flow: 4 hours
  - Token management: 2 hours
  - UI integration: 2 hours
  - Testing: 2-4 hours

## Recommendation

**Short-term (now):** Use cookies.txt file as implemented
**Medium-term (next sprint):** Implement OAuth connector
**Long-term:** Consider YouTube Data API for metadata only, store actual videos elsewhere

## References

- [Google OAuth 2.0 Guide](https://developers.google.com/identity/protocols/oauth2)
- [YouTube Data API](https://developers.google.com/youtube/v3)
- [Authlib Documentation](https://docs.authlib.org/)
- [yt-dlp Authentication](https://github.com/yt-dlp/yt-dlp#authentication-with-netrc)
