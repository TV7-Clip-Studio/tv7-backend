from __future__ import annotations

from app.core.config import Settings


def test_settings_accept_release_debug_mode() -> None:
    settings = Settings(DEBUG="release")

    assert settings.DEBUG is False


def test_settings_accept_dev_debug_mode() -> None:
    settings = Settings(DEBUG="dev")

    assert settings.DEBUG is True
