"""HUD testleri icin ortak fixture'lar (Qt offscreen; gercek kamera/mikrofon/Gemini YOK)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class FakeWebcam:
    """WebcamStreamer yerine gecen sahte kaynak."""

    def __init__(self) -> None:
        self.started = False
        self.frame: bytes | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def get_latest_jpeg(self) -> bytes | None:
        return self.frame


def make_settings():
    from config.settings import Settings, get_settings

    try:
        base = get_settings()
    except Exception:  # noqa: BLE001 - CI'da .env yok
        base = Settings(gemini_api_key="test")
    # hud_weather_location bos: testlerde hava durumu icin aga cikilmaz
    return base.model_copy(update={"webcam_enabled": False, "always_on_top": False,
                                   "hud_weather_location": ""})


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    from ui import theme
    from ui.hud.fonts import load_fonts

    load_fonts()
    app.setStyleSheet(theme.QSS)
    return app


@pytest.fixture()
def fake_webcam():
    return FakeWebcam()


@pytest.fixture(params=["classic", "hud"])
def main_window(request, qapp, fake_webcam):
    """Davranis testleri iki yerlesimde de kosar: eski panel penceresi ve sinematik HUD."""
    from agents.qt_observer import QtOrchestratorObserver
    from ui.hud.hud_window import HudWindow
    from ui.main_window import MainWindow
    from ui.qt_observer import QtEngineObserver

    window_cls = HudWindow if request.param == "hud" else MainWindow
    win = window_cls(
        make_settings(), QtEngineObserver(), fake_webcam, orch_observer=QtOrchestratorObserver()
    )
    win.resize(1320, 860)
    yield win
    win.hide()
    win.deleteLater()
    qapp.processEvents()


def wait_ms(app, ms: int) -> None:
    from PySide6.QtTest import QTest

    QTest.qWait(ms)
    app.processEvents()
