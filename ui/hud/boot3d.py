"""3B zirh acilisi: `web3d/` (React Three Fiber) sayfasini QtWebEngine ile pencerenin ustunde oynatir.

Sayfa `assets/web3d/` icine derlenir (`cd web3d && npm run build`). ES modulleri ve model
dosyasi `file://` uzerinden yuklenemedigi icin klasor, yalnizca bu makineden erisilen
(127.0.0.1, rastgele port) salt-okunur bir sunucudan verilir.

Kopru (QWebChannel gerekmez, bkz. `web3d/src/bridge.ts`):
    Qt -> sayfa : window.cyraen.setStats({cpu, ram, disk}) / window.cyraen.dismiss()
    sayfa -> Qt : document.title = "cyraen:<ready|idle|done|error>:<sayac>"

`BootOverlay` ile ayni arayuz: `start()` + `finished` sinyali. Sayfa hazir olmazsa (derleme
yok, WebGL yok, zaman asimi) kendini kapatir; arayuz acilmaya devam eder.
"""

from __future__ import annotations

import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.settings import ASSETS_DIR
from ui import theme
from ui.hud.stat_cards import SystemProbe

WEB_DIR = ASSETS_DIR / "web3d"
# Sayfa bu surede "ready" demezse acilis atlanir. Uygulama acilirken motor, ses ve uyandirma
# modeli de yuklendigi icin QtWebEngine'in ilk acilisi 10 sn'yi asabilir.
READY_TIMEOUT_MS = 30000
STATS_INTERVAL_MS = 1000
_HEADLESS_PLATFORMS = ("offscreen", "minimal")

class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        pass   # sayfa kapanirken yarim kalan istekler (baglanti kesildi) gunluge dusmesin


_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # noqa: ANN002 - istek gunlugu konsolu kirletmesin
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(directory: Path = WEB_DIR) -> str:
    """Derlenmis sayfayi veren yerel sunucuyu (bir kez) baslatir; taban adresini doner."""
    global _server
    with _server_lock:
        if _server is None:
            _server = _Server(("127.0.0.1", 0), partial(_Handler, directory=str(directory)))
            threading.Thread(target=_server.serve_forever, name="boot3d-http", daemon=True).start()
        return f"http://127.0.0.1:{_server.server_address[1]}/"


def event_of(title: str) -> str:
    """"cyraen:done:3" -> "done"; kopru basligi degilse bos metin."""
    parts = title.split(":")
    return parts[1] if len(parts) >= 2 and parts[0] == "cyraen" else ""


def available() -> bool:
    """3B acilis oynatilabilir mi: sayfa derlenmis, QtWebEngine kurulu ve gercek bir ekran var."""
    if not (WEB_DIR / "index.html").is_file():
        return False
    if QGuiApplication.platformName() in _HEADLESS_PLATFORMS:
        return False
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        return False
    return True


class Boot3DOverlay(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget, *, mode: str = "boot", hold_s: float = 0.0) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._mode = mode
        self._hold_s = max(0.0, hold_s)
        self._ready = False
        self._closed = False
        self._probe = SystemProbe()

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(theme.BG_SPACE))
        self.setPalette(palette)

        self._view = QWebEngineView(self)
        self._view.page().setBackgroundColor(QColor(theme.BG_SPACE))
        self._view.titleChanged.connect(self._on_title)
        self._view.loadFinished.connect(self._on_loaded)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view)

        # QtWebEngine'in ilk acilisi birkac saniye surer: o sirada ekran bos kalmasin
        self._loading = QLabel("C.Y.R.A.E.N  ·  3B ÇEKİRDEK YÜKLENİYOR…", self)
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet(
            f"color: {theme.ACCENT}; background: {theme.BG_SPACE}; font-size: 15px; letter-spacing: 6px;")

        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)
        self._stats = QTimer(self)
        self._stats.setInterval(STATS_INTERVAL_MS)
        self._stats.timeout.connect(self._push_stats)

        self.setGeometry(parent.rect())
        self._loading.setGeometry(self.rect())
        parent.installEventFilter(self)
        self.hide()

    def start(self) -> None:
        self.raise_()
        self.show()
        self._loading.raise_()
        url = f"{serve()}?embedded=1&mode={self._mode}&hold={self._hold_s:g}"
        self._view.load(QUrl(url))
        self._view.setFocus()
        self._started = time.monotonic()
        self._watchdog.start(READY_TIMEOUT_MS)

    def dismiss(self) -> None:
        """Kullanici Esc'e basti: sayfa kararip "done" bildirir; hazir degilse hemen kapanir."""
        if self._ready:
            self._view.page().runJavaScript("window.cyraen && window.cyraen.dismiss()")
        else:
            self._finish()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802, ANN001
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self._loading.setGeometry(self.rect())
        return False

    def _on_title(self, title: str) -> None:
        event = event_of(title)
        if event == "ready":
            self._ready = True
            logger.info("3B acilis hazir ({:.1f} sn).", time.monotonic() - self._started)
            self._loading.hide()
            self._watchdog.stop()
            self._push_stats()
            self._stats.start()
        elif event == "done":
            logger.info("3B acilis kapandi ({:.1f} sn).", time.monotonic() - self._started)
            self._finish()
        elif event == "error":
            logger.warning("3B acilis: sayfa WebGL baslatamadi, atlaniyor.")
            self._finish()

    def _on_loaded(self, ok: bool) -> None:
        if not ok and not self._closed:
            logger.warning("3B acilis: sayfa yuklenemedi, atlaniyor.")
            self._finish()

    def _on_timeout(self) -> None:
        if not self._ready:
            logger.warning("3B acilis: sayfa {} sn icinde hazir olmadi, atlaniyor.", READY_TIMEOUT_MS // 1000)
            self._finish()

    def _push_stats(self) -> None:
        data = {"cpu": self._probe.cpu() or 0.0, "ram": self._probe.ram() or 0.0, "disk": self._probe.disk() or 0.0}
        self._view.page().runJavaScript(f"window.cyraen && window.cyraen.setStats({json.dumps(data)})")

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._watchdog.stop()
        self._stats.stop()
        self.parent().removeEventFilter(self)
        self.hide()
        self._view.setUrl(QUrl("about:blank"))   # WebGL baglami ve isleyici bellegi birakilsin
        self.finished.emit()
        self.deleteLater()
