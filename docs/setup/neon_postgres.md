# Neon Postgres Runbook

This guide explains how we provision and operate our Neon-hosted Postgres instances alongside Fly.io deployments. Local development continues to use Docker Postgres (or SQLite for tests); Neon credentials are only injected into Fly and other hosted environments.

## 1. Provision Neon
1. Create a project in the region closest to your Fly deployment. Leave **Neon Auth disabled**—authentication stays within AgentForge.
2. Neon creates:
   - A **pooler endpoint** (`…-pooler…`) that fronts PgBouncer, ideal for the running API.
   - A **direct compute endpoint** (`…neon.tech`) for long-lived migrations and maintenance.

## 2. Map Connection Strings
- **Runtime / async driver (FastAPI):**
  ```
  DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@ep-…-pooler.REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require
  ```
- **Admin / sync driver (Alembic, scripts):**
  ```
  DATABASE_ADMIN_URL=postgresql+psycopg://USER:PASSWORD@ep-….REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require
  ```

Keep these values out of git. For local development, `.env` should point to your local Postgres (`postgresql+asyncpg://postgres:postgres@localhost:5432/appdb`) and mirror the admin DSN with `+psycopg`.

## 3. Configure Environments
- **Local:** `.env` contains the local Postgres URLs. If you need to test against Neon locally, export the Neon URLs temporarily—do not commit them.
- **Fly.io:** never edit `.env` in the image. Use secrets:
  ```bash
  fly secrets set DATABASE_URL="postgresql+asyncpg://..."
  fly secrets set DATABASE_ADMIN_URL="postgresql+psycopg://..."
  ```
  The app reads these at runtime; the admin DSN is only used for migrations.

## 4. Migrations & Maintenance
- Apply migrations locally against Neon when needed:
  ```bash
  DATABASE_ADMIN_URL="postgresql+psycopg://..." alembic upgrade head
  ```
- On Fly:
  ```bash
  fly ssh console -C 'DATABASE_ADMIN_URL="postgresql+psycopg://..." alembic upgrade head'
  ```
- For read-only testing or manual tweaks, use `psql` with the pooler DSN; stick to the direct compute DSN for DDL-heavy operations.

## 5. Branching & Review Environments
- Neon supports branches. Create a branch for experiments, copy its DSNs, and override `DATABASE_URL` / `DATABASE_ADMIN_URL` in the environment you’re testing. Tear the branch down after use to avoid drift.

## 6. Secrets Hygiene
- Rotate the Neon password after sharing access.
- Update Fly secrets and any other hosting environment simultaneously.
- Document rotations in the infrastructure changelog.

## 7. Troubleshooting
- **TLS errors:** ensure `sslmode=require` and `channel_binding=require` stay in the URL as provided by Neon.
- **Connection limits:** the pooler caps connections per compute size. For load tests, consider scaling the compute unit or using a dedicated branch.
- **Idle timeouts:** Neon auto-scales to zero when idle; the first connection after inactivity may take a second to warm up—expected behaviour.
