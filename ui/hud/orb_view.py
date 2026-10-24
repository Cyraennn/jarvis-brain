"""Merkez gorsel: Zoey OS (zoeyos.com) tarzi parcacik orb'u + altindaki konusma arayuzu.

`web3d/` sayfasinin `?view=orb` gorunumu QtWebEngine'de oynatilir (bkz. `boot3d.serve`).
`CommandGraph` ile ayni API'yi sunar (`set_center_mode`, `set_center_level`, `set_active`,
`set_agents`, `set_agent_status`, `node_clicked`); ajan dugumleri cizilmedigi icin ajan
cagrilari etkisizdir, ajanlar soldaki AJANLAR kartinda kalir.

Kopru (bkz. `web3d/src/orb/voice.ts`):
    Qt -> sayfa : window.jarvis.setVoice({state, level, thinking, asleep}) / setCaption / setStatus
                  / setActive / intro
    sayfa -> Qt : document.title = "jarvis:<ready|landed|mic|error>:<sayac>"

Sayfa hazir olmazsa (derleme yok, WebGL yok, zaman asimi) `failed` yayar; pencere klasik
komuta grafine doner.
"""

from __future__ import annotations

import json

from loguru import logger
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ui import theme
from ui.hud import boot3d

READY_TIMEOUT_MS = 30000
PUSH_INTERVAL_MS = 33            # ses genligi ~30 Hz gonderilir
_STATES = ("idle", "listening", "speaking")


def available() -> bool:
    """Orb oynatilabilir mi (derlenmis sayfa + QtWebEngine + gercek ekran)."""
    return boot3d.available()


class OrbView(QWidget):
    node_clicked = Signal(str)   # CommandGraph uyumlulugu; orb'da dugum yok
    landed = Signal()            # acilista orb yerine oturdu
    mic_clicked = Signal()       # alttaki dalga hapina tiklandi
    failed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._ready = False
        self._dead = False
        self._state = "idle"
        self._level = 0.0
        self._thinking = False
        self._asleep = False
        self._caption = ""
        self._status = ""
        self._theme: dict = {}   # kisilik temasi; sayfa hazir olunca yeniden gonderilir
        self._active = True
        self._dirty = True

        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(theme.BG_SPACE))
        self.setPalette(pal)

        self._view = QWebEngineView(self)
        self._view.page().setBackgroundColor(QColor(theme.BG_SPACE))
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._view.titleChanged.connect(self._on_title)
        self._view.loadFinished.connect(self._on_loaded)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._view)

        self._push_timer = QTimer(self)
        self._push_timer.setInterval(PUSH_INTERVAL_MS)
        self._push_timer.timeout.connect(self._push_voice)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)

        self._view.load(QUrl(f"{boot3d.serve()}?view=orb&embedded=1"))
        self._watchdog.start(READY_TIMEOUT_MS)

    # ------------------------------------------------------- CommandGraph API
    def set_center_mode(self, mode: str) -> None:
        state = mode if mode in _STATES else "idle"
        if state != self._state:
            self._state = state
            self._dirty = True

    def set_center_level(self, level: float) -> None:
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self._level) > 1e-3:
            self._level = level
            self._dirty = True

    def set_active(self, active: bool) -> None:
        """Gorunmezken (kucultulmus / icerik paneli acik) WebGL cizimi durur."""
        if active == self._active:
            return
        self._active = active
        self._js(f"window.jarvis.setActive({json.dumps(active)})")

    def set_agents(self, agents: list) -> None:  # noqa: ARG002 - ajanlar AJANLAR kartinda
        pass

    def set_agent_status(self, name: str, status: str) -> None:  # noqa: ARG002
        pass

    # --------------------------------------------------------------- orb API
    def set_thinking(self, thinking: bool) -> None:
        if thinking != self._thinking:
            self._thinking = thinking
            self._dirty = True

    def set_asleep(self, asleep: bool) -> None:
        if asleep != self._asleep:
            self._asleep = asleep
            self._dirty = True

    def set_caption(self, text: str) -> None:
        self._caption = text
        self._js(f"window.jarvis.setCaption({json.dumps(text)})")

    def set_status(self, text: str) -> None:
        self._status = text
        self._js(f"window.jarvis.setStatus({json.dumps(text)})")

    def set_theme(self, theme_: dict) -> None:
        """Kisilik temasi: {persona, accent, base, equator, pole} -> CSS degiskenleri + parcacik renkleri."""
        self._theme = dict(theme_)
        self._js(f"window.jarvis.setTheme && window.jarvis.setTheme({json.dumps(self._theme)})")

    def intro(self) -> None:
        """Orb'u yeniden uzaktan suzulerek getirir."""
        self._js("window.jarvis.intro()")

    @property
    def ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------- internal
    def _js(self, code: str) -> None:
        if self._ready and not self._dead:
            self._view.page().runJavaScript(f"window.jarvis && ({code})")

    def _push_voice(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        payload = {"state": self._state, "level": round(self._level, 4),
                   "thinking": self._thinking, "asleep": self._asleep}
        self._js(f"window.jarvis.setVoice({json.dumps(payload)})")

    def _on_title(self, title: str) -> None:
        event = boot3d.event_of(title)
        if event == "ready":
            self._ready = True
            self._watchdog.stop()
            # sayfa hazir olmadan gelen durum bir seferde aktarilir
            self._js(f"window.jarvis.setCaption({json.dumps(self._caption)})")
            self._js(f"window.jarvis.setStatus({json.dumps(self._status)})")
            self._js(f"window.jarvis.setActive({json.dumps(self._active)})")
            if self._theme:
                self._js(f"window.jarvis.setTheme && window.jarvis.setTheme({json.dumps(self._theme)})")
            self._dirty = True
            self._push_timer.start()
        elif event == "landed":
            self.landed.emit()
        elif event == "mic":
            self.mic_clicked.emit()
        elif event == "error":
            self._fail("sayfa WebGL baslatamadi")

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            self._fail("sayfa yuklenemedi")

    def _on_timeout(self) -> None:
        if not self._ready:
            self._fail(f"{READY_TIMEOUT_MS // 1000} sn icinde hazir olmadi")

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        self._watchdog.stop()
        self._push_timer.stop()
        logger.warning("Orb arayuzu: {}, komuta grafina donuluyor.", reason)
        self.failed.emit()
