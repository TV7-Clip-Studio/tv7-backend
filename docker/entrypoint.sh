#!/usr/bin/env bash
set -euo pipefail

# Decode base64-encoded YouTube cookies if present
if [ -n "${YOUTUBE_COOKIES_B64:-}" ]; then
  echo "$YOUTUBE_COOKIES_B64" | base64 -d > /app/youtube_cookies.txt
  export YOUTUBE_COOKIES_FILE="/app/youtube_cookies.txt"
  echo "Decoded YouTube cookies from YOUTUBE_COOKIES_B64"
fi

# Run migrations (only the API service will actually need this, but it's safe to run multiple times)
alembic upgrade head || true

# Execute whatever command was passed (from docker-compose command)
exec "$@"
