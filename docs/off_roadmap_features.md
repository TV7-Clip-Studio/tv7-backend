# Off-Roadmap Features

> Features, improvements, and changes implemented outside the main roadmap phases. These represent tactical improvements, branding updates, and user-requested enhancements that emerged during development.

## Completed Features

### 0.14 — Application Rebranding (✅ Completed)
- Rebrand application from "Shorts Factory" / "Forgotten App" to **TV7** across all user-facing surfaces.
- Update `APP_NAME` configuration, admin UI templates, and all documentation.
- Keep internal deployment names (`forgotten-app` in Fly.io) unchanged to avoid infrastructure disruption.

### 0.15 — User Profile Management (✅ Completed)
- Add `/admin/profile` page for operators to view and edit their account information.
- Implement `GET /api/v1/users/me` and `PATCH /api/v1/users/me` endpoints for profile access and updates.
- Allow users to update full name, email, and password with proper validation.
- Add navigation link to profile in admin dashboard header.

## Planned Features

### 0.16 — User-Scoped Video Ownership (Queued)
- Add `user_id` foreign key to `Video` model to associate videos with creators.
- Filter video lists and details by authenticated user.
- Update admin dashboard to show only user's own videos.
- Ensure proper authorization checks across all video endpoints.

## Future Considerations

### Potential Enhancements
- User avatar uploads and profile pictures.
- Multi-user collaboration (sharing videos between users).
- Role-based access control (admin, operator, viewer roles).
- Activity logs and audit trails.
- Email verification and password reset flows.
- Two-factor authentication.
- User preferences and settings (timezone, notifications).
- Dark mode toggle in admin UI.
- Internationalization (i18n) support.

## Maintenance Notes

- This document tracks features developed outside the main `roadmap.md` scope.
- When a feature is completed, update its status to ✅ and document its implementation date.
- Features may be promoted to the main roadmap if they inspire related work or become part of a larger initiative.
- Consult `off_roadmap_features_rationale.md` for detailed implementation notes and decision context.
