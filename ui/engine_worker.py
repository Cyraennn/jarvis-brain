"""BrainEngine'i kendi thread'inde, kendi asyncio dongusuyle calistiran isci.

GUI (Qt) ana thread'de kalmali; motor ise engelleyici asyncio islerini burada yurutur.
Kontrol cagrilari (`request_shutdown`, `set_mic_muted`, ...) thread-safe sekilde
motor dongusune `call_soon_threadsafe` ile aktarilir.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Callable

from loguru import logger

from config.settings import Settings
from core.audio_transport import AudioTransport, LocalAudioTransport, SwitchableAudioTransport
from core.brain_engine import BrainEngine
from core.bridge_listener import BridgeListener
from core.events import EngineObserver
from core.screen_streamer import ScreenStreamer
from core.telegram_handler import TelegramHandler
from core.webcam_streamer import WebcamStreamer


class EngineWorker(threading.Thread):
    def __init__(
        self,
        settings: Settings,
        observer: EngineObserver,
        webcam: WebcamStreamer,
        screen: ScreenStreamer | None = None,
        bridge: BridgeListener | None = None,
        on_finished: Callable[[BaseException | None], None] | None = None,
    ) -> None:
        super().__init__(name="brain-engine", daemon=True)
        self._settings = settings
        self._observer = observer
        self._webcam = webcam
        self._screen = screen
        self._bridge = bridge
        self._on_finished = on_finished

        self._loop: asyncio.AbstractEventLoop | None = None
        self._engine: BrainEngine | None = None
        self._telegram: TelegramHandler | None = None
        self._ready = threading.Event()
        self._audio_server = None  # telefon sesi (net/audio_server.py), _build_audio kurar

    # ------------------------------------------------------------------ thread
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._engine = BrainEngine(
            self._settings,
            audio_transport=self._build_audio(),
            observer=self._observer,
            webcam=self._webcam,
            bridge=self._bridge,
            screen=self._screen,
        )
        tg = TelegramHandler(self._settings)
        self._telegram = tg if tg.enabled else None
        self._ready.set()

        error: BaseException | None = None
        try:
            self._loop.run_until_complete(self._run_all())
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except BaseException as exc:  # noqa: BLE001
            error = exc
            logger.exception("Engine worker beklenmedik sekilde sonlandi.")
            with contextlib.suppress(Exception):
                self._observer.on_connection("closed")
        finally:
            with contextlib.suppress(Exception):
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            if self._on_finished is not None:
                self._on_finished(error)

    def _build_audio(self) -> AudioTransport | None:
        """Telefon sesi aciksa PC <-> telefon gecisli transport; degilse motorun varsayilani."""
        s = self._settings
        if not s.phone_audio_enabled or s.audio_mode != "local":
            return None
        from net.audio_server import NetworkAudioServer

        token = s.remote_audio_token or s.web_console_token
        self._audio_server = NetworkAudioServer(port=s.remote_audio_port, bind=s.web_console_bind, token=token)
        try:
            local: AudioTransport | None = LocalAudioTransport(s)
        except Exception as exc:  # noqa: BLE001 - PyAudio yoksa telefon yine calisir
            logger.warning(f"PC ses motoru baslatilamadi, yalnizca telefon sesi: {exc}")
            local = None
        return SwitchableAudioTransport(
            local, self._audio_server,
            receive_rate=s.audio.receive_sample_rate, sample_width=s.audio.sample_width,
        )

    async def _run_all(self) -> None:
        """Motor + (varsa) Telegram kolu ve telefon ses sunucusu ayni dongude; motor bitince hepsi durur."""
        assert self._engine is not None
        audio_task = (
            asyncio.create_task(self._audio_server.run(), name="phone_audio_server")
            if self._audio_server is not None else None
        )
        try:
            await self._run_engine()
        finally:
            if audio_task is not None:
                audio_task.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await audio_task

    async def _run_engine(self) -> None:
        assert self._engine is not None
        if self._telegram is None:
            await self._engine.run()
            return
        tg_task = asyncio.create_task(self._telegram.run(), name="telegram_handler")
        try:
            await self._engine.run()
        finally:
            self._telegram.request_shutdown()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(tg_task, timeout=5.0)

    # ------------------------------------------------------------ dis kontrol
    def _call(self, fn: Callable[[], None]) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(fn)

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    @property
    def engine(self) -> BrainEngine | None:
        return self._engine

    def shutdown(self) -> None:
        if self._engine is not None:
            self._call(self._engine.request_shutdown)

    def set_mic_muted(self, muted: bool) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_mic_muted(muted))

    def set_wake_word_enabled(self, enabled: bool) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_wake_word_enabled(enabled))

    def set_output_muted(self, muted: bool) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_output_muted(muted))

    def interrupt_speaking(self) -> None:
        if self._engine is not None:
            self._call(self._engine.interrupt_speaking)

    def retry_audio(self) -> None:
        if self._engine is not None:
            self._call(self._engine.retry_audio)

    def set_webcam_streaming(self, enabled: bool) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_webcam_streaming(enabled))

    def set_screen_streaming(self, enabled: bool) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_screen_streaming(enabled))

    def inject_bridge_message(self, text: str) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.inject_bridge_message(text))

    def set_persona(self, key: str) -> None:
        if self._engine is not None:
            self._call(lambda: self._engine.set_persona(key))
