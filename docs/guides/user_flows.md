# TV7 User Flows

> End-to-end workflows and user journeys for operators, API clients, and background processes. Focus on the user perspective rather than implementation details.

---

## Operator Flows (Admin Dashboard)

### Flow 1: Initial Login
```
1. Navigate to /admin/login
2. Enter email and password
3. Submit form
4. ✓ Redirect to /admin/videos with session cookie
5. ✗ Invalid credentials → Error message, stay on login page
```

**Key points:**
- Cookie-based session using JWT
- Session expires after `JWT_ACCESS_TOKEN_EXPIRES_MINUTES`
- No "remember me" option (session-only)

---

### Flow 2: Video Ingestion
```
Operator Dashboard (/admin/videos)
  ↓
1. Paste YouTube URL in ingestion form
2. Submit form
  ↓
3a. Valid URL → Video queued, redirect to dashboard with flash message
3b. Invalid URL → Error displayed, remain on page
  ↓
4. Video appears in "Recent videos" list with status badge
5. Poll page or wait for status updates
  ↓
6. Status progression:
   - "Ingested" → Video created, download queued
   - "Processing" → Download complete, highlights being detected
   - "Ready" → All clips generated
   - "Error" → Something failed (check error message)
  ↓
7. Click video card to view details
```

**Status indicators:**
- 🔵 Ingested - Just queued
- 🔄 Processing - Download + highlight detection
- ✅ Ready - All clips available
- ❌ Error - Failed (hover/click for details)

---

### Flow 3: Video Detail & Clip Review
```
Video List (/admin/videos)
  ↓
Click "View details" → Video Detail Page (/admin/videos/{id})
  ↓
View:
- Video metadata (source URL, created date, status)
- Clip cards with:
  - Timing (start → end)
  - Caption/hook text
  - Status badge
  - Preview player (if rendered)
  ↓
Actions:
- Delete video (confirmation required)
- Back to video list
```

**Future actions (Phase 2):**
- Publish clips to platforms
- Re-run highlight detection
- Edit clip timings/captions

---

### Flow 4: User Management
```
Admin Navigation → Users
  ↓
User List (/admin/users)
  ↓
View all users with:
- Full name
- Email
- Status badge (Active/Inactive)
- Created date
  ↓
Click user → User Detail Page (/admin/users/{id})
  ↓
View:
- User information (ID, email, name, status)
- Account metadata (created, updated)
  ↓
Actions:
- Toggle status (Active ↔ Inactive)
- Delete user (blocked if viewing own account)
  ↓
Confirmation:
- Status toggle → Redirect with flash message
- Delete → JavaScript confirm() → Redirect to user list
```

**Safety guards:**
- Cannot delete yourself
- Delete button disabled for current user
- Confirmation dialog before deletion

---

### Flow 5: Session Expiry
```
Logged in → Performing actions
  ↓
Session expires (JWT timeout)
  ↓
Next request → 303 Redirect to /admin/login
  ↓
Log in again → Resume work
```

**Note:** No automatic token refresh in admin dashboard (unlike API)

---

## API Client Flows

### Flow 1: Authentication
```
1. POST /api/v1/auth/login
   Body: { "email": "...", "password": "..." }
  ↓
2a. Success → 200 OK
    Response: {
      "access_token": "eyJ...",
      "refresh_token": "eyJ...",
      "token_type": "bearer"
    }
  ↓
2b. Failure → 401 Unauthorized
    Response: { "detail": "Invalid credentials" }
  ↓
3. Store access_token for future requests
4. Use in Authorization header: "Bearer {access_token}"
```

**Token lifecycle:**
- Access token: Short-lived (default: 15 min)
- Refresh token: Long-lived (default: 7 days)

---

### Flow 2: Token Refresh
```
Access token expires
  ↓
1. POST /api/v1/auth/refresh
   Body: { "refresh_token": "eyJ..." }
  ↓
2a. Success → 200 OK
    Response: {
      "access_token": "eyJ...",  // New access token
      "token_type": "bearer"
    }
  ↓
2b. Failure → 401 Unauthorized
    Refresh token invalid/expired → Re-authenticate
  ↓
3. Update stored access_token
4. Resume API calls
```

---

### Flow 3: Video Ingestion (API)
```
1. POST /api/v1/videos/ingest
   Headers: Authorization: Bearer {token}
   Body: { "youtube_url": "https://youtube.com/watch?v=..." }
  ↓
2a. Success → 201 Created
    Response: {
      "video_id": 123,
      "status": "queued",
      "created": true
    }
  ↓
2b. Duplicate URL → 200 OK
    Response: {
      "video_id": 123,
      "status": "queued",
      "created": false  // Already exists, re-queued
    }
  ↓
2c. Invalid URL → 422 Unprocessable Entity
    Response: { "detail": "Invalid YouTube URL" }
  ↓
3. Poll status endpoint to track progress
```

---

### Flow 4: Status Polling
```
After ingestion → Poll for completion
  ↓
Loop:
  GET /api/v1/videos/{video_id}
  Headers: Authorization: Bearer {token}
  ↓
  Response: {
    "id": 123,
    "status": "processing",  // or "ready", "error"
    "clips": [...],
    "created_at": "...",
    ...
  }
  ↓
  If status == "ready" → Break loop
  If status == "error" → Handle error
  Else → Wait N seconds, repeat
```

**Recommended polling intervals:**
- First minute: Every 5 seconds
- After 1 minute: Every 15 seconds
- After 5 minutes: Every 30 seconds

---

### Flow 5: Clip Retrieval
```
Video status == "ready"
  ↓
GET /api/v1/videos/{video_id}/clips
Headers: Authorization: Bearer {token}
  ↓
Response: [
  {
    "id": 1,
    "start_sec": 10,
    "end_sec": 45,
    "caption_text": "Check out this moment!",
    "status": "ready",
    "local_path": "/media/clips/clip_1.mp4"
  },
  ...
]
  ↓
Download clips or trigger publishing
```

---

## Background Processing Flows

### Flow 1: Video Pipeline (Happy Path)
```
User ingests YouTube URL
  ↓
1. create_video_record(url) → Video(id=1, status="ingested")
  ↓
2. enqueue_task(process_video, video_id=1)
  ↓
Worker picks up task:
  ↓
3. download_video_task(video_id=1)
   - Download video via yt-dlp
   - Fetch transcript via youtube-transcript-api
   - Save to local storage
   - Update: Video(status="processing", local_path="...", transcript_text="...")
  ↓
4. detect_highlights_task(video_id=1)
   - Send transcript to OpenAI API
   - Parse response (segments with start/end/hook)
   - Create Clip records (status="rendering")
   - Keep Video(status="processing")
  ↓
5. render_clips_task(video_id=1)  [FUTURE: Phase 1.8-1.9]
   - For each clip: ffmpeg slice, reframe, burn subtitles
   - Update: Clip(status="ready", local_path="...")
  ↓
6. finalize_video_task(video_id=1)
   - Check all clips ready
   - Update: Video(status="ready")
  ↓
User sees "Ready" status in dashboard
```

---

### Flow 2: Error Handling in Pipeline
```
Any task fails
  ↓
1. Catch exception
2. Log error with context (video_id, task name, traceback)
3. Update status:
   - Video(status="error", error_message="...")
   - OR Clip(status="error")
  ↓
4. Dramatiq retry logic:
   - Retry 3x with exponential backoff
   - If still failing → Mark as error permanently
  ↓
Operator sees "Error" status in dashboard
  ↓
Operator checks error message
  ↓
Options:
- Re-ingest URL (duplicate detection re-queues)
- Manual intervention (check logs, fix issue)
- Delete video and try different URL
```

**Common failure points:**
- YouTube download fails (video unavailable, region-locked)
- Transcript unavailable (no captions)
- OpenAI API error (rate limit, timeout)
- ffmpeg fails (future: corrupt video, unsupported format)

---

### Flow 3: Task Lifecycle
```
API enqueues task
  ↓
Dramatiq broker (Redis)
  ↓
Worker process polls broker
  ↓
Worker picks up task
  ↓
Execute task function
  ↓
Success → Acknowledge message, remove from queue
Failure → Retry (up to max_retries)
Dead letter → Log and mark as failed
```

**Worker configuration:**
- Concurrency: `WORKER_CONCURRENCY` (default: 2)
- Retry policy: 3 attempts, exponential backoff
- Timeout: Task-specific (download: 5min, LLM: 2min, etc.)

---

## Authentication Flows

### JWT Lifecycle (API)
```
Login
  ↓
Issue:
- access_token (exp: 15 min)
- refresh_token (exp: 7 days)
  ↓
Client stores both tokens
  ↓
Use access_token in Authorization header
  ↓
Access token expires
  ↓
Refresh:
- POST /api/v1/auth/refresh with refresh_token
- Receive new access_token
  ↓
Continue using new access_token
  ↓
Refresh token expires
  ↓
Re-authenticate (full login)
```

### Cookie-Based Session (Admin)
```
Login form submit
  ↓
Backend validates credentials
  ↓
Issue access_token (same as API)
  ↓
Set cookie: admin_session={access_token}
  - httponly: true
  - secure: true (production)
  - samesite: lax
  ↓
Browser includes cookie in subsequent requests
  ↓
Backend reads cookie, validates JWT
  ↓
Cookie expires (same as access_token)
  ↓
Next request → Redirect to /admin/login
```

**Why cookies for admin, not API?**
- Admin: Human operators using browsers (cookies prevent CSRF, easier UX)
- API: Programmatic clients (bearer tokens more flexible, standard REST practice)

---

## Error Recovery Patterns

### Pattern 1: Retry with Backoff
```
Task fails → Wait → Retry
  ↓
Attempt 1: Immediate
Attempt 2: +5 seconds
Attempt 3: +25 seconds (5^2)
Attempt 4: Mark as error
```

### Pattern 2: User Re-Queue
```
Video in "error" state
  ↓
Operator re-ingests same URL
  ↓
System detects existing Video record
  ↓
Re-queue processing (set status="ingested", clear error)
  ↓
Pipeline runs again
```

### Pattern 3: Manual Intervention
```
Persistent failure
  ↓
Check logs (JSON-formatted logging output)
  ↓
Fix issue (API key, network, etc.)
  ↓
Either:
- Re-ingest video
- Delete and create new
- Manual database fix + re-queue
```

---

## Future Flows (Planned)

### Publishing Flow (Phase 2.2)
```
Operator views clip → Click "Publish"
  ↓
Select platforms (YouTube Shorts, TikTok, Instagram)
  ↓
Submit
  ↓
Create PublishJob records (status="pending")
  ↓
Background worker:
- Upload to each platform API
- Update PublishJob(status="success" or "error")
- Update Clip(status="published_partial" or "published_all")
  ↓
Operator sees publish status in dashboard
```

### Scheduled Publishing (Phase 3.4)
```
Operator sets publish date/time
  ↓
PublishJob(scheduled_at="2025-12-01 10:00")
  ↓
Cron or delayed task triggers at scheduled time
  ↓
Execute publish
  ↓
Notify operator (email, webhook, dashboard)
```

---

## Quick Reference

**Operator actions:**
- Ingest video → Dashboard form
- Check status → Poll dashboard or API
- Manage users → /admin/users
- Review clips → /admin/videos/{id}

**API client actions:**
- Authenticate → POST /api/v1/auth/login
- Ingest video → POST /api/v1/videos/ingest
- Poll status → GET /api/v1/videos/{id}
- Get clips → GET /api/v1/videos/{id}/clips

**Background tasks:**
- Download → yt-dlp + transcript API
- Highlights → OpenAI GPT
- Render → ffmpeg (future)
- Publish → Platform APIs (future)
