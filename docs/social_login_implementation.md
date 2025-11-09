Social Login Implementation Plan (Google OAuth)
Overview
Add Google OAuth2 login as an alternative to email/password authentication, allowing users to sign in with their Google account while maintaining backward compatibility with existing email/password users.
1. Database Changes
1.1 Extend User Model
File: src/app/db/models.py Adjust existing `User` fields and introduce a dedicated OAuth table.
class AuthProvider(str, Enum):
    EMAIL = "email"
    GOOGLE = "google"

class User(Base):
    # Existing columns
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_auth_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AuthProvider.EMAIL.value,
        server_default=AuthProvider.EMAIL.value,
    )

class UserOAuthAccount(Base):
    __tablename__ = "user_oauth_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    picture_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at / updated_at timestamps

Unique constraint: (`provider`, `provider_user_id`) for lookup. Another unique constraint on (`user_id`, `provider`) prevents duplicates per provider. This approach keeps the `User` table simple, allows linking multiple providers later, and avoids schema churn when we add GitHub/Microsoft.

Key decisions:
- `password_hash` stays optional so Google-only accounts are valid; we can later offer “set password” to create a backup credential.
- `primary_auth_provider` reflects the most recent login method for analytics/UI but business logic should rely on `UserOAuthAccount`.
- OAuth metadata (provider ID, Google picture) lives in `user_oauth_accounts`.

1.2 Alembic Migration
File: alembic/versions/XXXX_add_oauth_support.py Migration steps:
- Create `user_oauth_accounts` table with the schema above.
- Add `primary_auth_provider` column to `users` with default `'email'`.
- Alter `password_hash` to be nullable.
- Backfill existing rows (set `primary_auth_provider='email'` wherever `password_hash IS NOT NULL`).
- Add indexes/constraints mentioned earlier.
2. Configuration Changes
2.1 Environment Variables
File: src/app/core/config.py Add OAuth config while deriving redirect URIs from canonical base URLs.
class Settings(BaseSettings):
    BACKEND_BASE_URL: AnyHttpUrl = "http://localhost:8000"  # already present; reuse
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_PATH: str = "/api/v1/auth/google/callback"
    OAUTH_STATE_SECRET: str = "change-me-oauth-state"

Add helper property:
    @property
    def google_redirect_uri(self) -> str:
        return urljoin(str(self.BACKEND_BASE_URL), self.GOOGLE_REDIRECT_PATH)

This keeps `.env` simple (no per-environment copy-paste) and ensures Fly + localhost use the same path while only the base URL changes.

2.2 Update .env.example
Add the new variables (without hardcoding full URIs):
# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
OAUTH_STATE_SECRET=random-secret-for-csrf-protection
GOOGLE_REDIRECT_PATH=/api/v1/auth/google/callback  # rarely changed; keep for completeness
3. Dependencies
3.1 Add OAuth Library
File: pyproject.toml Add to dependencies:
dependencies = [
    # Existing...
    "authlib>=1.3",  # OAuth client library
    "httpx>=0.27",   # Already in dev deps, move to main (for OAuth token exchange)
]
Why Authlib?
Industry standard OAuth2/OIDC client
Supports Google OAuth2 out of the box
Integrates well with FastAPI
Active maintenance and security updates
4. Service Layer
4.1 OAuth Service
File: src/app/services/oauth.py (new). Wrap Authlib’s `AsyncOAuth2Client` plus Google’s OIDC configuration.

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, jwt

class OAuthService:
    """Handle Google OAuth/OIDC flow and validation."""

    async def get_google_auth_url(self, state: str, redirect_uri: str) -> str:
        # Build authorization URL with PKCE + nonce support

    async def exchange_code_for_token(self, code: str, code_verifier: str, redirect_uri: str) -> dict:
        # Exchange code for tokens (access + id_token)

    async def validate_id_token(self, token_response: dict) -> dict:
        """
        Verify the Google ID token (iss, aud, exp) using Google JWKS.
        Returns decoded claims (sub, email, email_verified, picture, name).
        """

    async def get_google_user_info(self, access_token: str) -> dict:
        """Optional fallback for profile fields not present in ID token."""

Notes:
- Rely on `openid email profile` scope; prefer reading email/picture directly from the verified ID token.
- Cache Google JWKS for ~1 hour to avoid fetching per request.

State parameter:
- Generate cryptographically secure random state (32 bytes) + PKCE verifier.
- Sign state via HMAC using `OAUTH_STATE_SECRET`.
- Store state signature in Redis with 10-min TTL when available; fallback to signed, HttpOnly cookie when Redis/worker is unavailable (tests/local dev).
- Validate and delete on callback to avoid replay.
4.2 Extend User Service
File: src/app/services/users.py Add helpers focused on the new OAuth table.

async def get_or_create_oauth_user(*, provider: AuthProvider, provider_user_id: str, email: str, full_name: str, picture_url: str | None, repo: UserRepository, oauth_repo: UserOAuthAccountRepository) -> User:
    """
    1. Look up by (provider, provider_user_id).
    2. If not found, look up existing user by email (case-insensitive) and link.
    3. Otherwise create new user (password_hash=None) and attach OAuth row.
    4. Update picture_url / primary_auth_provider when user logs in via Google.
    """

async def link_oauth_account(user: User, provider: AuthProvider, provider_user_id: str, email: str, picture_url: str | None, oauth_repo: UserOAuthAccountRepository) -> UserOAuthAccount:
    """Persist or update the `user_oauth_accounts` row and ensure unique constraints hold."""

Repositories:
- `UserRepository` already exists; add `UserOAuthAccountRepository` (CRUD for the new table).

Account linking strategy:
- Trust Google’s verified email claim; automatically link when `email` matches an existing user to avoid duplicate accounts.
- Emit audit log (structured logger) whenever linking occurs.
- Allow multiple OAuth providers per user later without schema changes.
5. API Routes
5.1 OAuth Endpoints
File: src/app/api/v1/auth.py Add new routes: 1. Initiate OAuth Flow
@router.get("/auth/google/login")
async def google_login():
    """
    Redirect user to Google's OAuth consent screen.
    
    Steps:
    1. Generate state parameter (signed with OAUTH_STATE_SECRET)
    2. Build Google authorization URL
    3. Redirect user to Google
    
    Response: 302 redirect to Google
    """
2. OAuth Callback
@router.get("/auth/google/callback")
async def google_callback(code: str, state: str):
    """
    Handle Google OAuth callback.
    
    Steps:
    1. Validate state parameter + PKCE verifier (CSRF + code injection protection)
    2. Exchange code for access+ID tokens
    3. Validate ID token signature (audience, issuer, exp) via Google JWKS
    4. Read claims (sub, email, email_verified, name, picture)
    5. (Optional) Fetch extra profile info if picture missing
    4. Get or create user in our database
    5. Generate JWT tokens (same as email/password login)
    6. Return tokens OR redirect to admin dashboard with cookie
    
    Query params:
    - code: Authorization code from Google
    - state: CSRF protection token
    
    Response (API): { access_token, refresh_token, token_type }
Response (Admin): Redirect to /admin/videos with cookie set
    """
3. Get OAuth Providers
@router.get("/auth/providers")
async def get_oauth_providers():
    """
    Return list of enabled OAuth providers.
    
    Response: {
      "providers": ["google"],  # Only if GOOGLE_CLIENT_ID is configured
      "email_password_enabled": true
    }
    
    Used by frontend to show/hide Google login button.
    """
5.2 Update Existing Login
File: src/app/api/v1/auth.py Keep existing email/password login unchanged:
/auth/login - Email/password authentication
/auth/refresh - Token refresh (works for all auth methods)
6. Admin Dashboard UI
6.1 Login Page
File: src/app/templates/admin/login.html Add Google login button:
<form method="post" action="/admin/login">
  <!-- Existing email/password fields -->
  <button type="submit">Sign In</button>
</form>

<div style="margin: 1.5rem 0; text-align: center;">
  <span>— OR —</span>
</div>

<a href="/api/v1/auth/google/login?redirect=admin" 
   style="display: block; padding: 0.75rem; background: #fff; color: #333; border: 1px solid #ddd; border-radius: 4px; text-align: center;">
  <img src="/static/google-icon.svg" style="width: 20px; vertical-align: middle;"> 
  Sign in with Google
</a>
Key decisions:
Add redirect=admin query param to distinguish admin vs API OAuth flow
OAuth callback will set cookie and redirect to /admin/videos for admin users
Keep email/password form for backward compatibility
6.2 Static Assets
File: src/app/static/google-icon.svg (new) Add Google logo SVG for login button (download from Google brand guidelines)
7. Security Considerations
7.1 State Parameter Validation
Generate cryptographically secure random state (32 bytes)
Sign with HMAC using OAUTH_STATE_SECRET
Validate signature on callback
Prevent state reuse (store in Redis with 10-minute TTL)
7.2 Redirect URI Validation
Whitelist allowed redirect URIs in Google Console
Production: https://yourdomain.com/api/v1/auth/google/callback
Development: http://localhost:8000/api/v1/auth/google/callback
Never accept arbitrary redirect URIs
7.3 Email Verification
Google provides verified emails (no need for email verification flow)
Trust Google's email verification
7.4 Account Linking Security
Only link accounts if emails match exactly
Log account linking events for audit trail
Users can see linked providers in profile (future enhancement)
8. Testing Strategy
8.1 Unit Tests
File: tests/test_oauth_service.py (new) Test OAuth service with mocked HTTP responses:
State generation and validation
Token exchange
User info fetching
Error handling (invalid code, network errors)
8.2 System Tests
File: tests/system/test_auth_oauth_system.py (new) Test OAuth flow end-to-end with stubbed Google:
New user registration via Google
Existing user login via Google
Account linking (Google email matches existing email)
Invalid state parameter (CSRF protection)
Error handling (Google API errors)
Mock Google responses using pytest.fixture:
@pytest.fixture
def mock_google_oauth(monkeypatch):
    """Mock Google OAuth responses."""
    # Mock authorization URL generation
    # Mock token exchange
    # Mock user info fetch
8.3 Integration Tests
File: tests/integration/test_oauth_integration.py (new) Test with real database:
User creation with OAuth provider
Account linking updates existing user
Multiple users with same provider
Provider ID uniqueness
9. Documentation Updates
9.1 Architecture
File: docs/architecture.md Add OAuth flow diagram and endpoint documentation:
OAuth2 flow sequence
Account linking logic
New endpoints
9.2 User Flows
File: docs/user_flows.md Add flows:
Flow: Google Sign In (New User)
Flow: Google Sign In (Existing User)
Flow: Account Linking
9.3 Tech Stack
File: docs/tech_stack.md Add:
### authlib 1.3+
- OAuth2/OIDC client library
- Google OAuth integration
- PKCE support for enhanced security
9.4 README
File: README.md Add Google OAuth setup section:
Create Google Cloud Project
Enable Google+ API
Create OAuth2 credentials
Configure authorized redirect URIs
Add credentials to .env
10. Deployment Considerations
10.1 Google Cloud Console Setup
Create project: https://console.cloud.google.com
Enable Google+ API (for user profile access)
OAuth consent screen:
App name: TV7
User support email
Developer contact
Scopes: openid, email, profile
Create OAuth 2.0 Client ID:
Application type: Web application
Authorized redirect URIs:
Development: http://localhost:8000/api/v1/auth/google/callback
Production: https://yourdomain.com/api/v1/auth/google/callback
10.2 Fly.io Secrets
fly secrets set GOOGLE_CLIENT_ID=xxx
fly secrets set GOOGLE_CLIENT_SECRET=xxx
fly secrets set GOOGLE_REDIRECT_URI=https://yourdomain.com/api/v1/auth/google/callback
fly secrets set OAUTH_STATE_SECRET=random-secret
10.3 State Storage (Production)
Use Redis for state validation:
# Store state with 10-minute TTL
await redis.setex(f"oauth_state:{state}", 600, "1")

# Validate and consume state
if await redis.get(f"oauth_state:{state}"):
    await redis.delete(f"oauth_state:{state}")
else:
    raise InvalidStateError()
11. Implementation Order
Phase 1: Foundation (Database + Config)
Update User model + create `user_oauth_accounts` table
Create Alembic migration + repositories
Add OAuth settings helpers to config.py and `.env.example`
Add authlib/httpx dependencies
Phase 2: Service Layer 5. Create oauth.py service (state, token exchange, user info) 6. Extend users.py service (get_or_create_oauth_user, account linking) 7. Write unit tests for OAuth service Phase 3: API Routes 8. Add /auth/google/login endpoint 9. Add /auth/google/callback endpoint 10. Add /auth/providers endpoint 11. Write system tests for OAuth flow Phase 4: Admin UI 12. Update login template with Google button 13. Add Google icon asset 14. Test admin dashboard OAuth flow Phase 5: Documentation + Deployment 15. Update all docs (architecture, user_flows, tech_stack, README) 16. Create Google Cloud Project and OAuth credentials 17. Test on production (Fly.io) with real Google OAuth
12. Risks and Mitigations
Risk: Account takeover via email collision
Mitigation: Only link if email is verified by Google (which it always is)
Mitigation: Log all account linking events
Risk: CSRF attacks on OAuth callback
Mitigation: State parameter validation with cryptographic signing
Mitigation: Store used states in Redis to prevent replay
Risk: Google API changes breaking login
Mitigation: Pin authlib version
Mitigation: Monitor Google OAuth deprecation notices
Mitigation: Fallback to email/password always available
Risk: Users lose access if Google account disabled
Mitigation: Allow linking both Google + password to same account
Mitigation: Add "Set Password" feature for Google-only users (future)
13. Future Enhancements (Out of Scope)
Multiple OAuth providers: GitHub, Microsoft, etc.
Account unlinking: Remove Google from account
Profile management: Change profile picture from Google
Admin view: Show which provider user registered with
Force password creation: Require Google users to set password as backup
14. Success Criteria
✅ Users can sign in with Google on admin dashboard
✅ Users can sign in with Google via API
✅ Existing email users can link Google account automatically
✅ New users can register via Google
✅ All tests pass (unit, system, integration)
✅ Documentation updated
✅ Works in production with real Google OAuth
✅ Backward compatible (email/password still works)
✅ 85%+ test coverage maintained
Summary
This plan adds Google OAuth as a secure, user-friendly alternative to email/password authentication while maintaining full backward compatibility. The implementation follows TV7's established patterns (router→service→repository), includes comprehensive testing, and prioritizes security with state validation and account linking safeguards. Estimated effort: Medium-Large (3-5 days for full implementation + testing + docs) Dependencies: Google Cloud Project setup (1-2 hours) Breaking changes: None (fully backward compatible)
