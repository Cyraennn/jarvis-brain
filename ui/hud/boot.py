"""Acilis animasyonu: halkalar cizilerek acilir, "SISTEMLER CEVRIMICI" taramasi, sonra solar.

Pencerenin ustune binen, fare olaylarini gecirgen bir katman. Bir kez oynar ve kendini siler.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui import theme

DURATION_MS = 1600
_LINES = ("ÇEKİRDEK", "SES KANALI", "GÖRÜŞ", "AJAN AĞI", "ARAYÜZ")


class BootOverlay(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._k = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._done)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def start(self) -> None:
        self.raise_()
        self.show()
        self._anim.start()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802, ANN001
        if obj is self.parent() and event.type() == event.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def _on_value(self, value: float) -> None:
        self._k = float(value)
        self.update()

    def _done(self) -> None:
        self.parent().removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        k = self._k
        fade = 1.0 if k < 0.7 else max(0.0, 1.0 - (k - 0.7) / 0.3)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(240 * fade)))

        accent = QColor(theme.ACCENT)
        base = min(w, h) * 0.12
        for i, grow in enumerate((1.0, 1.5, 2.1, 2.8)):
            prog = max(0.0, min(1.0, k * 1.6 - i * 0.12))
            if prog <= 0:
                continue
            r = base * grow
            accent.setAlpha(int(200 * fade * (1 - i * 0.18)))
            p.setPen(QPen(accent, 2.0 if i == 0 else 1.2))
            span = int(-360 * 16 * prog)
            p.drawArc(QRectF(c.x() - r, c.y() - r, r * 2, r * 2), 90 * 16, span)

        gold = QColor(theme.ACCENT_HOVER)
        gold.setAlpha(int(230 * fade))
        p.setPen(QPen(gold, 1.6))
        spin = k * math.tau
        tr = base * 0.45
        pts = [QPointF(c.x() + tr * math.cos(spin + j * math.tau / 3),
                       c.y() + tr * math.sin(spin + j * math.tau / 3)) for j in range(3)]
        for j in range(3):
            p.drawLine(pts[j], pts[(j + 1) % 3])

        f = QFont(p.font())
        f.setPointSize(9)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        p.setFont(f)
        text = QColor(theme.TEXT)
        shown = min(len(_LINES), int(k * 1.4 * len(_LINES)) + 1)
        y0 = c.y() + base * 3.1
        for i in range(shown):
            ok = i < shown - 1 or k > 0.62
            text.setAlpha(int(210 * fade))
            p.setPen(text)
            line = f"{_LINES[i]:<12}{'ÇEVRİMİÇİ' if ok else '...'}"
            p.drawText(QRectF(0, y0 + i * 16, w, 16), Qt.AlignmentFlag.AlignHCenter, line)

        if k > 0.62:
            title = QColor(theme.ACCENT)
            title.setAlpha(int(255 * fade))
            p.setPen(title)
            f.setPointSize(12)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 8)
            p.setFont(f)
            p.drawText(QRectF(0, c.y() - base * 3.3, w, 24), Qt.AlignmentFlag.AlignHCenter,
                       "SİSTEMLER ÇEVRİMİÇİ")
        p.end()
