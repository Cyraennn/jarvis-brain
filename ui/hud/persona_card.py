"""EKİPLER karti: JARVIS / FRIDAY / ULTRON kisilik cipleri.

Cipler Iron Man 3'teki yapay zeka kartlarina benzer: koyu cerceve, ustte el yazisi
isimli beyaz etiket, altta kendi renginde parlayan devre penceresi. Resim dosyasi
gerekmez, QPainter ile cizilir (her boyutta keskin). Tiklanan cip `selected(key)`
yayar; asil gecisi motor yapar ve `set_active` ile geri bildirir.
"""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from core.personas import CHIPS
from ui.hud.hud_card import HudCard

_HAND_FONTS = ("Ink Free", "Segoe Print", "Comic Sans MS")


def _traces(seed: str, w: float, h: float) -> list[list[QPointF]]:
    """Devre penceresi icin dik acili izler (kisilige gore sabit desen)."""
    rnd = random.Random(seed)
    paths: list[list[QPointF]] = []
    cols = 5
    for i in range(cols):
        x = w * (i + 0.5 + rnd.uniform(-0.18, 0.18)) / cols
        y = h * rnd.uniform(0.0, 0.15) if rnd.random() < 0.5 else 0.0
        pts = [QPointF(x, y)]
        while y < h * 0.92:
            y = min(h, y + h * rnd.uniform(0.14, 0.3))
            pts.append(QPointF(x, y))
            if rnd.random() < 0.55:  # yana kirilma (bacaklar devre gibi gorunsun)
                x = max(3.0, min(w - 3.0, x + rnd.choice((-1, 1)) * w * rnd.uniform(0.08, 0.2)))
                y = min(h, y + h * 0.06)
                pts.append(QPointF(x, y))
        paths.append(pts)
    return paths


class PersonaChip(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, label: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.label = label
        self.color = QColor(color)
        self.active = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{label} kişiliğine geç")
        self.setMinimumSize(56, 84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(100)
        self._font = QFont()
        for family in _HAND_FONTS:
            self._font = QFont(family)
            if self._font.exactMatch():
                break
        self._font.setBold(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(70, 100)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    # ------------------------------------------------------------- etkilesim
    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # ----------------------------------------------------------------- cizim
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lit = 1.0 if self.active else (0.7 if self._hover else 0.42)
        c = QColor(self.color)

        # kartin govdesi (dis parlama pay birakilarak ortalanir)
        cw = min(self.width() - 8.0, (self.height() - 8.0) * 0.62)
        ch = self.height() - 8.0
        body = QRectF((self.width() - cw) / 2.0, 4.0, cw, ch)

        if self.active:  # dis parlama
            for i, alpha in enumerate((26, 44, 70)):
                g = QColor(c)
                g.setAlpha(alpha)
                p.setPen(QPen(g, 6.0 - i * 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(body.adjusted(-1.5, -1.5, 1.5, 1.5), 6, 6)

        frame = QLinearGradient(body.topLeft(), body.bottomRight())
        frame.setColorAt(0.0, QColor("#2a2d33"))
        frame.setColorAt(1.0, QColor("#0d0f12"))
        edge = QColor(c)
        edge.setAlphaF(0.45 + 0.55 * lit)
        p.setPen(QPen(edge, 1.6))
        p.setBrush(frame)
        p.drawRoundedRect(body, 5, 5)

        # ustteki beyaz etiket + el yazisi isim
        pad = cw * 0.1
        label = QRectF(body.left() + pad, body.top() + pad, cw - 2 * pad, ch * 0.2)
        paper = QColor("#f2f0ea") if self.active else QColor("#b9b7b1")
        p.setPen(QPen(QColor(0, 0, 0, 120), 0.8))
        p.setBrush(paper)
        p.drawRect(label)
        font = QFont(self._font)
        font.setPixelSize(max(9, int(label.height() * 0.62)))
        p.setFont(font)
        p.setPen(QColor("#151515"))
        p.drawText(label, Qt.AlignmentFlag.AlignCenter, self.label)

        # devre penceresi
        win = QRectF(label.left(), label.bottom() + pad * 0.8, label.width(),
                     body.bottom() - label.bottom() - pad * 1.8)
        glass = QLinearGradient(win.topLeft(), win.bottomLeft())
        top = QColor(c).darker(260)
        bottom = QColor(c).darker(420)
        glass.setColorAt(0.0, top)
        glass.setColorAt(1.0, bottom)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1.0))
        p.setBrush(glass)
        p.drawRect(win)

        p.save()
        p.setClipRect(win.adjusted(1, 1, -1, -1))
        p.translate(win.topLeft())
        trace = QColor(c).lighter(130)
        for width, alpha in ((4.0, 0.22), (1.6, 1.0)):  # once hale, sonra cizgi
            t = QColor(trace)
            t.setAlphaF(alpha * lit)
            p.setPen(QPen(t, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for pts in _traces(self.key, win.width(), win.height()):
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.drawPath(path)
        pad_color = QColor(trace)
        pad_color.setAlphaF(lit)
        p.setPen(QPen(pad_color, 1.2))
        p.setBrush(QColor(c).darker(300))
        for pts in _traces(self.key, win.width(), win.height()):
            p.drawEllipse(pts[-1], 2.2, 2.2)
        p.restore()
        p.end()


class PersonaCard(HudCard):
    """Sag sutunun en altindaki EKİPLER karti."""

    selected = Signal(str)

    def __init__(self, active: str = "jarvis", parent: QWidget | None = None) -> None:
        super().__init__("EKİPLER", parent=parent)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chips: dict[str, PersonaChip] = {}
        for key, label, color in CHIPS:
            chip = PersonaChip(key, label, color)
            chip.clicked.connect(self.selected.emit)
            self.chips[key] = chip
            row.addWidget(chip)
        self.body.addLayout(row)
        self.set_active(active)

    @property
    def active(self) -> str:
        return next((k for k, c in self.chips.items() if c.active), "jarvis")

    def set_active(self, key: str) -> None:
        if key not in self.chips:
            key = "jarvis"
        for k, chip in self.chips.items():
            chip.set_active(k == key)
        self.set_meta(self.chips[key].label)
