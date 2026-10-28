"""Decision Pipeline panosunu JARVIS'in kendi (Qt WebEngine) penceresinde acar.

QtWebEngine yoksa varsayilan tarayiciya duser. Pano sunucusu orkestratorle birlikte
baslar (ui/dashboard/server.py); burada yalnizca adres acilir.
"""

from __future__ import annotations

from typing import Any

from loguru import logger


def dashboard_url(settings: Any, mode: str | None = None) -> str:
    url = f"http://127.0.0.1:{int(settings.dashboard_port)}/dashboard/"
    return f"{url}?mode={mode}" if mode else url


class DashboardWindow:
    def __init__(self) -> None:
        self._win = None

    def is_open(self) -> bool:
        return self._win is not None and self._win.isVisible()

    def open(self, settings: Any) -> dict[str, Any]:
        if not getattr(settings, "dashboard_enabled", False):
            return {"error": "Pano kapali (JARVIS_DASHBOARD=false)."}
        url = dashboard_url(settings)
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QIcon
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            import webbrowser

            webbrowser.open(url, new=1)
            return {"status": "tarayicida acildi", "url": url}

        if self._win is None:
            view = QWebEngineView()
            view.setWindowTitle("JARVIS · Decision Pipeline")
            view.resize(1600, 900)
            view.setStyleSheet("background:#03050b;")
            try:
                from config.settings import APP_DIR

                view.setWindowIcon(QIcon(str(APP_DIR / "assets" / "jarvis.ico")))
            except Exception:  # noqa: BLE001
                pass
            self._win = view
        self._win.setUrl(QUrl(url))
        self._win.show()
        self._win.raise_()
        self._win.activateWindow()
        logger.info(f"[pano] Decision Pipeline penceresi acildi: {url}")
        return {"status": "acildi", "url": url}

    def close(self) -> None:
        if self._win is not None:
            self._win.close()
