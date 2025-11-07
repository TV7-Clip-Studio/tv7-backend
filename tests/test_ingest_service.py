from __future__ import annotations

import pytest
from dramatiq.brokers.stub import StubBroker

from app.services import ingest
from app.services import tasks as tasks_module


@pytest.mark.anyio
async def test_enqueue_video_runs_inline_when_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_broker = StubBroker()
    monkeypatch.setattr(ingest, "get_broker", lambda: stub_broker, raising=False)

    inline_calls: list[int] = []

    async def fake_run(video_id: int) -> None:
        inline_calls.append(video_id)

    send_calls: list[int] = []

    def fake_send(video_id: int) -> None:
        send_calls.append(video_id)

    monkeypatch.setattr(tasks_module, "run_pipeline_inline", fake_run, raising=False)
    monkeypatch.setattr(ingest, "run_pipeline_inline", fake_run, raising=False)
    monkeypatch.setattr(ingest.process_video, "send", fake_send, raising=False)

    await ingest.enqueue_video(42, source_url="https://youtu.be/test")

    assert inline_calls == [42]
    assert send_calls == []


@pytest.mark.anyio
async def test_enqueue_video_sends_to_broker_when_not_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyBroker:  # pragma: no cover - helper
        pass

    monkeypatch.setattr(ingest, "get_broker", lambda: DummyBroker(), raising=False)

    inline_calls: list[int] = []

    async def fake_run(video_id: int) -> None:
        inline_calls.append(video_id)

    send_calls: list[int] = []

    def fake_send(video_id: int) -> None:
        send_calls.append(video_id)

    monkeypatch.setattr(tasks_module, "run_pipeline_inline", fake_run, raising=False)
    monkeypatch.setattr(ingest, "run_pipeline_inline", fake_run, raising=False)
    monkeypatch.setattr(ingest.process_video, "send", fake_send, raising=False)

    await ingest.enqueue_video(7, source_url="https://youtu.be/demo")

    assert inline_calls == []
    assert send_calls == [7]
