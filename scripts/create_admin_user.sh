#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/create_admin_user.sh [--email EMAIL] [--full-name "Full Name"] [--fly] [--fly-app APP] [--fly-process-group GROUP]

Creates or updates a user record with the supplied email address and password.
Prompts interactively when values are not provided via flags.
By default the script targets the local database (using DATABASE_URL or .env).
With --fly it runs the same script inside the Fly.io app container.
When --fly is used, the script connects to the "app" process group by default; override with --fly-process-group.
USAGE
}

EMAIL=""
FULL_NAME=""
RUN_MODE="local"
FLY_APP=""
FLY_PROCESS_GROUP="app"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email)
      EMAIL="${2:-}"
      shift 2
      ;;
    --full-name)
      FULL_NAME="${2:-}"
      shift 2
      ;;
    --fly)
      RUN_MODE="fly"
      shift 1
      ;;
    --fly-app)
      RUN_MODE="fly"
      FLY_APP="${2:-}"
      shift 2
      ;;
    --fly-process-group)
      RUN_MODE="fly"
      FLY_PROCESS_GROUP="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$EMAIL" ]]; then
  read -rp "Email: " EMAIL
fi

if [[ -z "$FULL_NAME" ]]; then
  read -rp "Full name [Admin User]: " FULL_NAME
  FULL_NAME=${FULL_NAME:-Admin User}
fi

PASSWORD="${PASSWORD:-}"

export EMAIL FULL_NAME PASSWORD
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
export PROJECT_ROOT="$(pwd)"

PYTHON_SNIPPET=$(cat <<'PY'
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

project_root = Path(os.environ.get("PROJECT_ROOT", Path.cwd()))
env_file = project_root / ".env"
if env_file.exists():
    env_values = dotenv_values(env_file)
    for key, value in env_values.items():
        os.environ.setdefault(key, value or "")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    sys.stderr.write(
        "DATABASE_URL is not set. Export it or create a .env file before running this script.\n"
    )
    sys.exit(1)

email = os.environ.get("EMAIL", "").strip().lower()
full_name = os.environ.get("FULL_NAME", "").strip()
password = os.environ.get("PASSWORD", "")

if not email or "@" not in email:
    sys.stderr.write("A valid email address is required.\n")
    sys.exit(1)

from app.core.security import hash_password  # noqa: E402
from app.db.models import User  # noqa: E402


def ensure_password() -> str:
    if password:
        return password
    sys.stderr.write("PASSWORD environment variable must be set when running non-interactively.\n")
    sys.exit(1)


async def main() -> None:
    connect_args: dict[str, object] = {}
    if database_url.startswith("postgresql+asyncpg"):
        host = (urlparse(database_url).hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "postgres"}:
            connect_args["ssl"] = "require"

    local_password = ensure_password()
    engine = create_async_engine(database_url, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            user.full_name = full_name
            user.password_hash = hash_password(local_password)
            action = "updated"
        else:
            user = User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(local_password),
            )
            session.add(user)
            action = "created"

        await session.commit()
        print(f"User {action}: {user.email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
PY
)

run_local() {
  if [[ -z "$PASSWORD" ]]; then
    read -rsp "Password: " PASSWORD
    echo
    read -rsp "Confirm password: " PASSWORD_CONFIRM
    echo

    if [[ "$PASSWORD" != "$PASSWORD_CONFIRM" ]]; then
      echo "Passwords do not match. Aborting." >&2
      exit 1
    fi
  fi

  export PASSWORD
  python - <<PY
$PYTHON_SNIPPET
PY
}

run_fly() {
  if ! command -v fly >/dev/null 2>&1; then
    echo "fly CLI is required for --fly mode." >&2
    exit 1
  fi

  if [[ -z "$FLY_APP" ]]; then
    FLY_APP=$(sed -n 's/^app = "\(.*\)"/\1/p' fly.toml | head -n1)
  fi

  if [[ -z "$FLY_APP" ]]; then
    echo "Unable to determine Fly app name. Pass --fly-app APP." >&2
    exit 1
  fi

  if [[ -z "$PASSWORD" ]]; then
    read -rsp "Password to set for $EMAIL: " PASSWORD
    echo
    read -rsp "Confirm password: " PASSWORD_CONFIRM
    echo

    if [[ "$PASSWORD" != "$PASSWORD_CONFIRM" ]]; then
      echo "Passwords do not match. Aborting." >&2
      exit 1
    fi
  fi

  esc_email=$(printf '%q' "$EMAIL")
  esc_full_name=$(printf '%q' "$FULL_NAME")
  esc_password=$(printf '%q' "$PASSWORD")

  echo "Connecting to Fly app '$FLY_APP'..."
  remote_cmd=$(printf "cd /app && EMAIL=%s FULL_NAME=%s PASSWORD=%s python - <<'PY'\\n%s\\nPY\\n" "$esc_email" "$esc_full_name" "$esc_password" "$PYTHON_SNIPPET")
  remote_cmd_escaped=${remote_cmd//\'/\'\"\'\"\'}
  fly_args=(-a "$FLY_APP")
  if [[ -n "$FLY_PROCESS_GROUP" ]]; then
    fly_args+=("--process-group" "$FLY_PROCESS_GROUP")
  fi
  fly_args+=("-C" "bash -lc '$remote_cmd_escaped'")
  fly ssh console "${fly_args[@]}"
}

if [[ "$RUN_MODE" == "fly" ]]; then
  run_fly
  exit 0
fi

run_local

echo "Done."
