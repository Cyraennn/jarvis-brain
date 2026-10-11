"""Internet yoklamasi: sonuc, onbellek, durum degisimi logu."""
from __future__ import annotations

import asyncio

import pytest

from core import connectivity


class _Writer:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


@pytest.fixture
def probe(monkeypatch):
    """open_connection taklidi: state["up"] False ise DNS hatasi gibi OSError."""
    state = {"up": True, "calls": 0}

    async def fake_open(host, port):  # noqa: ANN001
        state["calls"] += 1
        if not state["up"]:
            raise OSError(11001, "getaddrinfo failed")
        return None, _Writer()

    monkeypatch.setattr(connectivity.asyncio, "open_connection", fake_open)
    monkeypatch.setattr(connectivity, "_state", None)
    monkeypatch.setattr(connectivity, "_checked_at", 0.0)
    return state


def test_online_and_offline(probe):
    assert asyncio.run(connectivity.is_online()) is True
    probe["up"] = False
    assert asyncio.run(connectivity.is_online(force=True)) is False


def test_result_is_cached(probe):
    asyncio.run(connectivity.is_online())
    probe["up"] = False
    assert asyncio.run(connectivity.is_online()) is True  # 15 sn onbellek
    assert probe["calls"] == 1


def test_offline_cache_shorter(probe, monkeypatch):
    probe["up"] = False
    asyncio.run(connectivity.is_online())
    probe["up"] = True
    monkeypatch.setattr(connectivity, "_checked_at", connectivity._checked_at - 6)
    assert asyncio.run(connectivity.is_online()) is True  # 5 sn sonra yeniden yoklar


def test_state_change_logged_once(probe):
    from loguru import logger

    messages: list[str] = []
    sink = logger.add(messages.append, level="INFO", format="{message}")
    try:
        probe["up"] = False
        asyncio.run(connectivity.is_online(force=True))
        asyncio.run(connectivity.is_online(force=True))
        probe["up"] = True
        asyncio.run(connectivity.is_online(force=True))
    finally:
        logger.remove(sink)
    assert sum("CEVRIMDISI" in m for m in messages) == 1
    assert sum("geri geldi" in m for m in messages) == 1
