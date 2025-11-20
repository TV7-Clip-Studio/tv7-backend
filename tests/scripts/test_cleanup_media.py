from collections.abc import Generator
from pathlib import Path

import pytest
import scripts.cleanup_media as cleanup

pytestmark = pytest.mark.no_db_override


@pytest.fixture(autouse=True)
def configure_app_database() -> Generator[None, None, None]:  # type: ignore[invalid-name]
    yield


@pytest.fixture
def media_layout(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    (media / "videos" / "1").mkdir(parents=True)
    (media / "videos" / "999").mkdir(parents=True)
    (media / "clips" / "10").mkdir(parents=True)
    (media / "clips" / "999").mkdir(parents=True)
    return media


@pytest.mark.asyncio
@pytest.mark.no_db_override
async def test_find_orphans(monkeypatch: pytest.MonkeyPatch, media_layout: Path) -> None:
    async def fake_fetch() -> tuple[set[int], set[int]]:
        return {1}, {10}

    monkeypatch.setattr(cleanup, "_fetch_existing_ids", fake_fetch)

    report = await cleanup.find_orphans(media_layout)
    assert {p.name for p in report.video_dirs} == {"999"}
    assert {p.name for p in report.clip_dirs} == {"999"}


@pytest.mark.no_db_override
def test_main_delete(monkeypatch: pytest.MonkeyPatch, media_layout: Path) -> None:
    async def fake_fetch() -> tuple[set[int], set[int]]:
        return {1}, {10}

    monkeypatch.setattr(cleanup, "_fetch_existing_ids", fake_fetch)

    cleanup.main(["--media-dir", str(media_layout), "--delete"])

    assert not (media_layout / "videos" / "999").exists()
    assert not (media_layout / "clips" / "999").exists()
