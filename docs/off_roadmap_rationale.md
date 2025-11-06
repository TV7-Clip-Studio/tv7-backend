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
