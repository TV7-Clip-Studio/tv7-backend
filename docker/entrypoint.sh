#!/usr/bin/env bash
set -euo pipefail

# Run migrations (only the API service will actually need this, but it's safe to run multiple times)
alembic upgrade head || true

# Execute whatever command was passed (from docker-compose command)
exec "$@"
