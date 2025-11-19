# YouTube Cookies Setup Guide

YouTube requires authentication to bypass bot detection when downloading videos. This guide shows how to set up cookies for both local development and production (Fly.io).

## Why This Is Needed

YouTube has aggressive bot detection that blocks yt-dlp downloads. You'll see errors like:
```
ERROR: [youtube] Sign in to confirm you're not a bot
```

## Solution: Export Your Browser Cookies

### Step 1: Export Cookies from Your Browser

1. **Install a browser extension** to export cookies:
   - **Chrome**: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - **Firefox**: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
   - **Edge**: Search "cookies.txt" in Edge Add-ons

2. **Log into YouTube** in your browser (use the account you want to authenticate with)

3. **Visit youtube.com** and click the extension icon

4. **Export cookies** and save as `youtube_cookies.txt`

### Step 2: Local Development (Docker)

For local Docker development:

```bash
# 1. Place cookies file in your project root
cp ~/Downloads/youtube_cookies.txt ./youtube_cookies.txt

# 2. Update .env
echo "YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt" >> .env

# 3. Update docker-compose.yml to mount the cookies file
```

Edit `docker-compose.yml`:

```yaml
services:
  api:
    volumes:
      - ./src:/app/src
      - ./alembic:/app/alembic
      - ./media:/app/media
      - ./youtube_cookies.txt:/app/youtube_cookies.txt  # Add this line

  worker:
    volumes:
      - ./src:/app/src
      - ./scripts:/app/scripts
      - ./alembic:/app/alembic
      - ./media:/app/media
      - ./youtube_cookies.txt:/app/youtube_cookies.txt  # Add this line
```

```bash
# 4. Restart containers
docker compose restart api worker
```

### Step 3: Production (Fly.io)

For Fly.io deployment, you have two options. When running outside Docker (e.g., local uvicorn), make sure Node.js 18+ is installed so yt-dlp can execute YouTube’s player JavaScript; the Docker/Fly image already bundles Node.

#### Option A: Use Fly Secrets (Recommended)

```bash
# 1. Base64 encode the cookies file
cat youtube_cookies.txt | base64 > youtube_cookies_b64.txt

# 2. Set as Fly secret
fly secrets set YOUTUBE_COOKIES_B64="$(cat youtube_cookies_b64.txt)" -a forgotten-app

# 3. Update Dockerfile to decode the secret
```

Add to your `Dockerfile` or entrypoint script:

```dockerfile
# In Dockerfile or docker/entrypoint.sh
RUN if [ -n "$YOUTUBE_COOKIES_B64" ]; then \
      echo "$YOUTUBE_COOKIES_B64" | base64 -d > /app/youtube_cookies.txt; \
    fi
```

```bash
# 4. Set the environment variable
fly secrets set YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt -a forgotten-app

# 5. Deploy
fly deploy -a forgotten-app
```

#### Option B: Bake into Docker Image (Less Secure)

⚠️ **Warning**: This embeds your cookies into the Docker image. Anyone with access to the image can extract them.

```dockerfile
# Add to Dockerfile
COPY youtube_cookies.txt /app/youtube_cookies.txt
```

```bash
# Set environment variable
fly secrets set YOUTUBE_COOKIES_FILE=/app/youtube_cookies.txt -a forgotten-app

# Deploy
fly deploy -a forgotten-app
```

### Step 4: Verify It Works

Check the logs to see if cookies are being used:

```bash
# Local
docker compose logs -f worker | grep -i cookies

# Fly
fly logs -a forgotten-app | grep -i cookies
```

You should see logs like:
```
Using cookies file for YouTube download cookies_file=/app/youtube_cookies.txt
Using cookies file for YouTube transcript fetch cookies_file=/app/youtube_cookies.txt
```
The same exported cookies are reused by yt-dlp (video download) and as a fallback for
transcripts when OAuth isn't connected. If cookies expire while OAuth is also unavailable,
highlight detection can't read captions, so refresh them whenever you see `RequestBlocked`
or "Sign in to confirm you're not a bot" errors in Fly logs.

Then try ingesting a video from the admin dashboard.

## Security Considerations

### Cookie Expiration
- YouTube cookies typically expire after 1-2 weeks
- You'll need to re-export and update them periodically
- Set a calendar reminder to refresh cookies monthly

### Cookie Security
- **Never commit `youtube_cookies.txt` to git**
  - Add to `.gitignore` immediately
- Use Fly secrets rather than baking into image
- Rotate cookies if they're compromised

### .gitignore Entry

Add this to your `.gitignore`:

```gitignore
# YouTube cookies
youtube_cookies.txt
youtube_cookies_b64.txt
```

## Troubleshooting

### "Cookies file not found"
- Check the path in `YOUTUBE_COOKIES_FILE`
- Verify the file is mounted in Docker or present in Fly container
- Check logs: `docker compose logs api` or `fly logs`

### "Sign in to confirm you're not a bot" (still happening)
- Cookies may have expired - re-export from browser
- Make sure you're logged into YouTube in the browser when exporting
- Try logging out and back into YouTube, then re-export

### "Invalid cookies format"
- Make sure you're using Netscape format (what the extensions export)
- File should start with `# Netscape HTTP Cookie File`
- Don't edit the file manually

## Alternative: Try Different Videos

Some YouTube videos have less strict bot detection. If a video fails, try:
- Different video URLs
- Shorter videos
- Videos from verified/popular channels
- Videos without age restrictions

## Future: OAuth Integration

For production use at scale, consider implementing YouTube Data API with OAuth:
- More reliable than cookies
- Officially supported by Google
- Requires Google Cloud project setup
- See: https://developers.google.com/youtube/v3
