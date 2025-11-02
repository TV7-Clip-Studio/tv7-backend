#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.admin.credentials import (
    DEFAULT_PASSWORD_LENGTH,
    generate_credentials,
    sync_fly_secrets,
    update_env_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate credentials for the FastAPI admin dashboard.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--username",
        help="Username for the admin dashboard (defaults to ADMIN_USERNAME env var or 'admin').",
    )
    parser.add_argument(
        "--password-length",
        type=int,
        default=DEFAULT_PASSWORD_LENGTH,
        help="Length of the generated password (min 12).",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=".env",
        help="Path to the env file to update.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist the credentials to the env file. Without this flag we only print them.",
    )
    parser.add_argument(
        "--fly-app",
        help="Fly app name (defaults to FLY_APP env variable).",
    )
    parser.add_argument(
        "--fly-sync",
        action="store_true",
        help="Push credentials to Fly secrets via `fly secrets set`. Requires Fly CLI login.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    default_username = os.getenv("ADMIN_USERNAME")
    username_override = args.username or default_username
    username, password = generate_credentials(
        username_override, password_length=args.password_length
    )

    env_path = Path(args.env_file).expanduser()
    wrote = False
    if args.write:
        update_env_file(env_path, username=username, password=password)
        wrote = True

    print("\nAdmin credentials")
    print("-----------------")
    print(f" username: {username}")
    print(f" password: {password}")
    print("")
    if wrote:
        print(f"Updated {env_path}")
    else:
        print("Not written to disk. Re-run with --write to update your env file.")
    synced = False
    if args.fly_sync:
        fly_app = args.fly_app or os.getenv("FLY_APP")
        if not fly_app:
            print("[warn] Fly sync requested but no app name provided (--fly-app or FLY_APP env).")
        else:
            try:
                sync_fly_secrets(fly_app, username, password)
                synced = True
                print(f"Fly secrets updated for app '{fly_app}'.")
            except RuntimeError as exc:  # CLI missing
                print(f"[warn] {exc}")
            except Exception as exc:  # pragma: no cover - surface any CLI failure
                print(f"[warn] Failed to sync Fly secrets: {exc}")
                if wrote:
                    print("Credentials still updated locally; retry fly sync manually.")
    if not synced:
        print("Remember to set these values in Fly secrets / CI before deploying.")


if __name__ == "__main__":
    main()
