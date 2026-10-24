"""Tam pencere HUD arka plani: saf siyah zemin + ust koselerde vurgu renginde hafif isima (Zoey OS).

Tek katman boyut degismedikce bir kez pixmap'e cizilir (bkz. `BrainGraph._render_static`);
animasyon yoktur. Kisilik efekti (`theme.EFFECT`) de bu katmana islenir: FRIDAY daha parlak
isima + ince nokta izgara, ULTRON altta kizil kor + koyu vinyet. ULTRON'un tarama cizgisi
ve glitch'i ustteki `persona_fx.PersonaOverlay`'dedir.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui import theme


class HudBackdrop(QWidget):
    """Ana pencerenin merkez widget'i; cocuk widget'lar bunun uzerine yerlesir."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._static: QPixmap | None = None
        self._static_key: tuple | None = None
        self.static_renders = 0

    def set_active(self, active: bool) -> None:
        """Animasyon yok; pencere durum degisiminde cagrildigi icin korunur."""

    def refresh_theme(self) -> None:
        """Palet degisti: onbellekteki katmani yeni renk ve efektle yeniden ciz."""
        self._static = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._static is None or self._static_key != key:
            self._static = self._render_static(dpr)
            self._static_key = key
            self.static_renders += 1
        p.drawPixmap(0, 0, self._static)
        p.end()

    def _render_static(self, dpr: float) -> QPixmap:
        w, h = self.width(), self.height()
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.fillRect(0, 0, w, h, QColor(theme.BG_SPACE))
        # Zoey .corner-glow: sol/sag ust koselerde 350 px'lik cok hafif turuncu isima
        c = QColor(theme.ACCENT_BASE)
        effect = theme.EFFECT
        boost = 2.4 if effect == "friday" else 1.0
        for x, alpha in ((75.0, 15), (w - 75.0, 13)):
            glow = QRadialGradient(QPointF(x, 75.0), 175.0 * 0.7 * (1.6 if effect == "friday" else 1.0))
            glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(alpha * boost)))
            glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, w, h, glow)
        if effect == "friday":
            dot = QColor(c.red(), c.green(), c.blue(), 22)
            p.setPen(dot)
            for y in range(12, h, 24):
                for x in range(12, w, 24):
                    p.drawPoint(x, y)
        elif effect == "ultron":
            ember = QRadialGradient(QPointF(w / 2.0, h * 1.05), max(w, h) * 0.55)
            ember.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 38))
            ember.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, w, h, ember)
            vignette = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.75)
            vignette.setColorAt(0.6, QColor(0, 0, 0, 0))
            vignette.setColorAt(1.0, QColor(20, 0, 0, 170))
            p.fillRect(0, 0, w, h, vignette)
        p.end()
        return pm

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._static = None
        super().resizeEvent(event)
