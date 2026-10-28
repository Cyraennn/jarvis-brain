"""HUD arayuzunu (PySide6) sunucuya baglar - arayuz kodu degismez.

`RemoteEngineWorker`, `ui/engine_worker.py::EngineWorker` ile ayni arayuzu sunar (start,
wait_ready, set_mic_muted, inject_bridge_message, shutdown...). Motor yerine kendi
thread'inde `JarvisClient` (+ masaustu eylemleri, ekran/kamera, ses) calistirir ve
sunucudan gelen olaylari mevcut Qt gozlemcilerine (`QtEngineObserver`,
`QtOrchestratorObserver`) aktarir. Boylece HUD, yerel motordaki gibi davranir.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from types import SimpleNamespace
from typing import Any

from loguru import logger

from client.config import ClientConfig
from client.core import JarvisClient


class _Named(str):
    """Bilinmeyen departman/otonomi degeri icin: hem `.value` hem sozluk anahtari olabilir."""

    @property
    def value(self) -> str:
        return str(self)


def _enum(enum_cls: Any, raw: Any) -> Any:
    try:
        return enum_cls(raw)
    except ValueError:
        return _Named(raw or "")


def _spec(a: dict[str, Any]) -> SimpleNamespace:
    """Sunucudan gelen ajan sozlugu -> HUD'un bekledigi AgentSpec benzeri nesne.

    department/autonomy gercek enum'lar (Department/Autonomy): Qt gozlemcisi bunlari
    sozluk anahtari olarak kullanir (hashlenebilir olmali)."""
    from agents.schemas import Autonomy, Department

    return SimpleNamespace(
        name=a.get("name", ""), title=a.get("title", a.get("name", "")),
        department=_enum(Department, a.get("department", "")),
        autonomy=_enum(Autonomy, a.get("autonomy", "")),
        sop="", skills=[],
    )


def bind_observers(client: JarvisClient, engine_obs: Any, orch_obs: Any | None) -> None:
    """Sunucu olaylarini Qt gozlemci metotlarina esler."""
    def transcript(final: bool):
        def _cb(data: Any) -> None:
            data = data or {}
            text = str(data.get("text", ""))
            if data.get("who") == "user":
                engine_obs.on_user_transcript(text, final)
            else:
                engine_obs.on_assistant_transcript(text, final)
        return _cb

    client.on_event("connection", lambda d: engine_obs.on_connection(str(d)))
    client.on_event("engine_state", lambda d: engine_obs.on_state(str(d)))
    client.on_event("input_level", lambda d: engine_obs.on_input_level(float(d or 0)))
    client.on_event("output_level", lambda d: engine_obs.on_output_level(float(d or 0)))
    client.on_event("transcript", transcript(True))
    client.on_event("transcript_partial", transcript(False))
    client.on_event("tool_call", lambda d: engine_obs.on_tool_call(list((d or {}).get("names", []))))
    client.on_event("tool_result", lambda d: engine_obs.on_tool_result(
        str((d or {}).get("name", "?")), bool((d or {}).get("ok")), str((d or {}).get("detail", ""))))
    client.on_event("bridge_message", lambda d: engine_obs.on_bridge_message(str(d)))
    client.on_event("external_typing", lambda d: engine_obs.on_external_typing(bool(d)))
    client.on_event("disconnected", lambda _: engine_obs.on_connection("reconnecting"))

    def snapshot(state: Any) -> None:
        state = state or {}
        engine_obs.on_connection(str(state.get("connection", "closed")))
        engine_obs.on_state(str(state.get("engine_state", "idle")))
        agents = list((state.get("agents") or {}).values())
        if orch_obs is not None and agents:
            orch_obs.on_agents_loaded([_spec(a) for a in agents])

    client.on_event("snapshot", snapshot)
    if orch_obs is not None:
        client.on_event("agents_loaded", lambda d: orch_obs.on_agents_loaded([_spec(a) for a in (d or [])]))
        client.on_event("task", lambda d: orch_obs.on_task(SimpleNamespace(
            id=(d or {}).get("id", ""), agent=(d or {}).get("agent", ""),
            status=(d or {}).get("status", ""), department=(d or {}).get("department", ""),
            autonomy=(d or {}).get("autonomy", ""), detail=(d or {}).get("detail", ""),
            result=(d or {}).get("result"), steps=0)))

    # onay: HUD'un kendi onay diyalogu (QtEngineObserver.confirm GUI thread'inde soru sorar)
    client.set_confirm_handler(
        lambda prompt, source, cancel: bool(engine_obs.confirm(prompt, cancel=cancel)))


class RemoteEngineWorker(threading.Thread):
    def __init__(self, cfg: ClientConfig, engine_obs: Any, orch_obs: Any | None = None) -> None:
        super().__init__(name="jarvis-client", daemon=True)
        self.cfg = cfg
        self.client = JarvisClient(cfg.ws_url, cfg.token, name=cfg.name, kind=cfg.kind)
        bind_observers(self.client, engine_obs, orch_obs)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._vision: Any = None
        self._audio: Any = None
        self._mic_muted = False

    # ------------------------------------------------------------ thread
    def run(self) -> None:
        from client.desktop import register_desktop_handlers

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        if self.cfg.desktop:
            register_desktop_handlers(self.client, self.cfg)
        tasks = [self.client.run()]
        if self.cfg.vision:
            from client.vision import VisionLink

            self._vision = VisionLink(self.client)
            tasks.append(self._vision.run())
        if self.cfg.audio:
            from client.audio import AudioLink

            self._audio = AudioLink(self.cfg.audio_url)
            tasks.append(self._audio.run())
        self._ready.set()
        try:
            self._loop.run_until_complete(_gather_until_client_stops(self.client, tasks))
        except Exception:  # noqa: BLE001
            logger.exception("Istemci thread'i sonlandi")
        finally:
            if self._vision is not None:
                self._vision.close()
            with contextlib.suppress(Exception):
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    # --------------------------------------------- EngineWorker ile ayni arayuz
    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def _call(self, coro_factory) -> None:  # noqa: ANN001
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)

    @property
    def engine(self) -> Any:
        """MainWindow ekran onizlemesi icin: yerel ekran yakalayici (varsa)."""
        streamers = getattr(self._vision, "_streamers", {}) if self._vision else {}
        return SimpleNamespace(screen=streamers.get("screen"))

    def shutdown(self) -> None:
        if self._audio is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._audio.stop)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self.client.stop)

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = bool(muted)
        self._call(lambda: self.client.control("mic_off" if muted else "mic_on"))

    def set_wake_word_enabled(self, enabled: bool) -> None:
        self._call(lambda: self.client.control("wake_on" if enabled else "wake_off"))

    def set_output_muted(self, muted: bool) -> None:
        self._call(lambda: self.client.control("away_on" if muted else "away_off"))

    def retry_audio(self) -> None:
        pass  # ses baglantisi kendiliginden yeniden dener

    def set_webcam_streaming(self, enabled: bool) -> None:
        self._call(lambda: self.client.control("webcam_on" if enabled else "webcam_off"))

    def set_screen_streaming(self, enabled: bool) -> None:
        self._call(lambda: self.client.control("screen_on" if enabled else "screen_off"))

    def inject_bridge_message(self, text: str) -> None:
        self._call(lambda: self.client.command(text))


async def _gather_until_client_stops(client: JarvisClient, coros: list) -> None:
    tasks = [asyncio.create_task(c) for c in coros]
    try:
        await tasks[0]            # istemci durunca (kapanis / token reddi) digerlerini de durdur
    finally:
        for t in tasks[1:]:
            t.cancel()
        await asyncio.gather(*tasks[1:], return_exceptions=True)
