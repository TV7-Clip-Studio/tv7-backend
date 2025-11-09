# Off-Roadmap Rationale

> Detailed reasoning for features built outside the main roadmap. Each entry explains why the feature was prioritized, implementation decisions, and operational considerations.

## User Management & Admin Features

### U.1 — Admin User Management Dashboard

**Why built now:**
- **Operational necessity:** As the application gains users, operators need a way to manage accounts without direct database access or API clients.
- **Reduces friction:** Manual user management via SQL queries or API calls is error-prone and requires technical expertise. A UI democratizes user administration.
- **Security hygiene:** Viewing user accounts, checking authentication status, and managing access are fundamental admin operations that should be as easy as managing videos.
- **Foundation for future features:** User management UI establishes patterns for other admin resources (clips, publish jobs, etc.) and provides a template for future dashboards.

**Implementation decisions:**
- **Reused existing patterns:** Followed the same router → service → repository layering as videos, maintaining architectural consistency.
- **Cookie-based auth for admin:** Admin pages use JWT cookies (not bearer tokens) for session management, matching the existing `/admin/videos` pattern.
- **Minimal but complete:** Focused on essential CRUD operations rather than advanced features (search, filtering, pagination). These can be added incrementally as user counts grow.
- **Visual consistency:** Matched the existing dark theme, card layouts, and status badge styles from the video dashboard for a cohesive admin experience.

**Notable dependencies:**
- Builds on Phase 1.4.x JWT authentication infrastructure.
- Extends `UserRepository` and `services/users.py` with new methods without breaking existing API endpoints.
- Tests reuse `system_login_credentials` fixture, keeping test setup DRY.

**Important:**
- All user management routes require authentication. Unauthenticated requests redirect to `/admin/login`.
- Self-deletion protection prevents operator lockout. The service layer enforces this rule, not just the UI.
- Hard delete is used for simplicity. If compliance or audit requirements emerge, migrate to soft delete by adding `deleted_at` timestamp and filtering queries.

---

### U.2 — User Status Management

**Why built now:**
- **Common administrative need:** Temporarily disabling accounts (suspicious activity, account issues, offboarding) is a standard operation.
- **Non-destructive control:** Toggling `is_active` is reversible, unlike deletion. Reduces risk of accidental data loss.
- **Already in the model:** The `User.is_active` field existed but had no UI or service-layer support. Exposing this field required minimal new code.

**Implementation decisions:**
- **Toggle, not set:** The UI flips the current state rather than requiring the operator to choose active/inactive. Fewer clicks, less cognitive load.
- **Immediate feedback:** Status changes redirect back to the user detail page with a flash message confirming the action.
- **Auth impact:** Inactive users cannot obtain JWT tokens (enforced in `authenticate_user` service). Existing sessions remain valid until token expiry.

**Important:**
- Status changes do not invalidate existing JWT tokens. If immediate logout is required, implement token revocation (future enhancement).
- The toggle endpoint is idempotent; repeated calls flip the state predictably.

---

### U.3 — Enhanced Admin Navigation

**Why built now:**
- **User experience:** Without navigation, operators must manually type URLs or use browser back buttons to move between Videos and Users sections.
- **Discoverability:** New users may not know the Users section exists. A visible nav menu surfaces available features.
- **Scalability:** As more admin sections are added (clips management, publish jobs, analytics), a central navigation becomes essential.

**Implementation decisions:**
- **Minimal styling:** Simple horizontal links in the header, matching the existing aesthetic. Avoids over-engineering with sidebars or dropdowns.
- **No active state tracking:** Links don't highlight the current page. Could be added with JavaScript or server-side context if needed.
- **Consistent placement:** Navigation appears in the header on all admin pages via the `base.html` template, ensuring it's always accessible.

**Important:**
- Navigation HTML is in `base.html`. Future admin sections should extend this menu, not create separate navigation patterns.
- Link order reflects priority: Videos (core feature) first, Users (supporting feature) second.

---

### U.4 — User Deletion with Safety Guards

**Why built now:**
- **Data hygiene:** Operators need to remove test accounts, duplicates, or offboarded users.
- **Security:** Deleting compromised accounts is a critical security response. The operation must be available but guarded.
- **Self-service:** Without a UI, deletion requires SQL access, which most operators shouldn't have.

**Implementation decisions:**
- **Hard delete:** Permanently removes the user and relies on database cascade rules for related data. Simpler than soft delete but irreversible.
- **Self-deletion protection:** Service layer checks `current_user_id` and raises `CannotDeleteCurrentUserError` if the user tries to delete themselves. Prevents accidental operator lockout.
- **Client-side confirmation:** JavaScript `confirm()` dialog asks "Are you sure?" before submitting the delete form. Low-tech but effective.
- **UI-level protection:** Delete button is disabled and replaced with an info message when viewing your own account. Defense in depth—UI, service, and business logic all enforce the rule.

**Notable dependencies:**
- Assumes `User` has no foreign key relationships that would prevent deletion. If future models reference `User` (e.g., `Video.created_by_user_id`), update cascade rules or implement soft delete.
- Deletion redirects to `/admin/users` with a success flash. Failed deletions (e.g., non-existent user, self-deletion attempt) redirect back to the detail page with an error.

**Important:**
- Hard delete means no recovery. For production deployments, consider:
  - Database backups before deletion.
  - Soft delete with `deleted_at` timestamp if regulatory compliance requires audit trails.
  - Delayed deletion (mark for deletion, purge after 30 days) to allow undo.
- If a user is deleted, their JWT tokens remain valid until expiration. For immediate revocation, implement a token blacklist (future enhancement).

---

### U.5 — Google OAuth Social Login

**Why built now:**
- **User experience:** Social login reduces friction—users don't need to remember another password or go through email verification flows.
- **Market expectations:** Modern web applications increasingly offer social login as a standard feature. Users expect to "Sign in with Google" alongside traditional email/password.
- **Security benefits:** Google handles password management, 2FA, and account recovery. Reduces our attack surface and eliminates password reset flows.
- **Account verification:** Google emails are pre-verified, eliminating the need for email confirmation workflows.
- **Foundation for future providers:** OAuth infrastructure (state validation, token exchange, account linking) can be extended to support GitHub, Microsoft, etc. with minimal changes.

**Implementation decisions:**
- **Google-first, multi-provider ready:** Focus on Google OAuth initially (most widely used), but design the schema and service layer to accommodate multiple providers (GitHub, Microsoft) in the future via the `auth_provider` enum.
- **Automatic account linking:** If a user signs in with Google and their email matches an existing account, automatically link the OAuth provider to that account. This works because Google verifies emails, so we can trust the match. Reduces duplicate accounts.
- **Authlib library:** Use `authlib>=1.3` rather than implementing OAuth from scratch. Authlib is the industry standard Python OAuth library, actively maintained, and supports OIDC (OpenID Connect) for fetching user profile data.
- **State parameter for CSRF protection:** Generate a cryptographically secure random state, sign it with `OAUTH_STATE_SECRET`, and validate on callback. Store used states in Redis with a 10-minute TTL to prevent replay attacks.
- **Nullable password hash:** Make `User.password_hash` nullable to support Google-only accounts. Existing email/password users keep their hashes; Google users have `password_hash=NULL`.
- **Admin + API support:** OAuth works for both admin dashboard (cookie-based sessions) and API clients (JWT bearer tokens). Use `redirect` query param (`?redirect=admin`) to distinguish the flow.
- **Backward compatible:** Email/password login remains fully functional. Google login is an *addition*, not a replacement. Users can choose either method.

**Notable dependencies:**
- **Google Cloud Project:** Requires creating a Google Cloud Project, enabling Google+ API, and configuring OAuth consent screen and credentials. See README for setup instructions.
- **Environment variables:** Four new required settings (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `OAUTH_STATE_SECRET`). If not configured, Google login button won't appear (graceful degradation).
- **Redis for state storage:** In production, use Redis to store and validate OAuth state tokens with TTL. Prevents state reuse/replay attacks.
- **Alembic migration:** Database schema changes (new columns, nullable password hash) require a migration. Backfill existing users with `auth_provider='email'`.

**Security considerations:**
- **State validation:** Every OAuth callback must validate the `state` parameter to prevent CSRF attacks. State must be signed, time-limited (10 minutes), and single-use.
- **Redirect URI whitelist:** Only allow whitelisted redirect URIs in Google Console. Never accept arbitrary redirect URIs from client requests.
- **Account takeover prevention:** Automatic account linking is safe because Google verifies email ownership. We only link when `oauth_provider_id` matches or email matches exactly.
- **Token security:** OAuth access tokens from Google are used once (to fetch user profile), then discarded. We issue our own JWT tokens using existing auth infrastructure.
- **Profile picture URLs:** Store Google profile picture URLs but sanitize/validate before rendering in HTML to prevent XSS.

**Important:**
- **Email/password remains available:** Users can still sign in with traditional credentials. Google OAuth is optional for users but enabled by default if configured.
- **Account linking is automatic:** If a user signs up with email/password, then later signs in with Google (same email), the accounts merge automatically. Log this event for audit trails.
- **Password reset not needed for Google users:** Google-only users (no password hash) cannot use password reset flows. If they lose Google access, they need admin help to set a password or recover their account.
- **Multiple providers future-proof:** The `auth_provider` field is an enum (`email`, `google`). Future providers (GitHub, Microsoft) can be added by extending the enum and duplicating the OAuth service pattern.
- **Production redirect URI:** Update `GOOGLE_REDIRECT_URI` to production domain (e.g., `https://tv7.example.com/api/v1/auth/google/callback`) before deploying. Mismatched redirect URIs will cause Google to reject the OAuth flow.
- **State storage scaling:** For high-traffic deployments, use Redis for state validation instead of in-memory storage. The plan assumes Redis (already used for Dramatiq) is available.

**Testing strategy:**
- **Mock Google responses:** Use `pytest` fixtures to mock Google's authorization URL, token exchange, and user info endpoints. No real Google API calls in tests.
- **State validation tests:** Ensure invalid/missing/expired/reused states are rejected (CSRF protection).
- **Account linking tests:** Verify new user creation, existing user login, and automatic linking when emails match.
- **Error handling tests:** Handle Google API errors gracefully (network failures, invalid tokens, denied consent).

---

## General Off-Roadmap Philosophy

**When to add off-roadmap features:**
- **Blocking operational needs:** Features that prevent the team from using the application effectively (e.g., user management).
- **Low-cost, high-value:** Quick wins that improve UX or reduce friction without derailing roadmap progress.
- **Foundation for future work:** Infrastructure or patterns that will be reused as the roadmap progresses.

**When to defer off-roadmap features:**
- **Speculative value:** Features requested by hypothetical future users without current operational need.
- **High complexity:** Features that would consume significant time better spent on roadmap milestones.
- **Can be worked around:** Features that have acceptable manual workarounds (e.g., SQL queries for one-off data tasks).

**Documentation expectations:**
- All off-roadmap features should be documented in `off_roadmap.md` with completion status, date, and implementation summary.
- Rationale should explain *why now* and *why this approach* to guide future contributors.
- Tests are mandatory. Off-roadmap doesn't mean lower quality standards.
