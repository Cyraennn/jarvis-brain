"""Tek seferde onay: baska cihazda yanitlanan onay bilgisayarda tekrar sorulmaz."""
from __future__ import annotations

import asyncio
import threading
import time

from client.core import JarvisClient, _accepts_cancel


def _client_with_outbox() -> tuple[JarvisClient, list[dict]]:
    client = JarvisClient("ws://x/ws", "x")
    sent: list[dict] = []

    async def fake_send(msg: dict) -> None:
        sent.append(msg)

    client.send = fake_send  # type: ignore[method-assign]
    return client, sent


def test_accepts_cancel_detects_signature():
    assert _accepts_cancel(lambda p, s, c: True)
    assert _accepts_cancel(lambda p, s, c=None: True)
    assert not _accepts_cancel(lambda p, s: True)


def test_remote_resolution_closes_local_dialog_without_response():
    client, sent = _client_with_outbox()
    seen_cancel: list[threading.Event] = []

    def handler(prompt: str, source: str, cancel: threading.Event) -> bool:
        seen_cancel.append(cancel)
        assert cancel.wait(5), "iptal sinyali gelmedi"
        return False  # pencere kapatildi; sonuc kullanilmamali

    async def scenario() -> None:
        task = client._handle({"type": "confirm_request", "id": "abc", "prompt": "Kapat?", "source": "engine"})
        await asyncio.sleep(0.1)
        client._handle({"type": "confirm_resolved", "id": "abc", "approved": True})
        await asyncio.wait_for(task, 5)

    client.set_confirm_handler(handler)
    asyncio.run(scenario())
    assert seen_cancel and seen_cancel[0].is_set()
    assert not any(m.get("type") == "confirm_response" for m in sent)
    assert client._open_confirms == {}


def test_legacy_two_arg_handler_still_answers():
    client, sent = _client_with_outbox()
    client.set_confirm_handler(lambda prompt, source: True)

    async def scenario() -> None:
        await client._handle({"type": "confirm_request", "id": "x1", "prompt": "?", "source": "engine"})

    asyncio.run(scenario())
    assert sent == [{"type": "confirm_response", "id": "x1", "approved": True}]


def test_qt_observer_confirm_stops_on_cancel():
    from ui.qt_observer import QtEngineObserver

    obs = QtEngineObserver()
    captured = []
    obs._emit = lambda name, *args: captured.append(args[0])  # type: ignore[method-assign]
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    t0 = time.monotonic()
    assert obs.confirm("Kapat?", cancel=cancel) is False
    assert time.monotonic() - t0 < 2
    req = captured[0]
    assert req.expired and req.remote_resolved
