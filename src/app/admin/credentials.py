from __future__ import annotations

import secrets
import shutil
import string
import subprocess  # nosec B404
from collections.abc import Iterable
from pathlib import Path

DEFAULT_PASSWORD_LENGTH = 24
MIN_PASSWORD_LENGTH = 12
_ALPHABET = string.ascii_letters + string.digits


def generate_credentials(
    username: str | None = None,
    *,
    password_length: int = DEFAULT_PASSWORD_LENGTH,
) -> tuple[str, str]:
    """Return a `(username, password)` tuple suitable for admin authentication."""
    if password_length < MIN_PASSWORD_LENGTH:
        msg = "Admin passwords must be at least 12 characters long"
        raise ValueError(msg)

    safe_username = username or "admin"
    password = "".join(secrets.choice(_ALPHABET) for _ in range(password_length))
    return safe_username, password


def update_env_file(path: Path, *, username: str, password: str) -> None:
    """Insert or replace ADMIN credentials inside a .env-style file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text().splitlines()

    rendered = _render_env(existing_lines, username=username, password=password)
    path.write_text("\n".join(rendered) + "\n")


def _render_env(
    lines: Iterable[str],
    *,
    username: str,
    password: str,
) -> list[str]:
    """Return updated .env lines with ADMIN_USERNAME/PASSWORD replaced or appended."""
    updated: list[str] = []
    seen_username = False
    seen_password = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            updated.append(line)
            continue

        key, _, value = line.partition("=")
        key = key.strip()

        if key == "ADMIN_USERNAME":
            updated.append(f"ADMIN_USERNAME={username}")
            seen_username = True
        elif key == "ADMIN_PASSWORD":
            updated.append(f"ADMIN_PASSWORD={password}")
            seen_password = True
        else:
            updated.append(line)

    if not seen_username:
        updated.append(f"ADMIN_USERNAME={username}")
    if not seen_password:
        updated.append(f"ADMIN_PASSWORD={password}")

    return updated


def sync_fly_secrets(
    app_name: str,
    username: str,
    password: str,
    *,
    cli_path: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """
    Push ADMIN credentials to Fly.io via `fly secrets set`.

    Parameters
    ----------
    app_name:
        Fly app identifier (e.g., forgotten-app).
    username/password:
        Credentials to store.
    cli_path:
        Optional explicit path to the Fly CLI. When omitted we auto-discover
        `fly` or `flyctl` on PATH.
    check:
        When True (default) raise CalledProcessError for non-zero exit status.
    """
    resolved_cli = cli_path or shutil.which("fly") or shutil.which("flyctl")
    if not resolved_cli:
        msg = "Fly CLI not found (expected `fly` or `flyctl` on PATH)"
        raise RuntimeError(msg)

    command = [
        resolved_cli,
        "secrets",
        "set",
        f"ADMIN_USERNAME={username}",
        f"ADMIN_PASSWORD={password}",
        "-a",
        app_name,
    ]
    return subprocess.run(command, check=check)  # nosec B603
