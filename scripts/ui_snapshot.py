"""HUD ekran goruntusu uretici (offscreen; gercek kamera/mikrofon/Gemini gerekmez).

Kullanim (jarvis-brain klasorunden):
    python scripts/ui_snapshot.py [cikti_klasoru]

`scratch/ui/` altina 1320x860 ve 1024x700 PNG'ler yazar (varsayilan HUD; eski yerlesim icin
JARVIS_UI_STYLE=classic). Asama oncesi/sonrasi gorsel
karsilastirma icin kullanilir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":   # offscreen platformu sistem fontlarini kendiliginden bulmaz (yazilar kutu cikar)
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class _FakeWebcam:
    def start(self): ...
    def stop(self): ...
    def get_latest_jpeg(self):
        return None


def build_window(app):
    from agents.departments import all_agents
    from agents.qt_observer import QtOrchestratorObserver
    from config.settings import Settings, get_settings
    from ui import theme
    from ui.hud.fonts import load_fonts
    from ui.hud.hud_window import HudWindow
    from ui.main_window import MainWindow
    from ui.qt_observer import QtEngineObserver

    load_fonts()
    app.setStyleSheet(theme.QSS)
    try:
        base = get_settings()
    except Exception:  # noqa: BLE001
        base = Settings(gemini_api_key="test")
    settings = base.model_copy(update={"webcam_enabled": False, "always_on_top": False})
    window_cls = MainWindow if os.getenv("JARVIS_UI_STYLE", "hud") == "classic" else HudWindow
    win = window_cls(settings, QtEngineObserver(), _FakeWebcam(), orch_observer=QtOrchestratorObserver())

    agents = list(all_agents().values()) if isinstance(all_agents(), dict) else list(all_agents())
    win._on_agents_loaded(agents)
    win._observer.connection.emit("active")
    win._observer.state.emit("listening")
    win._transcript.add_user("Bugün hava nasıl olacak?")
    win._transcript.add_assistant("İstanbul'da yarın parçalı bulutlu, sıcaklık yirmi iki derece civarında olacak.")
    win._log.add_event("🛠", "Araç çağrısı: get_weather", theme.ACCENT)
    win._log.add_event("✓", "get_weather -> tamam", theme.GOOD)
    win._log.flush()
    a = agents[0]
    win._on_orch_task(SimpleNamespace(id="t1", agent=a.name, status="running", result="", detail=""))
    win._on_orch_task(SimpleNamespace(id="t2", agent=agents[1].name, status="queued", result="", detail=""))
    return win


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratch" / "ui"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    win = build_window(app)
    for i, (w, h) in enumerate(((1320, 860), (1024, 700))):
        win.resize(w, h)
        win.show()
        QTest.qWait(2200 if i == 0 else 400)   # ilk gosterimde acilis animasyonu bitsin
        path = out / f"hud_{w}x{h}.png"
        win.grab().save(str(path))
        print("yazildi:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
