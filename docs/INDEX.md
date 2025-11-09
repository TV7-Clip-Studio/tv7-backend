# TV7 Documentation Index

> Central hub for navigating all project documentation. Start here to find the right guide for your needs.

## Quick Navigation

### Getting Started
- **[README.md](../README.md)** - Quickstart guide, setup instructions, and deployment basics
- **[architecture.md](core/architecture.md)** - System design, domain model, API surface, and layering

### Setup & Configuration
- **[neon_postgres.md](setup/neon_postgres.md)** - Database operations and maintenance
- **[youtube_cookies_setup.md](setup/youtube_cookies_setup.md)** - YouTube authentication using browser cookies
- **[youtube_oauth_connector.md](setup/youtube_oauth_connector.md)** - YouTube OAuth connector implementation plan

### For Operators
- **[user_flows.md](guides/user_flows.md)** - Admin dashboard workflows and user journeys

### For Developers
- **[tech_stack.md](core/tech_stack.md)** - Complete technology reference and library inventory
- **[testing.md](guides/testing.md)** - Test strategy (unit, system, integration)
- **[agent_best_practices.md](core/agent_best_practices.md)** - Development workflow and coding standards

### Planning & Features
- **[roadmap.md](roadmap/roadmap.md)** - Feature roadmap with completion status
- **[roadmap_rationale.md](roadmap/roadmap_rationale.md)** - Detailed reasoning for roadmap decisions
- **[off_roadmap.md](roadmap/off_roadmap.md)** - Features built outside the main roadmap
- **[off_roadmap_rationale.md](roadmap/off_roadmap_rationale.md)** - Why and how off-roadmap features were implemented

---

## Document Summaries

### [README.md](../README.md)
**When to read:** First time setup, deploying to production, running tests
**Covers:** Docker Compose setup, environment variables, authentication, admin credentials, Fly.io deployment, testing commands

### Core Documentation

#### [architecture.md](core/architecture.md)
**When to read:** Understanding system design, planning new features, onboarding to codebase
**Covers:** System purpose, domain model (Video/Clip/User), processing pipeline, API endpoints, layering (router→service→repository)

#### [tech_stack.md](core/tech_stack.md)
**When to read:** Need library version info, understanding technology choices, debugging dependencies
**Covers:** Runtime stack, database drivers, background processing, authentication, AI/LLM, dev tools, infrastructure

#### [agent_best_practices.md](core/agent_best_practices.md)
**When to read:** Before contributing code, during code review
**Covers:** Development workflow, coding standards, service layer patterns, pipeline guardrails, observability

### Setup & Configuration

#### [neon_postgres.md](setup/neon_postgres.md)
**When to read:** Provisioning databases, rotating credentials, troubleshooting connection issues
**Covers:** Neon setup, connection strings (pooler vs direct), migrations, branching, secrets management

#### [youtube_cookies_setup.md](setup/youtube_cookies_setup.md)
**When to read:** Setting up YouTube authentication for local or production deployment
**Covers:** Exporting browser cookies, Docker setup, Fly.io deployment, security considerations, troubleshooting

#### [youtube_oauth_connector.md](setup/youtube_oauth_connector.md)
**When to read:** Planning YouTube OAuth connector implementation
**Covers:** OAuth 2.0 flow, database schema, token refresh strategy, implementation phases, security best practices

### User Guides

#### [user_flows.md](guides/user_flows.md)
**When to read:** Understanding how operators and API clients use the system
**Covers:** Admin dashboard workflows, API authentication flows, background processing lifecycle, error handling

#### [testing.md](guides/testing.md)
**When to read:** Writing new tests, understanding test layers, debugging test failures
**Covers:** Unit vs system vs integration tests, where to place new tests, test fixture usage

### Roadmap & Planning

#### [roadmap.md](roadmap/roadmap.md) + [roadmap_rationale.md](roadmap/roadmap_rationale.md)
**When to read:** Planning work, understanding feature priorities, checking implementation status
**Covers:** Phased feature plan (Phase 0: Foundation, Phase 1: Shorts MVP, Phase 2: Polish, Phase 3: Growth), detailed "why" and "how" for each milestone

#### [off_roadmap.md](roadmap/off_roadmap.md) + [off_roadmap_rationale.md](roadmap/off_roadmap_rationale.md)
**When to read:** Understanding features outside main roadmap, justifying extra work
**Covers:** User management dashboard, status controls, navigation enhancements, deletion guards, implementation decisions

---

## By Reader Persona

### I'm an **Operator** (running the service)
1. Start: [README.md](../README.md) - Get the system running
2. Learn: [user_flows.md](guides/user_flows.md) - How to use admin dashboard
3. Configure: [youtube_cookies_setup.md](setup/youtube_cookies_setup.md) - YouTube authentication
4. Maintain: [neon_postgres.md](setup/neon_postgres.md) - Database operations

### I'm a **Developer** (contributing code)
1. Start: [README.md](../README.md) - Setup dev environment
2. Understand: [architecture.md](core/architecture.md) - System design
3. Code: [agent_best_practices.md](core/agent_best_practices.md) - Standards and patterns
4. Test: [testing.md](guides/testing.md) - Test strategy
5. Reference: [tech_stack.md](core/tech_stack.md) - Library versions and tools

### I'm a **Contributor** (planning features)
1. Current state: [roadmap.md](roadmap/roadmap.md) - What's planned
2. Rationale: [roadmap_rationale.md](roadmap/roadmap_rationale.md) - Why and how
3. Off-plan work: [off_roadmap.md](roadmap/off_roadmap.md) + [off_roadmap_rationale.md](roadmap/off_roadmap_rationale.md)
4. Architecture: [architecture.md](core/architecture.md) - Where new features fit

---

## Document Maintenance

- Keep this index updated when adding new documentation
- Link to new docs from relevant sections above
- Update summaries when document scope changes
- Date major doc revisions in commit messages
