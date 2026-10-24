"""Sunucunun calisma zamani: mevcut parcalari (motor, orkestrator, web konsolu, zamanlayici,
uzak ses) `run_server.py` ile ayni desende kurar ve FastAPI katmanina baglar.

Tek asyncio dongusu: BrainEngine + uzak ses sunucusu + uvicorn (FastAPI) + BUS pompasi.
Orkestrator / web konsolu / zamanlayici mevcut is parcacigi (thread) isciler olarak kalir.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import secrets
import time
from collections import deque
from typing import Any

from loguru import logger

from config.settings import Settings
from remote.protocol import AUTH_TIMEOUT_S, PROTOCOL_VERSION
from server import __version__
from server.command import CommandBroker, CommandResult
from server.config import ServerConfig
from server.frames import RemoteFrameSource
from server.hub import ClientConn, ClientHub
from server.model_probe import ModelStatus, probe_models, summarize
from server.telegram import TelegramNotifier
from web.confirm_registry import REGISTRY
from web.event_bus import BUS

_CONTROL_ACTIONS = {"mic_on", "mic_off", "away_on", "away_off",
                    "screen_on", "screen_off", "webcam_on", "webcam_off",
                    "wake_on", "wake_off", "interrupt"}
SESSION_DOWN_ALERT_S = 300.0   # canli oturum bu kadar suredir kopuksa kritik bildirim


class CyraenRuntime:
    def __init__(self, settings: Settings, cfg: ServerConfig, notifier: TelegramNotifier) -> None:
        self.settings = settings
        self.cfg = cfg
        self.notifier = notifier
        self.hub = ClientHub()
        self.broker = CommandBroker(model_name=settings.model.removeprefix("models/"))
        self.screen_source = RemoteFrameSource("screen")
        self.webcam_source = RemoteFrameSource("webcam")
        self.started_at = time.time()
        self.model_status: list[ModelStatus] = []
        self.model_problems: list[str] = []
        self.fallback_events: deque[dict[str, Any]] = deque(maxlen=50)
        self.engine: Any = None
        self.audio_server: Any = None
        self._stop = asyncio.Event()
        self._probe_lock = asyncio.Lock()

    # ================================================================ kimlik
    def check_token(self, given: str | None) -> bool:
        if not given:
            return False
        return secrets.compare_digest(given.encode("utf-8"), self.cfg.token.encode("utf-8"))

    # ================================================================ fallback / bildirim
    def on_fallback(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}
        self.fallback_events.append(event)
        BUS.push("model_fallback", event)
        self.notifier.notify(
            f"YEDEK MODELE GECILDI: {event.get('from')} -> {event.get('to')} "
            f"({str(event.get('reason', ''))[:120]})"
        )

    async def run_probe(self) -> list[ModelStatus]:
        async with self._probe_lock:
            try:
                self.model_status = await probe_models(self.settings)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Model testi calistirilamadi")
                self.model_problems = [f"Model testi calistirilamadi: {exc!r}"]
                self.notifier.notify(self.model_problems[0])
                return self.model_status
            self.model_problems = summarize(self.model_status, self.settings.agent_model_chain)
            for problem in self.model_problems:
                logger.bind(event="model_probe_problem").error(problem)
                self.notifier.notify(problem)
            if not self.model_problems:
                logger.success(f"Tum modeller erisilebilir ({len(self.model_status)} test).")
            return self.model_status

    # ================================================================ komut
    async def command(self, text: str) -> CommandResult:
        result = await self.broker.run(text, timeout=self.cfg.command_timeout)
        logger.bind(event="command", ok=result.ok, model=result.model,
                    elapsed_ms=result.elapsed_ms).info(
            f"/command {'OK' if result.ok else 'HATA'} ({result.elapsed_ms} ms): {text[:80]!r}"
        )
        return result

    # ================================================================ saglik
    def health(self) -> dict[str, Any]:
        state = BUS.snapshot()
        agents = state.get("agents", {}) or {}
        by_status: dict[str, int] = {}
        for a in agents.values():
            st = a.get("status") or "idle"
            by_status[st] = by_status.get(st, 0) + 1
        engine_ok = bool(self.engine is not None and self.engine.session_active)
        live_ok = any(m.ok for m in self.model_status if m.role == "live") if self.model_status else None
        degraded = (not engine_ok) or bool(self.model_problems)
        return {
            "status": "degraded" if degraded else "ok",
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
            "uptime_s": int(time.time() - self.started_at),
            "engine": {
                "session_active": engine_ok,
                "connection": state.get("connection"),
                "state": state.get("engine_state"),
                "model": self.settings.model,
                "live_model_ok": live_ok,
            },
            "models": [m.as_dict() for m in self.model_status],
            "model_problems": self.model_problems,
            "recent_fallbacks": list(self.fallback_events)[-10:],
            "agents": {"count": len(agents), "by_status": by_status,
                       "chain": self.settings.agent_model_chain},
            "clients": self.hub.clients(),
            "audio_client_connected": bool(self.audio_server and self.audio_server.client_connected),
            "pending_confirmations": len(REGISTRY.pending_list()),
            "command_busy": self.broker.busy,
        }

    # ================================================================ WebSocket
    async def handle_ws(self, ws: Any) -> None:
        """Starlette WebSocket. Ilk mesaj {"type":"auth","token":..} olmali."""
        await ws.accept()
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT_S)
            hello = json.loads(raw)
        except (asyncio.TimeoutError, ValueError, KeyError, RuntimeError):
            await _close(ws, 4401, "kimlik dogrulama zaman asimi / gecersiz ilk mesaj")
            return
        except Exception:  # noqa: BLE001 - istemci hemen koptu
            return
        if hello.get("type") != "auth" or not self.check_token(str(hello.get("token") or "")):
            logger.bind(event="auth_failed").warning("WS kimlik dogrulama BASARISIZ")
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "error": "gecersiz token"})
            await _close(ws, 4401, "gecersiz token")
            return

        info = hello.get("client") or {}
        conn = ClientConn(
            name=str(info.get("name") or "istemci")[:40],
            kind=str(info.get("kind") or "generic")[:20],
            actions={str(a) for a in (info.get("actions") or [])},
            confirm=bool(info.get("confirm")),
            send=ws.send_json,
        )
        await ws.send_json({"type": "hello", "client_id": conn.id, "server_version": __version__,
                            "protocol": PROTOCOL_VERSION})
        await self.hub.register(conn)
        await ws.send_json({"type": "event", "kind": "snapshot", "data": BUS.snapshot(), "ts": time.time()})
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                except ValueError:
                    await ws.send_json({"type": "error", "error": "gecersiz JSON"})
                    continue
                conn.last_seen = time.time()
                task = await self._dispatch(conn, ws, data)
                if task is not None:
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        except Exception as exc:  # noqa: BLE001 - kopma normal
            logger.debug(f"WS dongusu bitti ({conn.name}): {exc!r}")
        finally:
            for t in tasks:
                t.cancel()
            await self.hub.unregister(conn)

    async def _dispatch(self, conn: ClientConn, ws: Any, data: dict[str, Any]) -> asyncio.Task | None:
        kind = data.get("type")
        if kind == "action_result":
            self.hub.resolve_action(conn, data)
        elif kind == "confirm_response":
            if not self.hub.resolve_confirm(data):
                await ws.send_json({"type": "error", "error": "onay istegi bulunamadi (suresi dolmus olabilir)"})
        elif kind == "command":
            return asyncio.create_task(self._ws_command(ws, data))
        elif kind == "frame":
            self._accept_frame(data)
        elif kind == "control":
            await ws.send_json({"type": "event", "kind": "control_ack",
                                "data": self.apply_control(str(data.get("action", ""))), "ts": time.time()})
        elif kind == "ping":
            await ws.send_json({"type": "pong", "ts": time.time()})
        else:
            await ws.send_json({"type": "error", "error": f"bilinmeyen mesaj tipi: {kind!r}"})
        return None

    async def _ws_command(self, ws: Any, data: dict[str, Any]) -> None:
        result = await self.command(str(data.get("text") or ""))
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "command_result", "id": data.get("id"), **result.as_dict()})

    def _accept_frame(self, data: dict[str, Any]) -> None:
        source = {"screen": self.screen_source, "webcam": self.webcam_source}.get(str(data.get("source")))
        if source is None:
            return
        try:
            source.update(base64.b64decode(str(data.get("jpeg_b64") or ""), validate=True))
        except (binascii.Error, ValueError):
            logger.debug("gecersiz kare atlandi")

    def apply_control(self, action: str) -> dict[str, Any]:
        engine = self.engine
        if action not in _CONTROL_ACTIONS or engine is None:
            return {"error": f"bilinmeyen kontrol: {action!r}"}
        if action in ("mic_on", "mic_off"):
            engine.set_mic_muted(action == "mic_off")
        elif action in ("away_on", "away_off"):
            engine.set_mic_muted(action == "away_on")
            engine.set_output_muted(action == "away_on")
        elif action in ("wake_on", "wake_off"):
            engine.set_wake_word_enabled(action == "wake_on")
        elif action in ("screen_on", "screen_off"):
            engine.set_screen_streaming(action == "screen_on")
        elif action in ("webcam_on", "webcam_off"):
            engine.set_webcam_streaming(action == "webcam_on")
        elif action == "interrupt":
            engine.interrupt_speaking()
        BUS.push("control_state", {"mic": not engine.mic_muted, "away": engine.output_muted,
                                   "wake": engine.wake_word_enabled})
        return {"ok": True, "action": action}

    # ================================================================ akis kontrolu
    async def pump_stream_control(self) -> None:
        """Motor ekran/kamera gorusu istediginde istemciye kare gondermesini soyler.

        Ayrica bekci (watchdog): canli oturum SESSION_DOWN_ALERT_S boyunca kopuksa (gecersiz
        anahtar, kota, ag) sessizce yeniden denemek yerine Telegram'a bildirir; tekrar
        baglaninca "duzeldi" bildirimi gider.
        """
        down_since: float | None = None
        alerted = False
        while not self._stop.is_set():
            engine = self.engine
            if engine is not None and self.hub.set_stream_state(engine.screen_streaming,
                                                                engine.webcam_streaming):
                await self.hub.broadcast({"type": "stream_control", **self.hub.stream_state})
            if engine is not None:
                if engine.session_active:
                    if alerted:
                        self.notifier.notify("Canli oturum yeniden BAGLANDI - CYRAEN calisiyor.")
                    down_since, alerted = None, False
                else:
                    down_since = down_since or time.monotonic()
                    if not alerted and time.monotonic() - down_since >= SESSION_DOWN_ALERT_S:
                        alerted = True
                        logger.bind(event="session_down").critical(
                            f"Canli oturum {SESSION_DOWN_ALERT_S // 60:.0f} dakikadir BAGLI DEGIL "
                            "(API anahtari / kota / ag). CYRAEN sesli yanit veremiyor."
                        )
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop


async def _close(ws: Any, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason)
