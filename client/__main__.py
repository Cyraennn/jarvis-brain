"""CYRAEN istemcisini baslatir (cyraen-brain klasorunden):

    python -m client          # arayuzsuz: masaustu eylemleri + ekran/kamera + ses + onay penceresi
    python -m client --ui     # sinematik HUD arayuzu, sunucuya bagli (yerel motor YOK)
    python -m client --no-audio --no-vision    # yalnizca eylem/komut istemcisi

Sunucu adresi ve token: client/.env (ornek: client/.env.example)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from client.config import load_client_config


def _configure_logging() -> None:
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO",
                   format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


async def _run_headless(cfg) -> None:  # noqa: ANN001
    from client.core import CyraenClient
    from client.desktop import make_confirm_handler, register_desktop_handlers

    client = CyraenClient(cfg.ws_url, cfg.token, name=cfg.name, kind=cfg.kind)
    if cfg.desktop:
        register_desktop_handlers(client, cfg)
    client.set_confirm_handler(make_confirm_handler(cfg.confirm_mode))
    client.on_event("transcript", lambda d: logger.info(
        f"{'SEN' if (d or {}).get('who') == 'user' else 'CYRAEN'}: {(d or {}).get('text', '')}"))
    client.on_event("model_fallback", lambda d: logger.warning(f"YEDEK MODEL: {d}"))

    coros = [client.run()]
    vision = None
    if cfg.vision:
        from client.vision import VisionLink

        vision = VisionLink(client)
        coros.append(vision.run())
    if cfg.audio:
        from client.audio import AudioLink

        coros.append(AudioLink(cfg.audio_url).run())
    tasks = [asyncio.create_task(c) for c in coros]
    try:
        await tasks[0]
    finally:
        for t in tasks[1:]:
            t.cancel()
        await asyncio.gather(*tasks[1:], return_exceptions=True)
        if vision is not None:
            vision.close()


def _run_ui(cfg) -> int:  # noqa: ANN001
    from PySide6.QtWidgets import QApplication

    from agents.qt_observer import QtOrchestratorObserver
    from client.qt_bridge import RemoteEngineWorker
    from config.settings import get_settings
    from ui import theme
    from ui.hud.fonts import load_fonts
    from ui.hud.hud_window import HudWindow
    from ui.main_window import _load_app_icon
    from ui.qt_observer import QtEngineObserver

    app = QApplication(sys.argv)
    app.setApplicationName("CYRAEN")
    app.setWindowIcon(_load_app_icon())
    app.setQuitOnLastWindowClosed(False)
    load_fonts()
    app.setStyleSheet(theme.QSS)

    settings = get_settings().model_copy(update={"webcam_enabled": False})
    engine_obs, orch_obs = QtEngineObserver(), QtOrchestratorObserver()
    worker = RemoteEngineWorker(cfg, engine_obs, orch_obs)

    class _SharedWebcamPreview:
        """Kamerayi IKINCI kez acmamak icin: HUD onizlemesi VisionLink'in karelerini gosterir;
        kamera ac/kapa dugmesi sunucuya kontrol mesaji olarak gider (worker.set_webcam_streaming)."""

        def start(self) -> None: ...
        def stop(self) -> None: ...

        def get_latest_jpeg(self):  # noqa: ANN201
            vision = getattr(worker, "_vision", None)
            streamer = getattr(vision, "_streamers", {}).get("webcam") if vision else None
            return streamer.get_latest_jpeg() if streamer is not None else None

    window = HudWindow(settings, engine_obs, _SharedWebcamPreview(), orch_observer=orch_obs)
    window.attach_worker(worker)
    window.setWindowTitle(f"CYRAEN — {cfg.server_host}")
    window.show()
    worker.start()
    worker.wait_ready(5.0)
    code = app.exec()
    worker.shutdown()
    worker.join(timeout=5.0)
    return code


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m client", description="CYRAEN istemcisi")
    parser.add_argument("--ui", action="store_true", help="HUD arayuzunu ac")
    parser.add_argument("--no-audio", action="store_true", help="mikrofon/hoparlor kanalini acma")
    parser.add_argument("--no-vision", action="store_true", help="ekran/kamera karesi gonderme")
    parser.add_argument("--no-desktop", action="store_true", help="masaustu eylemlerini kaydetme")
    args = parser.parse_args()

    _configure_logging()
    cfg = load_client_config()
    from dataclasses import replace

    cfg = replace(cfg, audio=cfg.audio and not args.no_audio, vision=cfg.vision and not args.no_vision,
                  desktop=cfg.desktop and not args.no_desktop)
    logger.info(f"Sunucu: {cfg.ws_url} | istemci '{cfg.name}' | ses={'acik' if cfg.audio else 'kapali'} "
                f"| goruntu={'acik' if cfg.vision else 'kapali'} | masaustu={'acik' if cfg.desktop else 'kapali'}")
    if args.ui:
        sys.exit(_run_ui(cfg))
    try:
        asyncio.run(_run_headless(cfg))
    except KeyboardInterrupt:
        logger.info("Cikiliyor.")


if __name__ == "__main__":
    main()
