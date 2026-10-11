"""Tam pencere HUD arka plani: uzay zemini, ince izgara, vinyet, yavas yatay tarama cizgisi.

Statik katman (zemin + izgara + vinyet) boyut degismedikce bir kez pixmap'e cizilir
(bkz. `BrainGraph._render_static`); her karede yalnizca tarama cizgisi cizilir.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui import theme

GRID_STEP = 34
SCAN_PERIOD_S = 7.0


class HudBackdrop(QWidget):
    """Ana pencerenin merkez widget'i; cocuk widget'lar bunun uzerine yerlesir."""

    FRAME_MS = 50   # tarama cizgisi ~20 FPS yeter

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._static: QPixmap | None = None
        self._static_key: tuple | None = None
        self.static_renders = 0
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._scan_tick)
        self._timer.start()
        self._scan_y = 0.0

    def set_active(self, active: bool) -> None:
        if active:
            self._timer.start()
        else:
            self._timer.stop()

    def _scan_tick(self) -> None:
        phase = ((time.monotonic() - self._t0) % SCAN_PERIOD_S) / SCAN_PERIOD_S
        old = int(self._scan_y)
        self._scan_y = phase * self.height()
        # yalnizca cizginin eski ve yeni seridini yeniden ciz
        self.update(0, max(0, old - 40), self.width(), 60)
        self.update(0, max(0, int(self._scan_y) - 40), self.width(), 60)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._static is None or self._static_key != key:
            self._static = self._render_static(dpr)
            self._static_key = key
            self.static_renders += 1
        p.drawPixmap(0, 0, self._static)

        y = self._scan_y
        grad = QLinearGradient(QPointF(0, y - 36), QPointF(0, y))
        c = QColor(theme.ACCENT)
        grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 0))
        grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 16))
        p.fillRect(0, int(y - 36), self.width(), 36, grad)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 40), 1))
        p.drawLine(0, int(y), self.width(), int(y))
        p.end()

    def _render_static(self, dpr: float) -> QPixmap:
        w, h = self.width(), self.height()
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.fillRect(0, 0, w, h, QColor(theme.BG_SPACE))

        # merkezden hafif cyan isima
        glow = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.6)
        glow.setColorAt(0.0, QColor(18, 48, 64, 90))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, glow)

        grid = QColor(theme.GRID)
        grid.setAlpha(70)
        p.setPen(QPen(grid, 1))
        for x in range(0, w, GRID_STEP):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, GRID_STEP):
            p.drawLine(0, y, w, y)
        # izgara kesisimlerinde minik arti isaretleri (her 4 hucrede bir)
        cross = QColor(theme.ACCENT_DIM)
        cross.setAlpha(110)
        p.setPen(QPen(cross, 1))
        for x in range(0, w, GRID_STEP * 4):
            for y in range(0, h, GRID_STEP * 4):
                p.drawLine(x - 3, y, x + 3, y)
                p.drawLine(x, y - 3, x, y + 3)

        # kenar vinyeti
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vig.setColorAt(0.55, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 170))
        p.fillRect(0, 0, w, h, vig)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.end()
        return pm

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._static = None
        super().resizeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        self._timer.start()
        super().showEvent(event)
