from collections.abc import Generator
from pathlib import Path

import pytest

from app.core import config as config_module
from app.services import storage as storage_module
from app.services.storage import delete_video_media

pytestmark = pytest.mark.no_db_override


@pytest.fixture(autouse=True)
def configure_app_database() -> Generator[None, None, None]:  # type: ignore[invalid-name]
    yield


@pytest.mark.no_db_override
def test_delete_video_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[Path] = []

    def fake_remove(path: Path) -> None:
        called.append(path)

    expected_dir = str(tmp_path)
    monkeypatch.setattr(config_module.settings, "MEDIA_STORAGE_DIR", expected_dir)
    monkeypatch.setattr(storage_module.settings, "MEDIA_STORAGE_DIR", expected_dir)
    assert expected_dir == config_module.settings.MEDIA_STORAGE_DIR
    assert expected_dir == storage_module.settings.MEDIA_STORAGE_DIR
    monkeypatch.setattr("app.services.storage.remove_media_path", fake_remove)

    delete_video_media(123, [1, 2, 999])

    expected = {
        tmp_path / "videos" / "123",
        tmp_path / "clips" / "1",
        tmp_path / "clips" / "2",
        tmp_path / "clips" / "999",
    }
    assert set(called) == expected
