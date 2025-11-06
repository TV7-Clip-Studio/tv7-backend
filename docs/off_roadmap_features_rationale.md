# Off-Roadmap Features Rationale

> Detailed implementation notes and decision context for features developed outside the main roadmap. Each entry explains why the feature was needed, how it was implemented, and any important caveats for future maintainers.

---

## 0.14 — Application Rebranding

**Implemented:** 2025-01-XX
**PR/Commit:** `9198337` - "Rebrand application from 'Shorts Factory' to 'TV7'"

### Why

The application name evolved from a generic placeholder ("Forgotten App") to a feature descriptor ("Shorts Factory") and finally to the brand identity "TV7". This change was requested to align the user-facing product with its market positioning and branding strategy.

### Implementation Overview

**Changed:**
- `src/app/core/config.py` — Updated `APP_NAME` setting from `"My FastAPI Service"` to `"TV7"`. This value is consumed by FastAPI's OpenAPI docs title and can be referenced throughout the application.
- `src/app/templates/admin/base.html` — Changed the header `<strong>` tag from "Shorts Factory" to "TV7".
- `src/app/templates/admin/login.html` — Updated page title and descriptive text to reference "TV7".
- `docs/architecture.md` — Changed main heading from "Forgotten App → Shorts Factory" to "TV7".
- `docs/roadmap.md` — Updated title from "YouTube Shorts Factory Roadmap" to "TV7 Roadmap".
- `docs/agent_best_practices.md` — Changed heading to "TV7 Agent Best Practices".
- `README.md` — Updated project title to "TV7 — YouTube to Shorts Pipeline".
- `tests/test_admin_credentials.py` — Updated test fixtures to use "TV7" instead of "Forgotten App".

**Unchanged (by design):**
- `fly.toml` — The Fly.io app name remains `forgotten-app` because renaming would require infrastructure changes (DNS, volumes, secrets). Internal deployment names are not user-facing and can remain stable.
- `Makefile` — The `FLY_APP` variable stays `forgotten-app` for deployment tooling consistency.

### Important Notes

- The rebrand is purely cosmetic and does not affect application behavior or data models.
- Future domain mapping (e.g., `tv7.app`) will mask the internal `forgotten-app.fly.dev` hostname.
- If the Fly app name must eventually change, coordinate with ops to migrate volumes and secrets.

---

## 0.15 — User Profile Management

**Implemented:** 2025-01-XX
**PR/Commit:** TBD

### Why

Operators need the ability to view and update their own account information (full name, email, password) without requiring admin intervention or database access. The existing authentication system created users but provided no self-service profile management. This feature closes that gap while maintaining security through password verification for sensitive changes.

### Implementation Overview

**Data Layer:**
- Added `UserUpdate` Pydantic schema to `src/app/schemas.py` with optional fields: `full_name`, `email`, `current_password`, and `new_password`.
- Extended `UserRepository` with `get_by_id(user_id: int)` and `update(user: User)` methods for retrieving and persisting user changes.

**Service Layer:**
- Created `get_user_profile()` in `src/app/services/users.py` to fetch user data.
- Created `update_user_profile()` to handle updates with validation:
  - Check email uniqueness if the user is changing their email.
  - Verify `current_password` before allowing password changes.
  - Hash `new_password` using the existing password hashing utility.
- Added exception classes `InvalidPasswordError` and `EmailAlreadyTakenError` for clear error handling.

**API Layer:**
- `GET /api/v1/users/me` — Returns the authenticated user's `UserRead` payload. Protected by `Depends(require_jwt_user)`.
- `PATCH /api/v1/users/me` — Accepts `UserUpdate` payload and applies changes. Returns the updated `UserRead` or raises 400/409 errors for validation failures.

**Admin UI:**
- Created `src/app/templates/admin/profile.html` extending `admin/base.html`:
  - Displays current user information (full name, email, account age, last updated).
  - Provides a form to update full name and email.
  - Includes an optional password change section requiring current password verification.
  - Uses flash messages for success/error feedback.
- Added `GET /admin/profile` route in `src/app/admin/routes.py` to render the profile page.
- Added `POST /admin/profile` route to handle form submissions with validation and error handling.
- Updated `src/app/templates/admin/base.html` to include a "Profile" link in the header navigation.

**Testing:**
- API tests verify:
  - `GET /api/v1/users/me` returns correct user data.
  - `PATCH /api/v1/users/me` updates fields successfully.
  - Email conflicts return 409.
  - Password changes require correct current password.
  - Unauthorized requests return 401.
- System tests verify:
  - Profile page renders with correct user data.
  - Form submissions update the database.
  - Validation errors display correctly.
  - Unauthenticated users redirect to login.

### Important Notes

- **Password changes are optional.** If `current_password` and `new_password` are omitted, the password remains unchanged.
- **Email uniqueness is enforced.** Attempting to change to an email already in use returns a 409 conflict error.
- **Security:** The `current_password` field is required when changing passwords to prevent unauthorized account takeover if a session is compromised.
- **Admin access:** Currently, any authenticated user can only edit their own profile. Future enhancements could allow admins to edit other users via `/admin/users/{user_id}/edit`.

### Future Enhancements

- Add avatar/profile picture upload.
- Email verification flow when changing email addresses.
- Password strength requirements and validation feedback.
- Activity log showing recent logins and profile changes.
- Two-factor authentication setup.

---

## 0.16 — User-Scoped Video Ownership (Planned)

**Status:** Queued
**Rationale:** Currently, all videos are visible to all users. To support multi-user deployments and ensure data isolation, videos must be scoped to individual users.

### Why

The current implementation treats videos as globally accessible, which is acceptable for single-operator deployments but unsuitable for multi-user environments. Users should only see and manage videos they created, preventing accidental interference or data leakage.

### Proposed Implementation

**Database:**
- Add `user_id` column to the `videos` table as a foreign key to `users.id`.
- Create an Alembic migration that:
  - Adds the nullable `user_id` column (to support existing data).
  - Adds an index on `videos.user_id` for query performance.
  - Sets `ondelete="CASCADE"` so videos are removed when a user is deleted.
  - Optionally assigns existing videos to a default admin user or leaves them as `NULL`.

**Data Models:**
- Add `user_id: Mapped[int]` to the `Video` model with a foreign key relationship.
- Add `owner: Mapped[User]` relationship on `Video`.
- Add `videos: Mapped[list[Video]]` relationship on `User`.

**Repository Layer:**
- Update `VideoRepository.get_by_source_url()` to accept optional `user_id` and filter by it.
- Update `VideoRepository.list_with_clips()` to require `user_id` and filter results.
- Update `VideoRepository.get_with_clips()` to accept optional `user_id` for ownership verification.
- Add `VideoRepository.get_for_user(video_id, user_id)` for authorization checks.

**Service Layer:**
- Update `ingest_video()` to accept `user_id` and set it when creating new videos.
- Update `list_videos()` to accept `user_id` and pass it to the repository.
- Update `get_video_detail()` to verify ownership (or allow admin override in the future).

**API Layer:**
- Update `POST /videos/ingest` to extract `current_user.id` from `Depends(require_jwt_user)` and pass it to the service.
- Add `GET /videos` endpoint (if missing) that lists the current user's videos.
- Update `GET /videos/{video_id}` to verify the video belongs to the current user.

**Admin UI:**
- Update `GET /admin/videos` to pass `user.id` to `list_videos()`.
- Update `GET /admin/videos/{video_id}` to pass `user.id` for ownership verification.
- Update `POST /admin/videos/ingest` to pass `user.id` to `ingest_video()`.

**Testing:**
- Add tests to verify users cannot access other users' videos.
- Test that video ingestion correctly associates videos with the current user.
- Test that existing videos with `user_id=NULL` remain accessible (or handle them explicitly).

### Important Considerations

- **Migration strategy:** Existing videos will have `user_id=NULL`. Decide whether to:
  - Leave them orphaned (accessible only via direct ID).
  - Assign them to a default admin user.
  - Delete them (acceptable for dev/staging).
- **Admin access:** Future work could add an admin role that bypasses ownership checks to view all videos.
- **Cascade deletion:** If a user is deleted, their videos are also deleted. Consider soft deletes or orphaning videos instead.

---

## Maintenance Guidelines

- **When adding a new off-roadmap feature:**
  1. Add an entry to `off_roadmap_features.md` with status (Planned/In Progress/Completed).
  2. Add a detailed rationale entry to this file with "Why", "Implementation Overview", and "Important Notes".
  3. Update the status to ✅ Completed when the feature is merged.
  4. Reference the PR/commit hash for traceability.

- **When a feature graduates to the main roadmap:**
  - Move the entry from this document to `roadmap.md` and `roadmap_rationale.md`.
  - Add a note in this document redirecting readers to the main roadmap.

- **Keep both documents synchronized:**
  - Short summaries belong in `off_roadmap_features.md`.
  - Detailed implementation notes, decision context, and caveats belong here.
