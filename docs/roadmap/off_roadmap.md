# TV7 Off-Roadmap Features

> Features and improvements built outside the main roadmap, typically added for operational needs, user experience improvements, or technical debt reduction.

## User Management & Admin Features

### U.1 — Admin User Management Dashboard ✅
- **Status:** Complete
- **Added:** 2025-11-06
- **Implementation overview:** Built comprehensive user management interface within the admin dashboard, including user list view, detailed user pages, and user administration actions.
- **Components:**
  - Repository layer: `UserRepository.get_by_id()`, `update()`, `delete()`
  - Service layer: `get_user_detail()`, `update_user_status()`, `delete_user()`
  - Admin routes: `GET /admin/users`, `GET /admin/users/{user_id}`, `POST /admin/users/{user_id}/toggle-status`, `POST /admin/users/{user_id}/delete`
  - Templates: `admin/users.html`, `admin/user_detail.html`
  - Navigation: Added Users link to admin header navigation
- **Testing:** System tests (`test_admin_users_system.py`) and unit tests (`test_users_service.py`) cover all functionality
- **Important:** Prevents self-deletion to avoid operator lockout. Uses cookie-based authentication consistent with existing admin pages.

### U.2 — User Status Management ✅
- **Status:** Complete
- **Added:** 2025-11-06
- **Implementation overview:** Operators can toggle user accounts between active and inactive states directly from the admin UI. Status changes are immediate and reflected across all authentication flows.
- **Components:**
  - Database: Uses existing `User.is_active` field
  - Service: `update_user_status()` with validation
  - UI: Toggle button on user detail page with visual feedback
- **Important:** Inactive users cannot log in but their data remains intact. Useful for temporary account suspension without deletion.

### U.3 — Enhanced Admin Navigation ✅
- **Status:** Complete
- **Added:** 2025-11-06
- **Implementation overview:** Added horizontal navigation menu to admin header with "Videos" and "Users" sections. Provides consistent navigation across all admin pages.
- **Components:**
  - Template: Updated `admin/base.html` header with navigation links
  - Styling: Matches existing dark theme with hover states
- **Important:** Navigation is visible on all admin pages. Future admin sections should be added to this menu for consistency.

### U.4 — User Deletion with Safety Guards ✅
- **Status:** Complete
- **Added:** 2025-11-06
- **Implementation overview:** Operators can delete user accounts with built-in safety mechanisms. Prevents accidental self-deletion and provides clear confirmation prompts.
- **Components:**
  - Service: `delete_user()` with `current_user_id` parameter for self-deletion check
  - Exception: `CannotDeleteCurrentUserError` raised when attempting self-deletion
  - UI: JavaScript confirmation dialog, disabled delete button for current user
- **Important:** Hard delete operation (not soft delete). Consider future migration to soft delete with audit trail for compliance needs.

### U.5 — Google OAuth Social Login 📋
- **Status:** Planned
- **Added:** 2025-11-07
- **Implementation overview:** Add Google OAuth2 as an alternative authentication method while maintaining full backward compatibility with email/password login. Users can sign in with Google or traditional credentials.
- **Components:**
  - Database: Extend `User` model with `auth_provider`, `oauth_provider_id`, `picture_url` fields
  - Migration: Make `password_hash` nullable, add OAuth tracking columns
  - Service: New `oauth.py` service for OAuth flow (state validation, token exchange, user info)
  - Service: Extend `users.py` with `get_or_create_oauth_user()` and account linking logic
  - API routes: `GET /auth/google/login`, `GET /auth/google/callback`, `GET /auth/providers`
  - Admin UI: Add "Sign in with Google" button to login page
  - Config: Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `OAUTH_STATE_SECRET`
  - Dependencies: Add `authlib>=1.3` for OAuth2/OIDC client
- **Testing:** Unit tests for OAuth service, system tests for OAuth flow with mocked Google, integration tests for user creation/linking
- **Important:** Account linking automatic when Google email matches existing email. CSRF protection via signed state parameter. Works alongside email/password (not a replacement).

## Future Off-Roadmap Candidates

### User Audit Trail
- **Status:** Proposed
- **Description:** Track all user-related actions (creation, updates, deletions, login attempts) for security and compliance.
- **Rationale:** Would support regulatory compliance and security incident investigation.

### Bulk User Operations
- **Status:** Proposed
- **Description:** Allow operators to perform batch operations (activate/deactivate multiple users, export user lists).
- **Rationale:** Improves operational efficiency for large user bases.

### User Roles & Permissions
- **Status:** Proposed
- **Description:** Implement role-based access control (RBAC) with granular permissions.
- **Rationale:** Currently all users have equal access. RBAC needed when scaling to multiple operator roles.

### User Activity Dashboard
- **Status:** Proposed
- **Description:** Show user engagement metrics, last login times, and activity summaries.
- **Rationale:** Helps operators identify inactive accounts and understand usage patterns.

### Video Redownload Workflow
- **Status:** Proposed
- **Description:** Allow operators to explicitly re-download the original YouTube source (e.g., when the cached file is corrupted or when higher quality is desired) before regenerating highlights.
- **Rationale:** Current reruns reuse the cached download/transcript for speed; building a controlled redownload flow ensures append-mode reruns remain fast while still giving operators an escape hatch when the cached artifact is invalid.
