"""Istemci cekirdegi: geri cekilme, izin listesi, masaustu handler kaydi, yapilandirma."""
from __future__ import annotations

import sys

import pytest

from client.core import JarvisClient, backoff_delay
from remote.protocol import CLIENT_FUNCTIONS, action_timeout, short_name


def test_backoff_grows_and_is_capped():
    delays = [backoff_delay(n, base=1.0, cap=30.0) for n in range(1, 10)]
    assert 1.0 <= delays[0] <= 1.25
    assert 4.0 <= delays[2] <= 5.0
    assert all(d <= 30.0 * 1.25 for d in delays)
    assert delays[-1] >= 30.0


def test_resolve_only_allowlisted():
    from client.desktop import resolve

    assert resolve("os.system") is None                       # izin listesinde yok -> ASLA
    assert resolve("subprocess.run") is None
    assert resolve("tools.basic_tools.read_text_file") is not None


@pytest.mark.skipif(sys.platform != "win32", reason="masaustu araclari Windows'a ozel")
def test_desktop_registers_every_allowlisted_action():
    from client.config import ClientConfig
    from client.desktop import register_desktop_handlers

    cfg = ClientConfig(server_host="100.1.2.3", server_port=8765, token="x", name="pc", kind="desktop",
                       audio=False, audio_port=8771, audio_token="x", desktop=True, vision=False,
                       confirm_mode="deny", web_port=8770, web_token="w")
    client = JarvisClient("ws://x/ws", "x")
    registered = register_desktop_handlers(client, cfg)
    assert set(registered) == set(CLIENT_FUNCTIONS)
    assert set(client.actions) == set(CLIENT_FUNCTIONS)


def test_protocol_helpers():
    assert short_name("tools.app_launcher.open_application") == "open_application"
    assert action_timeout("tools.vision_tools.record_screen") > 300
    assert action_timeout("bilinmeyen.eylem") == 60.0
    # her izinli ad gercek bir fonksiyona isaret etmeli (yazim hatasi olmasin)
    from client.desktop import resolve

    missing = [a for a in CLIENT_FUNCTIONS if resolve(a) is None]
    assert missing == []


def test_client_config_requires_host_and_token(tmp_path, monkeypatch):
    from client.config import load_client_config

    env = tmp_path / ".env"
    env.write_text("JARVIS_SERVER_HOST=\nJARVIS_TOKEN=\n", encoding="utf-8")
    monkeypatch.delenv("JARVIS_SERVER_HOST", raising=False)
    monkeypatch.delenv("JARVIS_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        load_client_config(env)
    env.write_text("JARVIS_SERVER_HOST=jarvis-vps\nJARVIS_TOKEN=abc\nJARVIS_CLIENT_NAME=ev-pc\n",
                   encoding="utf-8")
    cfg = load_client_config(env)
    assert cfg.ws_url == "ws://jarvis-vps:8765/ws" and cfg.name == "ev-pc"
    assert cfg.audio_token == "abc" and "key=abc" in cfg.audio_url    # ayri ses token'i yoksa ortak


def test_qt_bridge_maps_server_events_to_observers():
    import asyncio

    from client.qt_bridge import bind_observers

    class Rec:
        def __init__(self) -> None:
            self.calls: list = []

        def __getattr__(self, name):  # noqa: ANN001, ANN204
            return lambda *a: self.calls.append((name, a)) or True

    eng, orch = Rec(), Rec()
    client = JarvisClient("ws://x/ws", "t")
    bind_observers(client, eng, orch)

    async def fire():
        await client._emit("snapshot", {"connection": "active", "engine_state": "idle",
                                        "agents": {"a": {"name": "a", "title": "A", "department": "okul",
                                                         "autonomy": "fully_autonomous"}}})
        await client._emit("transcript_partial", {"who": "jarvis", "text": "Mer"})
        await client._emit("transcript", {"who": "user", "text": "selam"})
        await client._emit("tool_result", {"name": "calculate", "ok": True, "detail": "84"})
        await client._emit("task", {"id": "t1", "agent": "a", "status": "running"})
        await client._emit("external_typing", True)

    asyncio.run(fire())
    names = [c[0] for c in eng.calls]
    assert ("on_connection", ("active",)) in eng.calls and "on_state" in names
    assert ("on_assistant_transcript", ("Mer", False)) in eng.calls
    assert ("on_user_transcript", ("selam", True)) in eng.calls
    assert ("on_tool_result", ("calculate", True, "84")) in eng.calls
    assert ("on_external_typing", (True,)) in eng.calls
    loaded = [c for c in orch.calls if c[0] == "on_agents_loaded"][0][1][0]
    assert loaded[0].department.value == "okul"                    # HUD'un bekledigi sekil
    from agents.qt_observer import QtOrchestratorObserver

    QtOrchestratorObserver().on_agents_loaded(loaded)               # hashlenebilir olmali (gercek gozlemci)
    task = [c for c in orch.calls if c[0] == "on_task"][0][1][0]
    assert task.status == "running" and task.agent == "a"
    assert client._confirm is not None                              # HUD onay diyalogu bagli


def test_decorator_registration():
    client = JarvisClient("ws://x/ws", "t", name="robot-1", kind="robot")

    @client.action("robot.move")
    def move(direction: str, cm: int = 10) -> dict:
        return {"moved": direction, "cm": cm}

    assert client.actions == ["robot.move"]
