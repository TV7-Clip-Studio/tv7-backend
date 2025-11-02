from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.admin.credentials import (
    DEFAULT_PASSWORD_LENGTH,
    generate_credentials,
    sync_fly_secrets,
    update_env_file,
)


def test_generate_credentials_defaults_length_and_username() -> None:
    username, password = generate_credentials()
    assert username == "admin"
    assert len(password) == DEFAULT_PASSWORD_LENGTH
    assert password.isalnum()


def test_generate_credentials_custom_username_and_length() -> None:
    username, password = generate_credentials("operator", password_length=32)
    assert username == "operator"
    assert len(password) == 32


def test_generate_credentials_reject_short_passwords() -> None:
    with pytest.raises(ValueError):
        generate_credentials(password_length=8)


def test_update_env_file_creates_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    update_env_file(env_file, username="admin", password="secret")

    content = env_file.read_text().strip().splitlines()
    assert "ADMIN_USERNAME=admin" in content
    assert "ADMIN_PASSWORD=secret" in content


def test_update_env_file_overrides_existing_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        os.linesep.join(
            [
                "APP_NAME=Forgotten App",
                "# comment should remain",
                "ADMIN_USERNAME=old",
                "ADMIN_PASSWORD=old-pass",
                "",
            ]
        )
    )

    update_env_file(env_file, username="new-admin", password="new-secret")
    content = env_file.read_text().splitlines()

    assert "ADMIN_USERNAME=new-admin" in content
    assert "ADMIN_PASSWORD=new-secret" in content
    assert content[0] == "APP_NAME=Forgotten App"
    assert "# comment should remain" in content


def test_sync_fly_secrets_uses_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "fly":
            return "/usr/local/bin/fly"
        return None

    def fake_run(cmd: list[str], *_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("app.admin.credentials.shutil.which", fake_which)
    monkeypatch.setattr("app.admin.credentials.subprocess.run", fake_run)

    result = sync_fly_secrets("my-app", "admin", "secret")
    assert isinstance(result, subprocess.CompletedProcess)
    assert calls == [
        [
            "/usr/local/bin/fly",
            "secrets",
            "set",
            "ADMIN_USERNAME=admin",
            "ADMIN_PASSWORD=secret",
            "-a",
            "my-app",
        ]
    ]


def test_sync_fly_secrets_errors_when_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.admin.credentials.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError):
        sync_fly_secrets("app", "user", "pass")
