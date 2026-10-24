"""Kisilige ozgu ust katman efekti (HUD'un en ustunde, fareye seffaf).

Yalniz ULTRON'da etkindir:
  - ince yatay tarama cizgileri (bir kez desen olarak hazirlanir, her boyamada doseme)
  - 4-9 sn'de bir ~120 ms'lik glitch: kayan kizil/camgobegi seritler + kisa titreme.
    `glitched(bool)` sinyali pencereye de iletilir (logo kayar, renk ayrisir).
Diger kisiliklerde katman gizlidir ve zamanlayici durur (bosta maliyet yok).
"""

from __future__ import annotations

import random

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ui import theme

GLITCH_MS = 120
GLITCH_GAP_MS = (4000, 9000)


class PersonaOverlay(QWidget):
    glitched = Signal(bool)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.effect = ""
        self.glitch_active = False
        self._bands: list[tuple[int, int, int, QColor]] = []
        self._rnd = random.Random()
        self._lines = self._scanline_tile()

        self._next = QTimer(self)
        self._next.setSingleShot(True)
        self._next.timeout.connect(self._start_glitch)
        parent.installEventFilter(self)   # ebeveyn boyutunu izle (tum pencereyi ortsun)
        self._end = QTimer(self)
        self._end.setSingleShot(True)
        self._end.timeout.connect(self._stop_glitch)
        self.hide()

    @staticmethod
    def _scanline_tile() -> QPixmap:
        tile = QPixmap(4, 3)
        tile.fill(Qt.GlobalColor.transparent)
        p = QPainter(tile)
        p.fillRect(0, 0, 4, 1, QColor(0, 0, 0, 70))
        p.end()
        return tile

    def eventFilter(self, obj, event) -> bool:  # noqa: N802, ANN001
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    # ------------------------------------------------------------------ API
    @property
    def timer_running(self) -> bool:
        return self._next.isActive() or self._end.isActive()

    def refresh_theme(self) -> None:
        self.set_effect(theme.EFFECT)

    def set_effect(self, effect: str) -> None:
        self.effect = effect
        if effect == "ultron":
            self.setGeometry(self.parentWidget().rect())
            self.show()
            self.raise_()
            self._schedule()
        else:
            self._next.stop()
            self._end.stop()
            if self.glitch_active:
                self._stop_glitch()
            self.hide()

    # ---------------------------------------------------------------- glitch
    def _schedule(self) -> None:
        self._next.start(self._rnd.randint(*GLITCH_GAP_MS))

    def _start_glitch(self) -> None:
        if self.effect != "ultron":
            return
        h = max(1, self.height())
        accent = QColor(theme.ACCENT)
        cyan = QColor(0, 230, 255)
        self._bands = []
        for _ in range(self._rnd.randint(3, 6)):
            y = self._rnd.randint(0, h)
            band_h = self._rnd.randint(2, 18)
            shift = self._rnd.randint(-24, 24)
            color = QColor(accent if self._rnd.random() < 0.6 else cyan)
            color.setAlpha(self._rnd.randint(40, 90))
            self._bands.append((y, band_h, shift, color))
        self.glitch_active = True
        self.glitched.emit(True)
        self.update()
        self._end.start(GLITCH_MS)

    def _stop_glitch(self) -> None:
        self.glitch_active = False
        self._bands = []
        self.glitched.emit(False)
        self.update()
        if self.effect == "ultron":
            self._schedule()

    # ----------------------------------------------------------------- cizim
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        if self.effect != "ultron":
            return
        p = QPainter(self)
        p.drawTiledPixmap(event.rect(), self._lines, event.rect().topLeft())
        if self.glitch_active:
            w = self.width()
            p.fillRect(self.rect(), QColor(255, 0, 0, 14))  # kisa kizil titreme
            for y, band_h, shift, color in self._bands:
                p.fillRect(QRect(shift, y, w, band_h), color)
        p.end()
