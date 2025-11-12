from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.admin import routes


@pytest.mark.anyio
async def test_delete_media_helper_offloads_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def fake_run_sync(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        called["func"] = func
        called["args"] = args
        called["kwargs"] = dict(kwargs)
        kwargs.pop("cancellable", None)
        return func(*args, **kwargs)

    def fake_delete(video_id: int, clip_ids: list[int]) -> None:
        called["invoked"] = (video_id, clip_ids)

    monkeypatch.setattr("app.admin.routes.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr("app.admin.routes.delete_video_media", fake_delete)

    await routes._delete_video_media_async(123, [1, 2, 3])

    assert called["func"] is fake_delete
    assert called["args"] == (123, [1, 2, 3])
    assert called["kwargs"] == {"cancellable": False}
    assert called["invoked"] == (123, [1, 2, 3])
