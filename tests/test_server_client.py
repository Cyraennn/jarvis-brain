"""Sunucu (FastAPI) + istemci cekirdegi: GERCEK uvicorn + GERCEK JarvisClient, tek dongude.

Gemini'ye cikilmaz: motor sahte (FakeEngine), model testi kapali.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from client.core import JarvisClient
from config.settings import Settings
from server.app import create_app
from server.config import ServerConfig, server_settings
from server.runtime import JarvisRuntime
from server.telegram import TelegramNotifier
from web.web_observer import WebEngineObserver

TOKEN = "t" * 40


class FakeEngine:
    """send_user_text -> kisa sure sonra asistan transkripti uretir (arac cagrisi dahil)."""

    def __init__(self, broker) -> None:  # noqa: ANN001
        self.broker = broker
        self.session_active = True
        self.mic_muted = False
        self.output_muted = False
        self.screen_streaming = False
        self.webcam_streaming = False
        self.wake_word_enabled = False
        self.sent: list[str] = []

    async def send_user_text(self, text: str) -> bool:
        self.sent.append(text)

        async def answer() -> None:
            await asyncio.sleep(0.05)
            self.broker.on_assistant_transcript("Bakiyorum.", True)
            self.broker.on_tool_call(["calculate"])
            await asyncio.sleep(0.2)
            self.broker.on_tool_result("calculate")
            self.broker.on_assistant_transcript("Sonu", False)
            self.broker.on_assistant_transcript("Sonuc 84.", True)

        asyncio.get_running_loop().create_task(answer())
        return True

    def set_mic_muted(self, muted: bool) -> None:
        self.mic_muted = muted

    def set_output_muted(self, muted: bool) -> None:
        self.output_muted = muted

    def set_wake_word_enabled(self, enabled: bool) -> None:
        self.wake_word_enabled = enabled

    def set_screen_streaming(self, on: bool) -> None:
        self.screen_streaming = on

    def set_webcam_streaming(self, on: bool) -> None:
        self.webcam_streaming = on


def _cfg(port: int = 0) -> ServerConfig:
    return ServerConfig(token=TOKEN, bind="127.0.0.1", port=port, command_timeout=5.0,
                        log_path=Path("unused.jsonl"), telegram_bot_token="", telegram_chat_id="",
                        probe_models=False)


def _runtime() -> JarvisRuntime:
    settings = server_settings(Settings(gemini_api_key="test"), _cfg())
    rt = JarvisRuntime(settings, _cfg(), TelegramNotifier())
    rt.broker.settle_s = 0.3
    engine = FakeEngine(rt.broker)
    rt.engine = engine
    rt.broker.engine = engine
    return rt


async def _start(rt: JarvisRuntime):
    rt.hub.attach_loop(asyncio.get_running_loop())
    server = uvicorn.Server(uvicorn.Config(create_app(rt), host="127.0.0.1", port=0, log_config=None,
                                           lifespan="off"))
    serve = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    pump = asyncio.create_task(rt.hub.pump_bus(rt.stop_event, interval=0.02))
    return server, serve, pump, port


async def _stop(rt, server, serve, pump) -> None:  # noqa: ANN001
    rt.request_stop()
    server.should_exit = True
    await asyncio.wait_for(serve, 5)
    pump.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pump


def _http(port: int, path: str, *, token: str | None = TOKEN, body: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"X-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# ----------------------------------------------------------------- HTTP
def test_http_auth_health_and_command():
    async def scenario():
        rt = _runtime()
        server, serve, pump, port = await _start(rt)
        try:
            no = await asyncio.to_thread(_http, port, "/health", token=None)
            bad = await asyncio.to_thread(_http, port, "/health", token="yanlis")
            ok = await asyncio.to_thread(_http, port, "/health")
            cmd = await asyncio.to_thread(_http, port, "/command", body={"text": "12x7?"})
            empty = await asyncio.to_thread(_http, port, "/command", body={"text": ""})
            nocmd = await asyncio.to_thread(_http, port, "/command", token=None, body={"text": "x"})
            return no, bad, ok, cmd, empty, nocmd
        finally:
            await _stop(rt, server, serve, pump)

    no, bad, ok, cmd, empty, nocmd = asyncio.run(scenario())
    assert no[0] == 401 and bad[0] == 401 and nocmd[0] == 401
    assert ok[0] == 200 and ok[1]["engine"]["session_active"] is True
    assert "uptime_s" in ok[1] and "models" in ok[1] and ok[1]["agents"]["chain"]
    assert cmd[0] == 200 and cmd[1]["ok"] is True
    assert cmd[1]["text"] == "Bakiyorum. Sonuc 84."          # arac turundan SONRAKI cevap da alindi
    assert cmd[1]["tools"] == ["calculate"] and cmd[1]["model"]
    assert empty[0] == 422


def test_command_without_live_session_is_503():
    async def scenario():
        rt = _runtime()
        rt.engine.session_active = False
        server, serve, pump, port = await _start(rt)
        try:
            return await asyncio.to_thread(_http, port, "/command", body={"text": "merhaba"})
        finally:
            await _stop(rt, server, serve, pump)

    status, body = asyncio.run(scenario())
    assert status == 503 and "oturum" in body["error"].lower()


# ----------------------------------------------------------------- WebSocket
def test_ws_action_confirm_command_and_missing_client():
    async def scenario():
        rt = _runtime()
        server, serve, pump, port = await _start(rt)
        client = JarvisClient(f"ws://127.0.0.1:{port}/ws", TOKEN, name="test-pc", kind="desktop")
        calls = []

        def list_processes(top_n: int = 12) -> dict:
            calls.append(top_n)
            return {"processes": ["a", "b"][:top_n]}

        client.register("tools.system_tools.list_processes", list_processes)
        client.register("tools.system_tools.kill_process", lambda name: 1 / 0)   # handler hatasi
        prompts = []
        client.set_confirm_handler(lambda prompt, source: prompts.append(prompt) or True)
        events = []
        client.on_event("*", lambda evt: events.append(evt.get("kind")))
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(client.connected.wait(), 5)
            await asyncio.sleep(0.1)
            hub = rt.hub
            ok = await asyncio.to_thread(hub.request_action_blocking,
                                         "tools.system_tools.list_processes", {"top_n": 1})
            failing = await asyncio.to_thread(hub.request_action_blocking,
                                              "tools.system_tools.kill_process", {"name": "x"})
            missing = await asyncio.to_thread(hub.request_action_blocking,
                                              "tools.keyboard_input.type_text", {"text": "x"})
            approved = await asyncio.to_thread(WebEngineObserver(confirm_timeout=5).confirm,
                                               "E-posta gonderilsin mi?")
            result = await client.command("12x7?", timeout=10)
            control = await client.control("mic_off")
            await asyncio.sleep(0.2)
            clients = rt.health()["clients"]
            return ok, failing, missing, approved, prompts, result, control, calls, events, clients
        finally:
            client.stop()
            await asyncio.wait_for(task, 5)
            await _stop(rt, server, serve, pump)

    ok, failing, missing, approved, prompts, result, control, calls, events, clients = asyncio.run(scenario())
    assert ok == {"processes": ["a"]} and calls == [1]
    assert "ZeroDivisionError" in failing["error"]
    assert "bagli istemci yok" in missing["error"]          # sunucu islemi KENDISI yapmaz
    assert approved is True and prompts == ["E-posta gonderilsin mi?"]
    assert result["ok"] is True and result["text"].endswith("Sonuc 84.")
    assert control is True
    assert "snapshot" in events and "confirmation_request" in events
    assert clients and clients[0]["name"] == "test-pc" and clients[0]["confirm"] is True


def test_ws_rejects_bad_token_and_client_stops_retrying():
    async def scenario():
        rt = _runtime()
        server, serve, pump, port = await _start(rt)
        client = JarvisClient(f"ws://127.0.0.1:{port}/ws", "yanlis-token-" + "x" * 30)
        try:
            await asyncio.wait_for(client.run(), 10)      # AuthRejected -> run() doner, sonsuz deneme yok
            return client.connect_count, rt.hub.clients()
        finally:
            await _stop(rt, server, serve, pump)

    connects, clients = asyncio.run(scenario())
    assert connects == 0 and clients == []


def test_client_reconnects_with_backoff_after_server_restart():
    async def scenario():
        rt = _runtime()
        server, serve, pump, port = await _start(rt)
        client = JarvisClient(f"ws://127.0.0.1:{port}/ws", TOKEN, max_backoff=0.5)
        task = asyncio.create_task(client.run())
        await asyncio.wait_for(client.connected.wait(), 5)
        await _stop(rt, server, serve, pump)                       # sunucu gitti
        await asyncio.sleep(0.3)
        assert not client.connected.is_set()
        rt2 = _runtime()
        rt2.hub.attach_loop(asyncio.get_running_loop())
        server2 = uvicorn.Server(uvicorn.Config(create_app(rt2), host="127.0.0.1", port=port,
                                                log_config=None, lifespan="off"))
        serve2 = asyncio.create_task(server2.serve())
        pump2 = asyncio.create_task(rt2.hub.pump_bus(rt2.stop_event, interval=0.02))
        await asyncio.wait_for(client.connected.wait(), 10)       # kendiliginden geri baglandi
        count = client.connect_count
        client.stop()
        await asyncio.wait_for(task, 5)
        await _stop(rt2, server2, serve2, pump2)
        return count

    assert asyncio.run(scenario()) == 2


# ----------------------------------------------------------------- vekil araclar
def test_remote_tools_keep_server_side_confirmation():
    """ToolRunner'daki onayli arac: onay REDDEDILIRSE istemciye hic istek gitmez."""
    from server import remote_tools
    from server.hub import ClientHub

    hub = ClientHub()
    sent = []
    hub.request_action_blocking = lambda action, args, timeout=None: sent.append((action, args)) or {"ok": 1}
    try:
        patched = remote_tools.install(hub)
        import agents.agent_tools as agent_tools
        from tools.tool_runner import ToolRunner

        assert any(p.endswith(".kill_process") for p in patched)
        assert any(p.endswith(".type_text") for p in patched)
        denied = ToolRunner(confirm=lambda prompt: False)._tool_kill_process("chrome")
        assert denied["status"] == "iptal edildi" and sent == []
        allowed = ToolRunner(confirm=lambda prompt: True)._tool_kill_process("chrome")
        assert allowed == {"ok": 1}
        assert sent == [("tools.system_tools.kill_process", {"name": "chrome"})]
        # ajan yetenekleri de vekil kullanir, imza korunur (Gemini semasi degismez)
        files = {fn.__name__: fn for fn in agent_tools.CAPABILITIES["files"]}
        assert getattr(files["read_text_file"], "__jarvis_remote__", "") == "tools.basic_tools.read_text_file"
        import inspect

        assert "path" in inspect.signature(files["read_text_file"]).parameters
        # sunucuda kalanlar vekil DEGIL
        assert not hasattr(agent_tools.CAPABILITIES["okul"][0], "__jarvis_remote__")
    finally:
        remote_tools.uninstall()
    import agents.agent_tools as agent_tools

    assert not any(hasattr(fn, "__jarvis_remote__")
                   for fns in agent_tools.CAPABILITIES.values() for fn in fns)


def test_request_action_blocking_from_loop_thread_does_not_deadlock():
    from server.hub import ClientHub

    async def scenario():
        hub = ClientHub()
        hub.attach_loop(asyncio.get_running_loop())
        return hub.request_action_blocking("tools.system_tools.list_processes", {})

    assert "dongu thread" in asyncio.run(scenario())["error"]


# ----------------------------------------------------------------- yapilandirma
def test_bind_and_token_validation(monkeypatch):
    from server.config import load_server_config, validate_bind

    for bad in ("0.0.0.0", "", "::", "*"):
        with pytest.raises(SystemExit):
            validate_bind(bad)
    assert validate_bind("100.101.102.103") == "100.101.102.103"
    monkeypatch.setenv("JARVIS_TOKEN", "kisa")
    with pytest.raises(SystemExit):
        load_server_config()
    monkeypatch.setenv("JARVIS_TOKEN", TOKEN)
    monkeypatch.setenv("JARVIS_SERVER_BIND", "0.0.0.0")
    with pytest.raises(SystemExit):
        load_server_config()


def test_server_settings_force_safety():
    base = Settings(gemini_api_key="x", confirm_before_close=False, agents_auto_approve_assisted=True,
                    agents_require_approval=False, web_console_bind="0.0.0.0")
    s = server_settings(base, _cfg())
    assert s.confirm_before_close and s.agents_require_approval and not s.agents_auto_approve_assisted
    assert s.audio_mode == "network" and s.web_console_bind == "127.0.0.1"
    assert s.web_console_token == TOKEN and s.remote_audio_token == TOKEN


def test_telegram_dedupe_and_disabled(monkeypatch):
    off = TelegramNotifier()
    assert off.notify("x") is False
    on = TelegramNotifier("bot", "chat")
    sent = []
    monkeypatch.setattr(on, "_send", lambda text: sent.append(text))
    monkeypatch.setattr(threading, "Thread", lambda target, args, **kw: type(
        "T", (), {"start": lambda self: target(*args)})())
    assert on.notify("model coktu") is True
    assert on.notify("model coktu") is False             # 10 dk icinde ayni mesaj tekrar gitmez
    assert on.notify("baska hata") is True
    assert len(sent) == 2


def test_watchdog_alerts_when_live_session_stays_down(monkeypatch):
    import server.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "SESSION_DOWN_ALERT_S", 0.2)
    alerts = []

    async def scenario():
        rt = _runtime()
        rt.hub.attach_loop(asyncio.get_running_loop())
        monkeypatch.setattr(rt.notifier, "notify", alerts.append)
        from loguru import logger

        sink = logger.add(lambda m: alerts.append(m.record["message"]), level="CRITICAL")
        rt.engine.session_active = False
        task = asyncio.create_task(rt.pump_stream_control())
        await asyncio.sleep(1.5)
        rt.engine.session_active = True           # geri geldi -> "duzeldi" bildirimi
        await asyncio.sleep(1.3)
        rt.request_stop()
        await asyncio.wait_for(task, 3)
        logger.remove(sink)

    asyncio.run(scenario())
    assert any("BAGLI DEGIL" in a for a in alerts)
    assert any("yeniden BAGLANDI" in a for a in alerts)


def test_frame_source_expires():
    from server.frames import RemoteFrameSource

    src = RemoteFrameSource("screen", max_age_s=0.05)
    assert src.get_latest_jpeg() is None
    src.update(b"jpeg")
    assert src.get_latest_jpeg() == b"jpeg"
    time.sleep(0.08)
    assert src.get_latest_jpeg() is None                 # bayat kare modele gitmez
