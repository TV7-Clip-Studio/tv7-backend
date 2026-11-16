from __future__ import annotations

import tomllib
from pathlib import Path

from app.core.config import Settings


def test_settings_accept_release_debug_mode() -> None:
    settings = Settings(DEBUG="release")

    assert settings.DEBUG is False


def test_settings_accept_dev_debug_mode() -> None:
    settings = Settings(DEBUG="dev")

    assert settings.DEBUG is True


def test_runtime_version_matches_project_metadata() -> None:
    metadata = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with metadata.open("rb") as project:
        assert (
            Settings.model_fields["VERSION"].default == tomllib.load(project)["project"]["version"]
        )
