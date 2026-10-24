"""CYRAEN sunucusunu baslatir:  python -m server

Sira:
 1. .env -> ServerConfig (CYRAEN_TOKEN zorunlu, 0.0.0.0'a baglanma reddedilir)
 2. JSON + donen dosya loglama, Telegram bildirimi
 3. Istemci eylem vekilleri (motor olusturulmadan ONCE)
 4. Mevcut parcalar: BrainEngine (ag-ses), uzak ses sunucusu, orkestrator, web konsolu, zamanlayici
 5. Model testi (arka planda) + FastAPI (uvicorn) + BUS pompasi
SIGTERM/SIGINT (systemd stop) -> uvicorn durur, motor kapanir, isciler durdurulur.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

import uvicorn
from loguru import logger

from agents.genai_util import FALLBACK_HOOKS
from config.settings import get_settings
from core.audio_transport import NetworkAudioTransport
from core.brain_engine import BrainEngine
from core import local_llm
from net.audio_server import NetworkAudioServer
from remote.protocol import MAX_MESSAGE_BYTES
from server import __version__, remote_tools
from server.app import create_app
from server.config import load_server_config, server_settings
from server.logging_setup import configure_logging
from server.observers import ServerEngineObserver
from server.runtime import CyraenRuntime
from server.telegram import TelegramNotifier
from ui.orchestrator_worker import OrchestratorWorker
from ui.scheduler_worker import SchedulerWorker
from ui.web_worker import WebWorker
from web.web_observer import WebOrchestratorObserver


class _Server(uvicorn.Server):
    """Sinyalleri uvicorn degil biz yonetiriz: once motoru duzgunce kapatabilmek icin."""

    @contextlib.contextmanager
    def capture_signals(self):  # noqa: ANN201
        yield


async def amain() -> None:
    cfg = load_server_config()
    settings = server_settings(get_settings(), cfg)
    local_llm.configure(settings)
    notifier = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
    configure_logging(cfg, notifier, level=settings.log_level)
    logger.info(f"CYRAEN sunucusu {__version__} basliyor - http://{cfg.bind}:{cfg.port} "
                f"(Telegram {'acik' if cfg.telegram_enabled else 'KAPALI - yalnizca log'})")

    loop = asyncio.get_running_loop()
    runtime = CyraenRuntime(settings, cfg, notifier)
    runtime.hub.attach_loop(loop)
    remote_tools.install(runtime.hub)
    FALLBACK_HOOKS.append(runtime.on_fallback)

    audio_server = NetworkAudioServer(port=settings.remote_audio_port, bind=cfg.bind,
                                      token=settings.remote_audio_token)
    observer = ServerEngineObserver(runtime.hub, runtime.broker,
                                    confirm_timeout=settings.remote_confirm_timeout)
    engine = BrainEngine(settings, observer=observer, webcam=runtime.webcam_source,
                         screen=runtime.screen_source,
                         audio_transport=NetworkAudioTransport(audio_server))
    runtime.engine = engine
    runtime.audio_server = audio_server
    runtime.broker.engine = engine

    orch_worker = (OrchestratorWorker(settings, WebOrchestratorObserver(
        confirm_timeout=settings.remote_confirm_timeout)) if settings.agents_enabled else None)
    web_worker = WebWorker(settings, on_control=lambda a: runtime.apply_control(a)) \
        if settings.web_console_enabled else None
    sched_worker = SchedulerWorker(settings) if settings.scheduler_enabled else None
    for w in (orch_worker, web_worker, sched_worker):
        if w is not None:
            w.start()

    server = _Server(uvicorn.Config(
        create_app(runtime), host=cfg.bind, port=cfg.port, log_config=None,
        ws_max_size=MAX_MESSAGE_BYTES, proxy_headers=False, server_header=False,
    ))

    def _on_signal(*_: object) -> None:
        logger.info("Kapatma sinyali alindi.")
        runtime.request_stop()
        server.should_exit = True
        engine.request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, RuntimeError):  # Windows
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_on_signal))

    tasks = {
        asyncio.create_task(engine.run(), name="brain_engine"),
        asyncio.create_task(audio_server.run(), name="remote_audio"),
        asyncio.create_task(server.serve(), name="http"),
        asyncio.create_task(runtime.hub.pump_bus(runtime.stop_event), name="bus_pump"),
        asyncio.create_task(runtime.pump_stream_control(), name="stream_control"),
    }
    if cfg.probe_models:
        tasks.add(asyncio.create_task(runtime.run_probe(), name="model_probe"))

    core = {t for t in tasks if t.get_name() in ("brain_engine", "http", "remote_audio")}
    try:
        done, _ = await asyncio.wait(core, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if not t.cancelled() and t.exception() is not None:
                logger.critical(f"Cekirdek gorev coktu ({t.get_name()}): {t.exception()!r}")
            elif not runtime.stop_event.is_set():
                logger.warning(f"Cekirdek gorev bitti: {t.get_name()} - sunucu kapaniyor.")
    finally:
        _on_signal()
        with contextlib.suppress(asyncio.TimeoutError, Exception):
            await asyncio.wait_for(asyncio.gather(*(t for t in tasks if t.get_name() in
                                                    ("brain_engine", "http")),
                                                  return_exceptions=True), timeout=10)
        for t in tasks:
            t.cancel()
        for w in (orch_worker, web_worker, sched_worker):
            if w is not None:
                with contextlib.suppress(Exception):
                    w.shutdown()
        logger.info("CYRAEN sunucusu durdu.")


def main() -> None:
    try:
        asyncio.run(amain())
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(f"HATA: {exc}", file=sys.stderr)
        raise
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
