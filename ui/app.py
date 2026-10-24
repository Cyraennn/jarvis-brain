"""Arayuz giris noktasi: QApplication + motor iscisi + sinyal baglantilari."""

from __future__ import annotations

import sys

from loguru import logger
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from agents.qt_observer import QtOrchestratorObserver
from config.settings import Settings, get_settings
from core import personas
from core.webcam_streamer import WebcamStreamer
from ui import theme
from ui.engine_worker import EngineWorker
from ui.hud.fonts import load_fonts
from ui.hud.hud_window import HudWindow
from ui.main_window import MainWindow, _load_app_icon
from ui.orchestrator_worker import OrchestratorWorker
from ui.qt_observer import QtEngineObserver
from ui.scheduler_worker import SchedulerWorker
from ui.sound import play_startup
from ui.web_worker import WebWorker


def _configure_file_logging(settings: Settings) -> None:
    logger.remove()
    if sys.stderr is not None:  # pythonw.exe / paketli .exe altinda None olabilir
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
            enqueue=True,
        )
    logger.add(
        settings.log_file,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,
    )


def run() -> int:
    # Icerik panelinin web gorunumu (QtWebEngine) bunu QApplication'dan ONCE ister
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("CYRAEN")
    app.setApplicationDisplayName("CYRAEN")
    app.setWindowIcon(_load_app_icon())
    app.setQuitOnLastWindowClosed(False)  # tepsiye kucultunce cikmasin
    load_fonts()                          # assets/fonts (Rajdhani + JetBrains Mono)
    app.setStyleSheet(theme.QSS)

    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - genelde eksik API anahtari
        QMessageBox.critical(
            None,
            "CYRAEN - Yapilandirma Hatasi",
            f"Ayarlar yuklenemedi:\n\n{exc}\n\n"
            "cyraen-brain/.env dosyanizda GEMINI_API_KEY tanimli oldugundan emin olun.",
        )
        return 1

    _configure_file_logging(settings)
    # son secilen kisiligin temasi (CYRAEN mavi / FRIDAY yesil / ULTRON kirmizi)
    theme.apply_palette(personas.load_active(settings).key)
    app.setStyleSheet(theme.QSS)

    observer = QtEngineObserver()
    webcam = WebcamStreamer(
        index=settings.webcam_index,
        jpeg_quality=settings.webcam_jpeg_quality,
    )

    orch_observer = QtOrchestratorObserver() if settings.agents_enabled else None
    window_cls = MainWindow if settings.ui_style == "classic" else HudWindow
    window = window_cls(settings, observer, webcam, orch_observer=orch_observer)

    def _qt_sink(message) -> None:  # noqa: ANN001
        record = message.record
        try:
            window.log_message.emit(record["level"].name, record["message"])
        except (RuntimeError, TypeError):
            pass  # pencere kapanirken yok edildi (sinyal artik bagli degil)

    logger.add(_qt_sink, level="INFO", format="{message}", enqueue=True)

    worker = EngineWorker(settings, observer, webcam)
    window.attach_worker(worker)

    orch_worker: OrchestratorWorker | None = None
    if orch_observer is not None:
        orch_worker = OrchestratorWorker(settings, orch_observer)
        window.attach_orchestrator_worker(orch_worker)

    def _on_web_control(action: str) -> dict:
        """Telefon web konsolundan gelen PC ses kontrolu (mic / uzak mod / uyandirma)."""
        if action == "mic_off":
            worker.set_mic_muted(True)
            return {"mic": False}
        if action == "mic_on":
            worker.set_mic_muted(False)
            return {"mic": True}
        if action == "away_on":
            worker.set_mic_muted(True)
            worker.set_output_muted(True)
            logger.info("Uzak mod ACIK - telefondan gorusme (PC mic + hoparlor kapali).")
            return {"away": True}
        if action == "away_off":
            worker.set_mic_muted(False)
            worker.set_output_muted(False)
            logger.info("Uzak mod KAPALI - PC sesi geri acildi.")
            return {"away": False}
        if action in ("wake_on", "wake_off"):
            window.wake_toggle_requested.emit(action == "wake_on")  # dugme -> motor + BUS
            return {"wake": action == "wake_on"}
        if action == "interrupt":  # El Kontrolu ✊: konusmayi kes
            worker.interrupt_speaking()
            return {"interrupted": True}
        return {"error": "bilinmeyen"}

    web_worker = (
        WebWorker(settings, on_control=_on_web_control)
        if settings.web_console_enabled
        else None
    )
    if web_worker is not None:
        window.attach_web_worker(web_worker)
        from web.event_bus import BUS

        BUS.push("control_state", {"wake": settings.wake_word_enabled})
    sched_worker = SchedulerWorker(settings) if settings.scheduler_enabled else None

    window.show()
    play_startup(settings)  # acilis alkisi
    worker.start()
    worker.wait_ready(5.0)
    if orch_worker is not None:
        orch_worker.start()
        orch_worker.wait_ready(5.0)
    if web_worker is not None:
        web_worker.start()
    if sched_worker is not None:
        sched_worker.start()

    exit_code = app.exec()

    worker.shutdown()
    worker.join(timeout=6.0)
    for w in (orch_worker, web_worker, sched_worker):
        if w is not None:
            w.shutdown()
            w.join(timeout=5.0)
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
